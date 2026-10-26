"""RTA 胜率 / 选人模型的运行时（B14b）：读随包的 ONNX 模型，用 onnxruntime 推理，只依赖 numpy。

```python
from e7helper.core.rta import model
from e7helper.core.rta.encode import DraftState
m = model.load()                       # 随包 assets/data/rta/，进程内缓存
m.win([state, ...])                    # 每个局面「先手方赢」的概率
m.next_picks(state, k=8)               # 下一手（轮到的一方）最可能选的英雄 [(编号, 概率)]
m.evaluate(states)                     # 一次前向：胜率 + 下一手分布（B14c 搜索用）
m.check()                              # 用 parity.json 核对编码和推理
```
模型文件：`model.onnx`（输出每个位置的 win_logit / pick_logits）、`meta.json`（词表、温度、训练数据和测试指标）、
`parity.json`（一致性样例）。训练和导出在 `core/rta/train`（要 torch，不随包）。
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .. import paths
from . import encode

MODEL_FILE = "model.onnx"
META_FILE = "meta.json"
PARITY_FILE = "parity.json"
MAX_BATCH = 1024  # 一次送进 onnxruntime 的局面数


def bundled_dir() -> Path:
    return paths.bundled_data_dir("rta")


def calibration_arrays(cal) -> tuple[np.ndarray, np.ndarray]:
    """校准参数 → 每个局面的 (斜率, 截距)，各 12 个。cal 是 {"scale": [...], "bias": [...]}；
    也认早期的温度（一个数或 12 个，等于斜率 1/T、截距 0）。"""
    if isinstance(cal, dict):
        return np.asarray(cal["scale"], dtype=np.float64), np.asarray(cal["bias"], dtype=np.float64)
    t = np.broadcast_to(np.asarray(cal, dtype=np.float64), (encode.N_STATES,))
    return 1.0 / t, np.zeros(encode.N_STATES)


def calibrate(z: np.ndarray, state: np.ndarray, cal) -> np.ndarray:
    """胜率头的 logit → 校准后的概率：σ(斜率[n] · z + 截距[n])。z 和 state 形状相同（或 state 能广播到 z）。"""
    scale, bias = calibration_arrays(cal)
    return 1.0 / (1.0 + np.exp(-(scale[state] * z.astype(np.float64) + bias[state])))


def win_prob(win_logit: np.ndarray, state: np.ndarray, cal) -> np.ndarray:
    """win_logit [B, 17] → 每个局面自己的读出位置上「先手方赢」的概率 [B]。"""
    z = win_logit[np.arange(len(state)), encode.STATE_POS[state]]
    return calibrate(z, state, cal)


def pick_probs(pick_logits: np.ndarray, heroes: np.ndarray, state: np.ndarray, size: int) -> np.ndarray:
    """pick_logits [B, 17, V] → 下一手的概率 [B, V]（不能选的是 0；选完了的局面整行是 0）。"""
    out = np.zeros((len(state), size))
    live = state < encode.N_PICKS
    if not live.any():
        return out
    idx = np.flatnonzero(live)
    z = pick_logits[idx, encode.STATE_POS[state[idx]]].astype(np.float64)
    ok = encode.pick_mask(heroes[idx], state[idx], size)
    z = np.where(ok, z, -np.inf)
    z -= z.max(axis=1, keepdims=True)
    e = np.exp(z)
    out[idx] = e / e.sum(axis=1, keepdims=True)
    return out


@dataclass
class Evaluation:
    win: np.ndarray  # [B] 先手方赢的概率
    picks: np.ndarray  # [B, V] 下一手的概率（英雄编号见 vocab）
    state: np.ndarray  # [B] 局面编号


class RtaModel:
    def __init__(self, folder: Path):
        import onnxruntime as ort

        started = time.perf_counter()
        self.folder = folder
        self.meta = json.loads((folder / META_FILE).read_text(encoding="utf-8"))
        self.vocab = encode.Vocab.from_dict(self.meta["vocab"])
        # 每个局面一组斜率 + 截距（Platt 缩放，在验证集上拟合）
        self.calibration = self.meta.get("calibration") or self.meta.get("temperature", 1.0)
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(folder / MODEL_FILE), opts, providers=["CPUExecutionProvider"])
        self.load_seconds = time.perf_counter() - started

    def run(self, heroes: np.ndarray, ctx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """原始输出：win_logit [B, 17]、pick_logits [B, 17, V]（分批跑）。"""
        wins, picks = [], []
        for s in range(0, len(heroes), MAX_BATCH):
            w, p = self.session.run(None, {"heroes": np.ascontiguousarray(heroes[s:s + MAX_BATCH], dtype=np.int64),
                                           "ctx": np.ascontiguousarray(ctx[s:s + MAX_BATCH], dtype=np.int64)})
            wins.append(w)
            picks.append(p)
        return np.concatenate(wins), np.concatenate(picks)

    def evaluate(self, states: Sequence[encode.DraftState]) -> Evaluation:
        x = encode.encode_states(states, self.vocab)
        win, pick = self.run(x["heroes"], x["ctx"])
        return Evaluation(win=win_prob(win, x["state"], self.calibration),
                          picks=pick_probs(pick, x["heroes"], x["state"], self.vocab.size), state=x["state"])

    def win(self, states: Sequence[encode.DraftState]) -> np.ndarray:
        return self.evaluate(states).win

    def next_picks(self, state: encode.DraftState, k: int = 8) -> list[tuple[str, float]]:
        probs = self.evaluate([state]).picks[0]
        top = [int(i) for i in np.argsort(-probs)[:k] if probs[i] > 0]
        return [(self.vocab.code(i), float(probs[i])) for i in top]

    def check(self) -> dict:
        """parity.json 核对：编码一致、胜率和下一手前 8 名的概率差都在容差内。"""
        parity = json.loads((self.folder / PARITY_FILE).read_text(encoding="utf-8"))
        tol = float(parity.get("tolerance", 1e-5))
        states = [encode.DraftState.from_dict(c["state"]) for c in parity["cases"]]
        x = encode.encode_states(states, self.vocab)
        ev = self.evaluate(states)
        enc_ok = all(x["heroes"][i].tolist() == c["heroes"] and x["ctx"][i].tolist() == c["ctx"]
                     for i, c in enumerate(parity["cases"]))
        win_diff = float(max(abs(ev.win[i] - c["win"]) for i, c in enumerate(parity["cases"])))
        # 前 8 名每名的概率都对得上，名次自然一致（只有概率差 < 容差的并列可能换位）
        pick_diff = float(max((abs(ev.picks[i, self.vocab.hero(code)] - p) for i, c in enumerate(parity["cases"])
                               for code, p in c.get("top", [])), default=0.0))
        return {"cases": len(states), "encode_ok": enc_ok, "win_diff": win_diff, "pick_diff": pick_diff,
                "tolerance": tol, "ok": enc_ok and win_diff <= tol and pick_diff <= tol}


@lru_cache(maxsize=4)
def _load(folder: str) -> RtaModel:
    return RtaModel(Path(folder))


def load(folder: Path | None = None) -> RtaModel:
    """读模型（默认随包的），同一目录只读一次。"""
    return _load(str(folder or bundled_dir()))


def available(folder: Path | None = None) -> bool:
    folder = folder or bundled_dir()
    return all((folder / f).exists() for f in (MODEL_FILE, META_FILE))
