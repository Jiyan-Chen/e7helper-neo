"""把训练好的 Transformer 导出成随包模型（B14b）：model.onnx + meta.json + parity.json。

- ONNX：`torch.onnx.export(dynamo=True, opset 18)`，批次维动态；输入 heroes [B, 17] / ctx [B, 3]（int64），
  输出 win_logit [B, 17]（B14g 起 [B, 17, 3]：先手方先动 / 后手方先动 / 不知道）/ pick_logits [B, 17, V]
  （每个位置都输出，运行时按局面取）。B14g 起模型不看 ctx 里的段位，但输入格式不变。
- parity.json：几十个真实局面（DraftState）+ 编码结果 + torch 算出的期望输出，运行时 `rta model --check` 和测试用它
  核对编码和推理都没走样。
- 导出后立刻用 onnxruntime 跑一遍，和 torch 比最大误差。
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
import torch

from .. import encode
from ..model import MODEL_FILE, META_FILE, PARITY_FILE, mix, pick_probs, win_heads


class _Export(torch.nn.Module):
    def __init__(self, model: torch.nn.Module):
        super().__init__()
        self.model = model

    def forward(self, heroes: torch.Tensor, ctx: torch.Tensor):
        return self.model(heroes, ctx)


def export_onnx(model: torch.nn.Module, path: Path, opset: int = 18) -> None:
    model = model.cpu().eval()
    heroes = torch.full((4, encode.SEQ_LEN), encode.FIRST_HERO, dtype=torch.long)
    ctx = torch.zeros((4, 3), dtype=torch.long)
    batch = torch.export.Dim("batch", min=1, max=1 << 16)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(_Export(model).eval(), (heroes, ctx), str(path), input_names=["heroes", "ctx"],
                      output_names=["win_logit", "pick_logits"], dynamic_shapes={"heroes": {0: batch}, "ctx": {0: batch}},
                      opset_version=opset, dynamo=True, external_data=False)


@torch.no_grad()
def torch_outputs(model: torch.nn.Module, heroes: np.ndarray, ctx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    model = model.cpu().eval()
    win, pick = model(torch.as_tensor(heroes), torch.as_tensor(ctx))
    return win.numpy(), pick.numpy()


def make_parity(model: torch.nn.Module, vocab: encode.Vocab, calibration,
                states: list[encode.DraftState]) -> dict:
    """parity 样例：每个局面的输入、期望胜率（先手方，不知道谁先动时的）、期望下一手前 8 名；
    B14g 三头模型另存三种情况的胜率 heads。"""
    x = encode.encode_states(states, vocab)
    win, pick = torch_outputs(model, x["heroes"], x["ctx"])
    heads = win_heads(win, x["state"], calibration)
    p_win = mix(heads, None)
    probs = pick_probs(pick, x["heroes"], x["state"], vocab.size)
    cases = []
    for i, st in enumerate(states):
        case = {"state": st.to_dict(), "heroes": x["heroes"][i].tolist(), "ctx": x["ctx"][i].tolist(),
                "win": float(p_win[i])}
        if win.ndim == 3:
            case["heads"] = [float(v) for v in heads[i]]
        if st.state < encode.N_PICKS:
            top = np.argsort(-probs[i])[:8]
            case["top"] = [[vocab.code(int(j)), float(probs[i, j])] for j in top]
        cases.append(case)
    return {"tolerance": 1e-5, "cases": cases}


def onnx_vs_torch(model: torch.nn.Module, path: Path, heroes: np.ndarray, ctx: np.ndarray) -> dict:
    """onnxruntime 和 torch 在同一批输入上的最大误差（logit 和概率）。"""
    import onnxruntime as ort

    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    win_t, pick_t = torch_outputs(model, heroes, ctx)
    win_o, pick_o = sess.run(None, {"heroes": heroes, "ctx": ctx})
    sig = lambda z: 1 / (1 + np.exp(-z))  # noqa: E731
    return {"n": int(len(heroes)), "win_logit": float(np.abs(win_t - win_o).max()),
            "pick_logit": float(np.abs(pick_t - pick_o).max()), "win_prob": float(np.abs(sig(win_t) - sig(win_o)).max())}


def write_bundle(model: torch.nn.Module, vocab: encode.Vocab, ckpt: dict, out: Path, *, states: list[encode.DraftState],
                 check_inputs: tuple[np.ndarray, np.ndarray], info: dict) -> dict:
    """导出到 out/（随包是 engine/assets/data/rta/）：model.onnx、meta.json、parity.json；返回一致性检查结果。"""
    out.mkdir(parents=True, exist_ok=True)
    onnx_path = out / MODEL_FILE
    export_onnx(model, onnx_path)
    cfg = ckpt["config"]
    first = bool(cfg.get("first", False))
    ident = {"scale": [1.0] * encode.N_STATES, "bias": [0.0] * encode.N_STATES}
    calibration = ckpt.get("calibration") or ({h: ident for h in encode.FIRST_HEADS} if first else ident)
    parity = make_parity(model, vocab, calibration, states)
    (out / PARITY_FILE).write_text(json.dumps(parity, ensure_ascii=False), encoding="utf-8")
    check = onnx_vs_torch(model, onnx_path, *check_inputs)
    meta = {
        "format": 2 if first else 1, "kind": cfg["model"], "built": time.strftime("%Y-%m-%d %H:%M:%S"),
        "torch": torch.__version__, "grades": bool(cfg.get("grades", True)),
        **({"first_heads": list(encode.FIRST_HEADS)} if first else {}),
        "opset": 18, "calibration": calibration, "vocab": vocab.to_dict(), "params": ckpt.get("params"),
        "arch": {k: cfg[k] for k in ("d", "layers", "heads", "dropout", "lam", "k")}, "epoch": ckpt.get("epoch"),
        "sha256": hashlib.sha256(onnx_path.read_bytes()).hexdigest(), "onnx_vs_torch": check, **info,
    }
    (out / META_FILE).write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return check
