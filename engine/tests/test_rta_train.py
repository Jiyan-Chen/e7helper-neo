"""B14b：RTA 模型的网络、训练循环、评估（要 torch：python -m uv sync --group train，没装就跳过）。"""

import json
import math

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from e7helper.core.rta import encode  # noqa: E402
from e7helper.core.rta.train import evaluate, fit, nets  # noqa: E402
from rta_fakes import synthetic_dataset  # noqa: E402


@pytest.fixture(scope="module")
def ds():
    return synthetic_dataset()


@pytest.fixture(scope="module")
def batch(ds):
    vocab = ds.vocab(np.arange(len(ds)), min_picks=1)
    x = ds.encode(vocab)
    return vocab, torch.as_tensor(x["heroes"][:32]), torch.as_tensor(x["ctx"][:32]), torch.as_tensor(x["y"][:32])


@pytest.mark.parametrize("kind", list(nets.MODELS))
def test_models_shapes(batch, kind):
    vocab, h, c, y = batch
    model = nets.build(kind, vocab.size, vocab.n_rules, d=16, layers=1, k=4)
    win, pick = model.predict(h, c)
    assert win.shape == (32, encode.N_STATES)
    assert (pick is None) == (not model.has_pick)
    if pick is not None:
        assert pick.shape == (32, encode.N_PICKS, vocab.size)
    wl, pc, _, _ = nets.losses(model, h, c, y, vocab.size)
    assert torch.isfinite(wl) and (pc is None or torch.isfinite(pc))


def test_hero_lr_sums_strength(batch):
    vocab, h, c, _ = batch
    model = nets.HeroLR(vocab.size, vocab.n_rules)
    with torch.no_grad():
        model.strength.weight.copy_(torch.arange(vocab.size, dtype=torch.float32)[:, None])
        model.strength.weight[encode.PAD] = 0
    win, _ = model.predict(h, c)
    row = h[0].tolist()
    f = [row[encode.PICK_POS + k] for k, s in enumerate("FSSFFSSFFS") if s == "F"]
    s = [row[encode.PICK_POS + k] for k, s_ in enumerate("FSSFFSSFFS") if s_ == "S"]
    assert win[0, 0] == 0  # 还没选人
    assert win[0, 3] == f[0] - s[0] - s[1]
    assert win[0, 10] == sum(f) - sum(s)
    assert win[0, 11] == sum(f) - sum(s) - row[15] + row[16]  # 后禁后去掉双方被禁的


def test_fm_members_drop_banned(batch):
    vocab, h, _, _ = batch
    model = nets.FactorizationMachine(vocab.size, vocab.n_rules, k=4)
    mf, ms = model._members(h)
    assert mf[0, 10].sum() == 5 and ms[0, 10].sum() == 5
    assert mf[0, 11].sum() == 4 and ms[0, 11].sum() == 4
    picks = h[0, :15]
    assert not (mf[0, 11] * (picks == h[0, 15])).any() and not (ms[0, 11] * (picks == h[0, 16])).any()
    # 对子项：两两内积 = 直接求和
    e = torch.randn(1, 15, 4)
    m = torch.zeros(1, 12, 15)
    m[0, 0, [5, 8, 9]] = 1
    direct = sum((e[0, i] * e[0, j]).sum() for i, j in ((5, 8), (5, 9), (8, 9)))
    assert torch.isclose(model._pairs(m, e)[0, 0], direct, atol=1e-5)


def test_pick_available_matches_numpy(batch):
    vocab, h, _, _ = batch
    t = nets.pick_available(h, vocab.size).numpy()
    for n in range(encode.N_PICKS):
        ref = encode.pick_mask(h.numpy(), np.full(len(h), n), vocab.size)
        ref[:, encode.UNK] = True  # 训练里 UNK 算一类、可选；运行时推荐不出 UNK
        assert np.array_equal(t[:, n], ref)
    tgt, w = nets.pick_targets(h)
    assert tgt.shape == (32, 10, 2) and torch.allclose(w.sum(-1), torch.ones(10))
    assert t[np.arange(32)[:, None], np.arange(10)[None, :], tgt[..., 0].numpy()].all()  # 目标总是可选的


def test_fit_calibration():
    from e7helper.core.rta.model import calibrate, calibration_arrays

    rng = np.random.default_rng(0)
    z = rng.normal(size=20000)
    y = (rng.random(20000) < 1 / (1 + np.exp(-z))).astype(np.float32)
    # 第 0 列过度自信 2 倍；第 1 列过于保守并且整体偏向后手
    logits = np.stack([2.0 * z, 0.5 * z - 0.15], axis=1)
    cal = evaluate.fit_calibration(logits, y)
    assert math.isclose(cal["scale"][0], 0.5, rel_tol=0.08) and abs(cal["bias"][0]) < 0.05
    assert math.isclose(cal["scale"][1], 2.0, rel_tol=0.08) and math.isclose(cal["bias"][1], 0.3, abs_tol=0.05)
    p = calibrate(logits, np.arange(2)[None, :], cal)
    assert abs(p[:, 1].mean() - y.mean()) < 0.01
    # 早期的温度格式也认：斜率 1/T、截距 0
    s, b = calibration_arrays(2.0)
    assert np.allclose(s, 0.5) and np.allclose(b, 0) and len(s) == 12


def test_popularity_and_infer(ds):
    vocab = ds.vocab(np.arange(len(ds)), min_picks=1)
    x = ds.encode(vocab)
    pop = evaluate.popularity(x["heroes"], vocab.size)
    assert pop.shape == (10, vocab.size) and (pop[:, :encode.FIRST_HERO] == 0).all()
    model = nets.build("transformer", vocab.size, vocab.n_rules, d=16, layers=1)
    out = evaluate.infer(model, x["heroes"], x["ctx"], vocab.size, batch=128, pop=pop)
    assert out["win"].shape == (len(ds), 12)
    for key in ("pick", "pop"):
        s = out[key]
        assert 0 <= s["top1"] <= s["top5"] <= s["top8"] <= 1 and len(s["per_state"]) == 10


def test_train_writes_run(ds, tmp_path):
    cfg = fit.TrainConfig(model="transformer", d=16, layers=1, heads=2, epochs=3, batch=64, test_days=6, val_days=6,
                          min_picks=1, warmup=5, log_every=3, patience=5, device="cpu")
    result = fit.train(ds, cfg, out_dir=tmp_path / "run")
    run = tmp_path / "run"
    assert result["status"] == "done" and result["epochs_run"] == 3
    assert len(result["calibration"]["scale"]) == len(result["calibration"]["bias"]) == encode.N_STATES  # 每个局面一组
    for name in ("config.json", "vocab.json", "metrics.jsonl", "status.json", "best.pt", "result.json"):
        assert (run / name).exists()
    lines = [json.loads(line) for line in (run / "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [line["kind"] for line in lines]
    assert kinds.count("val") == 3 and kinds[-1] == "end" and "step" in kinds
    val = next(line for line in lines if line["kind"] == "val")
    assert {"loss", "win_loss", "n10", "n11", "n11_champ", "pick", "best_epoch", "bad_epochs", "train_win_loss",
            "train_n11", "lr"} <= set(val)
    assert json.loads((run / "status.json").read_text(encoding="utf-8"))["status"] == "done"
    model, vocab, ckpt = fit.load_run(run)
    assert ckpt["calibration"] == result["calibration"] and vocab.size == ckpt["n_heroes"]
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    assert config["data"]["val"] > 0 and config["data"]["test"] > 0


def test_lr_learns_signal(ds, tmp_path):
    cfg = fit.TrainConfig(model="lr", epochs=8, batch=32, lr=0.05, test_days=6, val_days=6, min_picks=1, warmup=1,
                          device="cpu", log_every=100)
    result = fit.train(ds, cfg, out_dir=tmp_path / "lr")
    assert result["best_val"]["n10"]["auc"] > 0.65  # c0–c2 在哪边决定胜负


def test_full_and_stop(ds, tmp_path):
    import threading

    cal = {"scale": [1.1] * 12, "bias": [0.01] * 12}
    cfg = fit.TrainConfig(model="fm", k=4, epochs=2, batch=64, full=True, calibration=cal, min_picks=1, device="cpu")
    result = fit.train(ds, cfg, out_dir=tmp_path / "full")
    assert result["status"] == "done" and result["calibration"] == cal and result["best_epoch"] == 2
    stop = threading.Event()
    stop.set()
    result = fit.train(ds, fit.TrainConfig(model="lr", epochs=3, min_picks=1, device="cpu"), out_dir=tmp_path / "stop",
                       stop=stop)
    assert result["status"] == "stopped"


def test_lr_schedules():
    cfg = fit.TrainConfig(lr=1e-3, warmup=10)
    assert fit._lr_at(0, 100, cfg) == pytest.approx(1e-4) and fit._lr_at(10, 100, cfg) == pytest.approx(1e-3)
    assert fit._lr_at(99, 100, cfg) == pytest.approx(5e-5, rel=0.01)  # 余弦退火到 5%
    const = fit.TrainConfig(lr=1e-3, warmup=10, schedule="constant")
    assert fit._lr_at(99, 100, const) == fit._lr_at(50, 100, const) == 1e-3


@pytest.mark.parametrize("after, epochs_run", [(1.0, 2), (0.0, 3)])
def test_patience_counts_only_after_lr_decays(ds, tmp_path, after, epochs_run):
    # 学习率几乎为 0：验证损失不会再变好。patience_after=1 时一开始就计数（第 2 轮停）；=0 时永远不计数（跑满）
    cfg = fit.TrainConfig(model="lr", epochs=3, lr=1e-12, warmup=1, patience=1, patience_after=after, min_picks=1,
                          device="cpu", test_days=6, val_days=6)
    result = fit.train(ds, cfg, out_dir=tmp_path / "run")
    assert result["epochs_run"] == epochs_run and result["best_epoch"] == 1
