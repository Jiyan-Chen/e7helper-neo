"""B14b：RTA 模型的网络、训练循环、评估（要 torch：python -m uv sync --group train，没装就跳过）。
B14g：默认结构不看段位、胜率头分三种「谁先动」；旧结构（grades=True、first=False）照样能建、能读。"""

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


@pytest.fixture(scope="module")
def heads32(ds):
    vocab = ds.vocab(np.arange(len(ds)), min_picks=1)
    return torch.as_tensor(ds.encode(vocab)["head"][:32])


@pytest.mark.parametrize("kind", list(nets.MODELS))
@pytest.mark.parametrize("old", [False, True])
def test_models_shapes(batch, heads32, kind, old):
    vocab, h, c, y = batch
    flags = {"grades": True, "first": False} if old else {}
    model = nets.build(kind, vocab.size, vocab.n_rules, d=16, layers=1, k=4, **flags)
    win, pick = model.predict(h, c)
    assert win.shape == ((32, encode.N_STATES) if old else (32, encode.N_STATES, encode.N_HEADS))
    assert (pick is None) == (not model.has_pick)
    if pick is not None:
        assert pick.shape == (32, encode.N_PICKS, vocab.size)
    wl, pc, _, _ = nets.losses(model, h, c, y, vocab.size, None if old else heads32)
    assert torch.isfinite(wl) and (pc is None or torch.isfinite(pc))


def test_grades_ignored_by_new_models(batch):
    vocab, h, c, _ = batch
    torch.manual_seed(0)
    for kind in ("hybrid", "fm"):
        model = nets.build(kind, vocab.size, vocab.n_rules, d=16, layers=1, k=4).eval()
        assert not any("grade" in name for name, _ in model.named_parameters())
        c2 = c.clone()
        c2[:, :2] = (c2[:, :2] + 3) % encode.N_GRADES
        with torch.no_grad():
            assert torch.equal(model.predict(h, c)[0], model.predict(h, c2)[0])


def test_first_term_heads(batch):
    """先动敏感度：先手方先动 − 后手方先动 = 2 × (常数 + 在场英雄的敏感度之和)；不知道 = 基础 + 偏移。"""
    vocab, h, c, _ = batch
    model = nets.HeroLR(vocab.size, vocab.n_rules, grades=False, first=True)
    with torch.no_grad():
        model.first.t.weight.copy_(torch.arange(vocab.size, dtype=torch.float32)[:, None] / 100)
        model.first.t.weight[encode.PAD] = 0
        model.first.state.fill_(0.5)
        model.first.unknown.fill_(-0.25)
        win, _ = model.predict(h, c)
    base = win[..., encode.HEAD_U] + 0.25
    row = h[0].tolist()
    picks = row[encode.PICK_POS:encode.PICK_POS + 10]
    gap = win[0, :, encode.HEAD_F] - win[0, :, encode.HEAD_S]
    assert gap[0].item() == pytest.approx(1.0)  # 还没选人：只有常数
    assert gap[3].item() == pytest.approx(2 * (0.5 + sum(picks[:3]) / 100), abs=1e-5)
    assert gap[11].item() == pytest.approx(2 * (0.5 + (sum(picks) - row[15] - row[16]) / 100), abs=1e-5)
    assert torch.allclose((win[..., encode.HEAD_F] + win[..., encode.HEAD_S]) / 2, base, atol=1e-5)


def test_win_loss_uses_known_first_mover():
    win = torch.zeros(4, encode.N_STATES, encode.N_HEADS)
    win[..., encode.HEAD_F] = 5.0  # 先手方先动的头说「先手方一定赢」
    y = torch.tensor([1.0, 1.0, 0.0, 0.0])
    head = torch.tensor([encode.HEAD_F, encode.HEAD_U, encode.HEAD_S, encode.HEAD_U])

    def ll(z: float, t: float) -> float:
        return torch.nn.functional.binary_cross_entropy_with_logits(torch.tensor(z), torch.tensor(t)).item()

    # 4 场「不知道」头（都是 0 logit）+ 已知的 2 场（第 1 场用 F 头 5.0、第 3 场用 S 头 0.0）
    expect = (4 * ll(0.0, 1.0) + ll(5.0, 1.0) + ll(0.0, 0.0)) / 6
    assert nets.win_loss_of(win, y, head).item() == pytest.approx(expect, rel=1e-5)
    assert nets.win_loss_of(win, y, None).item() == pytest.approx(ll(0.0, 1.0), rel=1e-5)
    assert fit.win_loss_np(win.numpy(), y.numpy(), head.numpy()) == pytest.approx(expect, rel=1e-4)


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
    # B14g 三个头：先手方先动的头只用先手方先动的对局拟合
    head = rng.integers(0, 3, 20000)
    l3 = np.stack([logits] * 3, axis=2)
    l3[head == encode.HEAD_F, :, encode.HEAD_F] = 0.0  # 先手方先动的对局里 F 头没信息
    cal3 = evaluate.fit_calibration(l3, y, head)
    assert set(cal3) == set(encode.FIRST_HEADS)
    assert math.isclose(cal3["S"]["scale"][0], 0.5, rel_tol=0.1) and math.isclose(cal3["U"]["scale"][0], 0.5, rel_tol=0.1)
    s, _ = calibration_arrays(cal3, encode.HEAD_S)
    assert s[0] == cal3["S"]["scale"][0]


def test_popularity_and_infer(ds):
    vocab = ds.vocab(np.arange(len(ds)), min_picks=1)
    x = ds.encode(vocab)
    pop = evaluate.popularity(x["heroes"], vocab.size)
    assert pop.shape == (10, vocab.size) and (pop[:, :encode.FIRST_HERO] == 0).all()
    model = nets.build("transformer", vocab.size, vocab.n_rules, d=16, layers=1)
    out = evaluate.infer(model, x["heroes"], x["ctx"], vocab.size, batch=128, pop=pop)
    assert out["win"].shape == (len(ds), 12, 3)
    for key in ("pick", "pop"):
        s = out[key]
        assert 0 <= s["top1"] <= s["top5"] <= s["top8"] <= 1 and len(s["per_state"]) == 10


def test_train_writes_run(ds, tmp_path):
    cfg = fit.TrainConfig(model="transformer", d=16, layers=1, heads=2, epochs=3, batch=64, test_days=6, val_days=6,
                          min_picks=1, warmup=5, log_every=3, patience=5, device="cpu")
    result = fit.train(ds, cfg, out_dir=tmp_path / "run")
    run = tmp_path / "run"
    assert result["status"] == "done" and result["epochs_run"] == 3
    assert set(result["calibration"]) == set(encode.FIRST_HEADS)  # B14g：每个头一组
    for cal in result["calibration"].values():
        assert len(cal["scale"]) == len(cal["bias"]) == encode.N_STATES  # 每个局面一组
    for name in ("config.json", "vocab.json", "metrics.jsonl", "status.json", "best.pt", "result.json"):
        assert (run / name).exists()
    lines = [json.loads(line) for line in (run / "metrics.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [line["kind"] for line in lines]
    assert kinds.count("val") == 3 and kinds[-1] == "end" and "step" in kinds
    val = next(line for line in lines if line["kind"] == "val")
    assert {"loss", "win_loss", "n10", "n11", "n11_champ", "pick", "best_epoch", "bad_epochs", "train_win_loss",
            "train_n11", "lr", "n11_first", "n11_first_u"} <= set(val)
    assert json.loads((run / "status.json").read_text(encoding="utf-8"))["status"] == "done"
    model, vocab, ckpt = fit.load_run(run)
    assert ckpt["calibration"] == result["calibration"] and vocab.size == ckpt["n_heroes"]
    config = json.loads((run / "config.json").read_text(encoding="utf-8"))
    assert config["data"]["val"] > 0 and config["data"]["test"] > 0
    assert config["grades"] is False and config["first"] is True and config["first_known"]["train"] > 0


def test_old_runs_load_with_old_structure(ds, tmp_path):
    """B14g 之前的 run（设置里没有 grades / first）按旧结构读：看段位、一个胜率头。"""
    cfg = fit.TrainConfig(model="fm", k=4, epochs=1, batch=64, grades=True, first=False, test_days=6, val_days=6,
                          min_picks=1, device="cpu")
    result = fit.train(ds, cfg, out_dir=tmp_path / "old")
    assert len(result["calibration"]["scale"]) == 12  # 一个头：旧格式的校准
    ckpt = torch.load(tmp_path / "old" / "best.pt", weights_only=False)
    del ckpt["config"]["grades"], ckpt["config"]["first"]
    torch.save(ckpt, tmp_path / "old" / "best.pt")
    model, vocab, _ = fit.load_run(tmp_path / "old")
    assert model.bias.grades and model.first is None
    x = ds.encode(vocab, np.arange(8))
    win, _ = model.predict(torch.as_tensor(x["heroes"]), torch.as_tensor(x["ctx"]))
    assert win.shape == (8, encode.N_STATES)


def test_first_mover_signal_learned(ds, tmp_path):
    """合成数据里 c3 先动才厉害：学到的敏感度明显高于别的英雄；知道谁先动的头比「不知道」的好。"""
    cfg = fit.TrainConfig(model="lr", epochs=8, batch=32, lr=0.05, test_days=6, val_days=6, min_picks=1, warmup=1,
                          device="cpu", log_every=100)
    result = fit.train(ds, cfg, out_dir=tmp_path / "lr")
    model, vocab, _ = fit.load_run(tmp_path / "lr")
    t = model.first.t.weight.detach().numpy()[:, 0]
    c3 = vocab.hero("c3")
    others = np.delete(t[encode.FIRST_HERO:], c3 - encode.FIRST_HERO)
    assert t[c3] > others.mean() + 3 * others.std()
    v = result["best_val"]
    assert v["n11_first"]["log_loss"] < v["n11_first_u"]["log_loss"]


def test_lr_learns_signal(ds, tmp_path):
    cfg = fit.TrainConfig(model="lr", epochs=8, batch=32, lr=0.05, test_days=6, val_days=6, min_picks=1, warmup=1,
                          device="cpu", log_every=100)
    result = fit.train(ds, cfg, out_dir=tmp_path / "lr")
    assert result["best_val"]["n10"]["auc"] > 0.65  # c0–c2 在哪边决定胜负


def test_full_and_stop(ds, tmp_path):
    import threading

    cal = {h: {"scale": [1.1] * 12, "bias": [0.01] * 12} for h in encode.FIRST_HEADS}
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


def test_evaluate_run_first_report(ds, tmp_path):
    """B14g1：三头模型的评估给混合 / 只用速度表 / 不知道 / 知道谁先动、先动差分布、先动概率准确度，先动概率另存 npy。"""
    from e7helper.core.rta.speed import SpeedTable

    cfg = fit.TrainConfig(model="fm", k=4, epochs=1, batch=64, test_days=6, val_days=6, min_picks=1, device="cpu")
    fit.train(ds, cfg, out_dir=tmp_path / "run")
    hist = lambda k: [0] * k + [1000] + [0] * (9 - k)  # noqa: E731
    table = SpeedTable.from_hists({f"c{i}": {"legend": hist(i % 10)} for i in range(40)}, jitter=5.0)
    res = evaluate.evaluate_run(tmp_path / "run", ds, "test", speed_table=table)
    assert res["mix"] == "speed"
    for key in ("win", "win_speed", "win_unknown", "win_first", "win_first_u"):
        assert set(res[key]["all"]) == {str(n) for n in range(12)}
    assert {"段位:同档", "段位:差1档"} <= set(res["win"])
    assert res["known"] == int((ds.first_mover[ds.split(6, 6)["test"]] >= 0).sum())
    assert set(res["first_gap"]) == {"10", "11"} and 0 <= res["first_gap"]["11"]["ge10"] <= 1
    assert 0 < res["first_prob"]["log_loss"] and 0 < res["first_prob_speed"]["log_loss"]
    first = np.load(tmp_path / "run" / "eval-test-first.npy")
    assert first.shape == (res["n"], 12) and (tmp_path / "run" / "eval-test-first-ref.npy").exists()
    json.loads((tmp_path / "run" / "eval-test.json").read_text(encoding="utf-8"))  # 能存成 JSON（没有数组）
