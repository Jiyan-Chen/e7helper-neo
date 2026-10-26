"""B14b：Transformer 导出 ONNX → onnxruntime 推理和 torch 一致、parity 核对、运行时接口（要 torch）。"""

import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("onnxscript")

from e7helper.core.rta import encode  # noqa: E402
from e7helper.core.rta import model as rmodel  # noqa: E402
from e7helper.core.rta.train import export, fit  # noqa: E402
from rta_fakes import synthetic_dataset  # noqa: E402


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    ds = synthetic_dataset(n=400)
    root = tmp_path_factory.mktemp("rta")
    cfg = fit.TrainConfig(model="transformer", d=16, layers=1, heads=2, epochs=1, batch=64, min_picks=1, device="cpu",
                          test_days=6, val_days=6, warmup=2)
    fit.train(ds, cfg, out_dir=root / "run")
    model, vocab, ckpt = fit.load_run(root / "run")
    rows = np.arange(len(ds))[-40:]
    states = [ds.state(int(r), n % 12) for n, r in enumerate(rows)]
    x = ds.encode(vocab, rows)
    out = root / "bundle"
    check = export.write_bundle(model, vocab, ckpt, out, states=states, check_inputs=(x["heroes"], x["ctx"]),
                                info={"run": "test"})
    return ds, model, vocab, ckpt, out, check


def test_onnx_matches_torch(bundle):
    _, _, _, _, out, check = bundle
    assert check["n"] == 40
    assert check["win_logit"] < 1e-4 and check["pick_logit"] < 1e-4 and check["win_prob"] < 1e-5
    meta = json.loads((out / rmodel.META_FILE).read_text(encoding="utf-8"))
    assert meta["kind"] == "transformer" and meta["opset"] == 18 and meta["run"] == "test"
    assert set(p.name for p in out.iterdir()) >= {rmodel.MODEL_FILE, rmodel.META_FILE, rmodel.PARITY_FILE}


def test_runtime_parity_and_api(bundle):
    ds, model, vocab, ckpt, out, _ = bundle
    m = rmodel.RtaModel(out)
    res = m.check()
    assert res["ok"] and res["cases"] == 40 and res["encode_ok"]
    assert m.calibration == ckpt["calibration"] and len(m.calibration["scale"]) == 12
    states = [ds.state(5, n) for n in range(12)]
    ev = m.evaluate(states)
    assert ev.win.shape == (12,) and ((ev.win > 0) & (ev.win < 1)).all()
    assert np.allclose(ev.picks[:10].sum(axis=1), 1) and (ev.picks[10:] == 0).all()
    # 不能选的（已选、被预禁、PAD / UNK）概率是 0
    x = encode.encode_states(states, vocab)
    ok = encode.pick_mask(x["heroes"], x["state"], vocab.size)
    assert (ev.picks[:10][~ok[:10]] == 0).all()
    top = m.next_picks(states[3], k=5)
    assert len(top) == 5 and all(c and c.startswith("c") for c, _ in top)
    assert [p for _, p in top] == sorted((p for _, p in top), reverse=True)
    assert m.win(states[:2]).tolist() == pytest.approx(ev.win[:2].tolist())


def test_runtime_batches_and_parity_detects_change(bundle, tmp_path):
    ds, _, vocab, _, out, _ = bundle
    m = rmodel.RtaModel(out)
    states = [ds.state(int(i % len(ds)), int(i % 12)) for i in range(rmodel.MAX_BATCH + 7)]
    ev = m.evaluate(states)
    assert ev.win.shape == (len(states),)
    # parity 里的期望改一下 → 核对不通过
    bad = tmp_path / "bad"
    bad.mkdir()
    for f in out.iterdir():
        (bad / f.name).write_bytes(f.read_bytes())
    parity = json.loads((bad / rmodel.PARITY_FILE).read_text(encoding="utf-8"))
    parity["cases"][0]["win"] += 0.01
    (bad / rmodel.PARITY_FILE).write_text(json.dumps(parity), encoding="utf-8")
    assert not rmodel.RtaModel(bad).check()["ok"]


def test_hybrid_exports_and_matches_torch(tmp_path):
    ds = synthetic_dataset(n=300)
    cfg = fit.TrainConfig(model="hybrid", d=16, layers=1, heads=2, k=4, epochs=1, batch=64, min_picks=1, device="cpu",
                          test_days=6, val_days=6, warmup=2)
    fit.train(ds, cfg, out_dir=tmp_path / "run")
    model, vocab, ckpt = fit.load_run(tmp_path / "run")
    rows = np.arange(len(ds))[-24:]
    x = ds.encode(vocab, rows)
    check = export.write_bundle(model, vocab, ckpt, tmp_path / "bundle", states=[ds.state(int(r), 11) for r in rows[:6]],
                                check_inputs=(x["heroes"], x["ctx"]), info={})
    assert check["win_logit"] < 1e-4 and check["pick_logit"] < 1e-4
    assert rmodel.RtaModel(tmp_path / "bundle").check()["ok"]
    # 宽部分（因子分解机）确实加在读出位置上
    with torch.no_grad():
        h, c = torch.as_tensor(x["heroes"]), torch.as_tensor(x["ctx"])
        full, _ = model(h, c)
        deep, _ = super(type(model), model).forward(h, c)
        wide, _ = model.fm.predict(h, c)
    assert torch.allclose((full - deep)[:, torch.as_tensor(encode.STATE_POS)], wide, atol=1e-5)
