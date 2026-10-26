"""RTA 模型的训练循环（B14b）：读快照 → 训练 → 每轮验证 → 早停 → 校准，过程写进 run 目录给曲线页看。

run 目录（默认 F:\\e7helper-data\\rta\\runs\\<名字>\\）：
- `config.json`：训练设置 + 数据快照 + 词表大小（开头写）；
- `metrics.jsonl`：每 log_every 步一行 `{"kind": "step", ...}`，每轮结束一行 `{"kind": "val", ...}`，结束一行 `{"kind": "end"}`；
- `status.json`：运行中 / 完成 / 中断、当前轮、剩余时间（曲线页和终端都看它）；
- `best.pt`：验证最好的一轮（全量重训时是最后一轮），含权重、设置、词表、校准参数；`result.json`：结果摘要。
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch

from .. import encode, metrics
from ..dataset import Dataset
from . import evaluate, nets, runs_dir


@dataclass
class TrainConfig:
    name: str = ""
    model: str = "transformer"  # lr0 / lr / fm / transformer / hybrid
    d: int = 64
    layers: int = 2
    heads: int = 4
    dropout: float = 0.1
    k: int = 16  # 因子分解机的隐向量维度
    lam: float = 1.0  # 选人损失的权重
    lr: float = 2e-3
    weight_decay: float = 0.01
    batch: int = 512
    epochs: int = 30
    # 0 = 跑满整个周期、按验证集保存最好的一轮（默认）。学习率还高时验证损失常停在平台上，等退火才再降，
    # 所以早停只在学习率降到峰值的 patience_after 以下之后才计数
    patience: int = 0
    patience_after: float = 0.3
    schedule: str = "cosine"  # cosine（余弦退火到 5%）/ constant（预热后恒定，grokking 实验用，排除退火的影响）
    warmup: int = 500  # 预热步数
    train_eval: int = 50_000  # 每轮在这么多场训练数据上用评估模式算一次胜率损失（看训练 / 验证差距），0 = 不算
    unk_rate: float = 0.02  # 训练时把英雄换成 UNK 的概率
    min_picks: int = 30
    test_days: int = 7
    val_days: int = 7
    full: bool = False  # 全量重训：不留验证 / 测试，跑满 epochs，校准用 calibration
    calibration: dict | None = None  # 全量重训时用切分训练在验证集上拟合的（每个局面一组斜率 + 截距）
    device: str = "auto"
    threads: int = 0  # CPU 线程数，0 = torch 默认
    seed: int = 0
    log_every: int = 50
    max_steps: int = 0  # 只跑这么多步（测速 / 测试用），0 = 不限
    dataset: str = ""
    extra: dict = field(default_factory=dict)

    def run_name(self) -> str:
        if self.name:
            return self.name
        if self.model in ("transformer", "hybrid"):
            base = f"{'tf' if self.model == 'transformer' else 'hy'}-d{self.d}-L{self.layers}-lam{self.lam:g}"
        elif self.model == "fm":
            base = f"fm-k{self.k}"
        else:
            base = self.model
        return base + ("-full" if self.full else "")


def pick_device(name: str) -> str:
    if name == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return name


class RunLog:
    """run 目录的写入：metrics.jsonl 追加、status.json 覆盖。"""

    def __init__(self, path: Path):
        self.path = path
        path.mkdir(parents=True, exist_ok=True)
        self.metrics = (path / "metrics.jsonl").open("w", encoding="utf-8")

    def write(self, kind: str, **data) -> None:
        self.metrics.write(json.dumps({"kind": kind, "t": round(time.time(), 2), **data}, ensure_ascii=False) + "\n")
        self.metrics.flush()

    def status(self, **data) -> None:
        tmp = self.path / "status.json.tmp"
        tmp.write_text(json.dumps({"updated": round(time.time(), 2), **data}, ensure_ascii=False), encoding="utf-8")
        # Windows：曲线页正好打开着 status.json 时改名会被拒绝（WinError 5），重试几次；还不行就跳过这一次，
        # 状态文件只给人看，下次还会写（B14b 踩过：训练进程因此整个崩掉）
        for _ in range(10):
            try:
                tmp.replace(self.path / "status.json")
                return
            except PermissionError:
                time.sleep(0.05)

    def close(self) -> None:
        self.metrics.close()


def _lr_at(step: int, total: int, cfg: TrainConfig) -> float:
    if step < cfg.warmup:
        return cfg.lr * (step + 1) / cfg.warmup
    if cfg.schedule == "constant":
        return cfg.lr
    frac = (step - cfg.warmup) / max(1, total - cfg.warmup)
    return cfg.lr * (0.05 + 0.95 * 0.5 * (1 + math.cos(math.pi * min(1.0, frac))))


def _val(model, data: dict, size: int, device: str, champ: np.ndarray, lam: float) -> dict:
    """验证：两种损失 + n = 10 / 11 的胜率指标（全部 / 双方 ≥ 优胜者）+ 选人命中率。"""
    out = evaluate.infer(model, data["heroes"], data["ctx"], size, device=device)
    y = data["y"]
    win = out["win"]
    p = evaluate.sigmoid(win)
    win_loss = float(np.mean([metrics.log_loss(p[:, n], y) for n in range(encode.N_STATES)]))
    res = {"win_loss": win_loss}
    for n in (10, 11):
        res[f"n{n}"] = metrics.win_metrics(p[:, n], y)
        res[f"n{n}_champ"] = metrics.win_metrics(p[champ, n], y[champ])
    if "pick" in out:
        pk = out["pick"]
        res["pick"] = {k: pk[k] for k in ("ce", "top1", "top5", "top8")}
        res["total"] = win_loss + lam * pk["ce"]
    # 早停只看胜率损失（门槛看的是胜率）：选人那部分后期会过拟合，总损失会让胜率还在变好时就停下
    res["loss"] = win_loss
    res["_win_logits"] = win
    return res


def _train_eval(model, data: dict, size: int, device: str) -> dict:
    """训练子集上（评估模式：不 dropout、不换 UNK）的胜率损失，和验证集的同一口径对比。"""
    p = evaluate.sigmoid(evaluate.infer(model, data["heroes"], data["ctx"], size, device=device)["win"])
    y = data["y"]
    return {"train_win_loss": float(np.mean([metrics.log_loss(p[:, n], y) for n in range(encode.N_STATES)])),
            "train_n11": metrics.log_loss(p[:, encode.POSTBAN], y)}


def train(ds: Dataset, cfg: TrainConfig, *, out_dir: Path | None = None, stop: threading.Event | None = None,
          on_step: Callable[[dict], None] | None = None, on_epoch: Callable[[dict], None] | None = None) -> dict:
    """训练一个模型，返回结果摘要（也写进 run 目录的 result.json）。Ctrl+C / stop 事件 → 停下，保留最好的一轮。"""
    torch.manual_seed(cfg.seed)
    np.random.seed(cfg.seed)
    device = pick_device(cfg.device)
    if cfg.threads and device == "cpu":
        torch.set_num_threads(cfg.threads)
    run = out_dir or runs_dir() / cfg.run_name()
    log = RunLog(run)

    parts = ds.split(0 if cfg.full else cfg.test_days, cfg.val_days)
    vocab = ds.vocab(parts["train"], cfg.min_picks)
    train_np = ds.encode(vocab, parts["train"])
    val_np = ds.encode(vocab, parts["val"]) if len(parts["val"]) else None
    sub_rows = np.random.default_rng(cfg.seed).permutation(len(train_np["y"]))[:cfg.train_eval]
    train_sub = {k: v[sub_rows] for k, v in train_np.items()} if cfg.train_eval and val_np is not None else None
    champ = ds.champion_plus()[parts["val"]] if val_np is not None else None
    size = vocab.size
    model = nets.build(cfg.model, size, vocab.n_rules, d=cfg.d, layers=cfg.layers, heads=cfg.heads,
                       dropout=cfg.dropout, k=cfg.k).to(device)
    params = sum(p.numel() for p in model.parameters())
    config = {**asdict(cfg), "device": device, "run": str(run), "params": params, "vocab_size": size,
              "n_rules": vocab.n_rules, "data": {k: int(len(v)) for k, v in parts.items()},
              "dataset_meta": {k: ds.meta.get(k) for k in ("season", "until", "first_day", "last_day", "kept")},
              "torch": torch.__version__}
    (run / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=1), encoding="utf-8")
    vocab.save(run / "vocab.json")

    heroes = torch.as_tensor(train_np["heroes"], device=device)
    ctx = torch.as_tensor(train_np["ctx"], device=device)
    y = torch.as_tensor(train_np["y"], device=device)
    n_train = len(y)
    steps_per_epoch = math.ceil(n_train / cfg.batch)
    total = steps_per_epoch * cfg.epochs if not cfg.max_steps else cfg.max_steps
    opt = torch.optim.AdamW(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    gen = torch.Generator(device="cpu").manual_seed(cfg.seed)

    best = {"loss": float("inf"), "epoch": 0}
    bad_epochs = 0
    step = 0
    started = time.time()
    status = "running"
    last_val: dict = {}
    epoch = 0
    log.status(status=status, epoch=0, epochs=cfg.epochs, step=0, total_steps=total, eta=None, device=device)
    try:
        for epoch in range(1, cfg.epochs + 1):
            model.train()
            perm = torch.randperm(n_train, generator=gen).to(device)
            sums = {"loss": 0.0, "win": 0.0, "pick": 0.0, "n": 0}
            t_log, done_log = time.time(), 0
            for b in range(steps_per_epoch):
                if stop is not None and stop.is_set():
                    raise KeyboardInterrupt
                idx = perm[b * cfg.batch:(b + 1) * cfg.batch]
                h, c, yy = heroes[idx], ctx[idx], y[idx]
                if cfg.unk_rate > 0:
                    swap = (torch.rand(h.shape, device=device) < cfg.unk_rate) & (h >= encode.FIRST_HERO)
                    h = torch.where(swap, torch.full_like(h, encode.UNK), h)
                for group in opt.param_groups:
                    group["lr"] = _lr_at(step, total, cfg)
                win_loss, pick_ce, _, _ = nets.losses(model, h, c, yy, size)
                loss = win_loss + cfg.lam * pick_ce if pick_ce is not None else win_loss
                opt.zero_grad(set_to_none=True)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                opt.step()
                step += 1
                # 累计在设备上，记录时才取回（每步 float() 会让 GPU 同步）
                sums["loss"] += loss.detach()
                sums["win"] += win_loss.detach()
                sums["pick"] += pick_ce.detach() if pick_ce is not None else 0.0
                sums["n"] += 1
                done_log += len(idx)
                if step % cfg.log_every == 0 or b == steps_per_epoch - 1:
                    sums = {k: float(v) for k, v in sums.items()}
                    now = time.time()
                    speed = done_log / max(now - t_log, 1e-6)
                    t_log, done_log = now, 0
                    elapsed = now - started
                    eta = elapsed / step * (total - step)
                    rec = {"epoch": epoch, "step": step, "frac": round(epoch - 1 + (b + 1) / steps_per_epoch, 4),
                           "loss": sums["loss"] / sums["n"], "win": sums["win"] / sums["n"],
                           "pick": sums["pick"] / sums["n"] if model.has_pick else None,
                           "lr": opt.param_groups[0]["lr"], "speed": round(speed), "eta": round(eta)}
                    log.write("step", **rec)
                    log.status(status=status, epoch=epoch, epochs=cfg.epochs, step=step, total_steps=total, eta=round(eta),
                               device=device, best_epoch=best["epoch"], bad_epochs=bad_epochs)
                    if on_step:
                        on_step(rec)
                    sums = {"loss": 0.0, "win": 0.0, "pick": 0.0, "n": 0}
                if cfg.max_steps and step >= cfg.max_steps:
                    break
            # —— 每轮结束 ——
            if val_np is not None:
                v = _val(model, val_np, size, device, champ, cfg.lam)
                logits = v.pop("_win_logits")
                if train_sub is not None:
                    v.update(_train_eval(model, train_sub, size, device))
                lr_now = opt.param_groups[0]["lr"]
                improved = v["loss"] < best["loss"] - 1e-5
                if improved:
                    best = {"loss": v["loss"], "epoch": epoch, "val": v}
                    bad_epochs = 0
                    _save(run / "best.pt", model, cfg, vocab, epoch, None, config)
                    np.save(run / "val_logits.npy", logits.astype(np.float32))
                elif lr_now <= cfg.patience_after * cfg.lr:  # 学习率还高时的平台不算
                    bad_epochs += 1
                last_val = {"epoch": epoch, **v, "best_epoch": best["epoch"], "bad_epochs": bad_epochs,
                            "improved": improved, "lr": lr_now}
                log.write("val", **last_val)
                if on_epoch:
                    on_epoch(last_val)
                if cfg.patience and bad_epochs >= cfg.patience:
                    break
            else:
                _save(run / "best.pt", model, cfg, vocab, epoch, cfg.calibration, config)
                best = {"loss": float("nan"), "epoch": epoch}
                if on_epoch:
                    on_epoch({"epoch": epoch})
            if cfg.max_steps and step >= cfg.max_steps:
                break
        status = "done"
    except KeyboardInterrupt:
        status = "stopped"

    calibration = cfg.calibration
    if val_np is not None and (run / "val_logits.npy").exists():
        calibration = evaluate.fit_calibration(np.load(run / "val_logits.npy"), val_np["y"])
        ckpt = torch.load(run / "best.pt", map_location="cpu", weights_only=False)
        ckpt["calibration"] = calibration
        torch.save(ckpt, run / "best.pt")
    result = {"run": str(run), "status": status, "device": device, "params": params, "epochs_run": epoch,
              "best_epoch": best["epoch"], "best_val": best.get("val"), "calibration": calibration,
              "seconds": round(time.time() - started, 1), "steps": step}
    (run / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    log.write("end", status=status, best_epoch=best["epoch"], seconds=result["seconds"])
    log.status(status=status, epoch=epoch, epochs=cfg.epochs, step=step, total_steps=total, eta=0, device=device,
               best_epoch=best["epoch"], bad_epochs=bad_epochs)
    log.close()
    return result


def _save(path: Path, model, cfg: TrainConfig, vocab: encode.Vocab, epoch: int, calibration: dict | None,
          config: dict) -> None:
    torch.save({"state_dict": model.state_dict(), "config": asdict(cfg), "vocab": vocab.to_dict(), "epoch": epoch,
                "calibration": calibration, "n_heroes": vocab.size, "n_rules": vocab.n_rules,
                "params": config["params"]}, path)


def load_run(run: Path, device: str = "cpu") -> tuple[torch.nn.Module, encode.Vocab, dict]:
    """读 run 目录的 best.pt → (模型, 词表, checkpoint)。"""
    ckpt = torch.load(run / "best.pt", map_location=device, weights_only=False)
    cfg = ckpt["config"]
    model = nets.build(cfg["model"], ckpt["n_heroes"], ckpt["n_rules"], d=cfg["d"], layers=cfg["layers"],
                       heads=cfg["heads"], dropout=cfg["dropout"], k=cfg["k"])
    model.load_state_dict(ckpt["state_dict"])
    model.to(device).eval()
    return model, encode.Vocab.from_dict(ckpt["vocab"]), ckpt
