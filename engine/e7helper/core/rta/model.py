"""RTA 胜率 / 选人模型的运行时（B14b）：读随包的 ONNX 模型，用 onnxruntime 推理，只依赖 numpy。

```python
from e7helper.core.rta import model
from e7helper.core.rta.encode import DraftState
m = model.load()                       # 随包 assets/data/rta/，进程内缓存
m.win([state, ...])                    # 每个局面「先手方赢」的概率（不知道谁先动时的）
m.win([state, ...], first=[0.7, ...])  # B14g：按「先手方先动」的概率混合先动 / 后动两种胜率
m.heads([state, ...])                  # B14g：[B, 3] 先手方先动 / 后手方先动 / 不知道 三种情况下先手方赢的概率
m.next_picks(state, k=8)               # 下一手（轮到的一方）最可能选的英雄 [(编号, 概率)]
m.evaluate(states)                     # 一次前向：胜率 + 下一手分布（B14c 搜索用）
m.check()                              # 用 parity.json 核对编码和推理
```
模型文件：`model.onnx`（输出每个位置的 win_logit / pick_logits）、`meta.json`（词表、校准、训练数据和测试指标）、
`parity.json`（一致性样例）。训练和导出在 `core/rta/train`（要 torch，不随包）。

B14g 起 win_logit 是 [B, 17, 3]（三种「谁先动」，encode.FIRST_HEADS），校准每个头一组；模型不看段位（段位只用来算
先动概率，见 `speed.FirstCalc`）。旧格式（[B, 17]，一个头）照样能读：三种情况都是那一个值。
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


def per_head(cal) -> bool:
    """校准参数是不是 B14g 的「每个头一组」（{"F": {...}, "S": {...}, "U": {...}}）。"""
    return isinstance(cal, dict) and all(h in cal for h in encode.FIRST_HEADS)


def calibration_arrays(cal, head: int = encode.HEAD_U) -> tuple[np.ndarray, np.ndarray]:
    """校准参数 → 每个局面的 (斜率, 截距)，各 12 个。cal 是 {"scale": [...], "bias": [...]}；B14g 起每个头一组，
    按 head 取（默认「不知道」那个）；也认早期的温度（一个数或 12 个，等于斜率 1/T、截距 0）。"""
    if per_head(cal):
        cal = cal[encode.FIRST_HEADS[head]]
    if isinstance(cal, dict):
        return np.asarray(cal["scale"], dtype=np.float64), np.asarray(cal["bias"], dtype=np.float64)
    t = np.broadcast_to(np.asarray(cal, dtype=np.float64), (encode.N_STATES,))
    return 1.0 / t, np.zeros(encode.N_STATES)


def calibrate(z: np.ndarray, state: np.ndarray, cal, head: int = encode.HEAD_U) -> np.ndarray:
    """胜率头的 logit → 校准后的概率：σ(斜率[n] · z + 截距[n])。z 和 state 形状相同（或 state 能广播到 z）。"""
    scale, bias = calibration_arrays(cal, head)
    return 1.0 / (1.0 + np.exp(-(scale[state] * z.astype(np.float64) + bias[state])))


def calibrate_heads(z: np.ndarray, state: np.ndarray, cal) -> np.ndarray:
    """z [..., 3]（三个头的 logit）→ 各自校准后的概率 [..., 3]；state 的形状是 z 去掉最后一维（或能广播过去）。
    旧格式 z [...]（一个头）→ 三列一样。"""
    if z.ndim == np.ndim(state):
        p = calibrate(z, state, cal)
        return np.repeat(p[..., None], encode.N_HEADS, axis=-1)
    return np.stack([calibrate(z[..., h], state, cal, h) for h in range(encode.N_HEADS)], axis=-1)


FIRST_TAU = 0.1  # 先动 / 后动两种胜率差这么多时，模型隐含的先动概率和速度表各占一半（见 effective_first）


def _logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=np.float64), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def effective_first(heads: np.ndarray, first, ref=None, tau: float = FIRST_TAU) -> np.ndarray:
    """混合用的「先手方先动」概率（B14g1）。first = 速度表按双方段位 + 英雄池速度算的；ref = 同一阵容按「不知道段位、
    没填速度」（一般玩家）算的。ref 不给就直接用 first。

    π = σ(logit first + w · (logit q − logit ref))：q 是模型自己隐含的先动概率（「不知道」的头 = q × 先手方先动时
    + (1 − q) × 后手方先动时，由三个头反推），w = 差² / (差² + τ²)，差 = 两种胜率之差。
    - 两种胜率差得多（抢一速要紧）：以模型从对局里学到的「一般玩家这一局谁先动」为底，段位 / 英雄池速度只带来
      first 相对 ref 的变化量。B14h 快照的测试期：官方速度直方图混着 PvE 配装，偏偏在抢速的阵容上最不准，直接用
      速度表混合比「不知道」的头还差，这样混合反而更好（见 reviews/B14g1.md）；
    - 差得少（谁先动无所谓）：反推的 q 不稳，退回速度表（这时混合结果几乎不受影响，主要为了显示的先动概率稳定）。
    双方一般玩家（first = ref）时混合结果正好接近「不知道」的头。"""
    f = np.asarray(first, dtype=np.float64)
    if ref is None:
        return np.broadcast_to(f, heads.shape[:-1]).copy()
    pf, ps, pu = heads[..., encode.HEAD_F], heads[..., encode.HEAD_S], heads[..., encode.HEAD_U]
    gap = pf - ps
    q = (pu - ps) / np.where(np.abs(gap) > 1e-6, gap, 1.0)
    w = gap * gap / (gap * gap + tau * tau)
    z = _logit(f) + w * (_logit(np.clip(q, 1e-3, 1 - 1e-3)) - _logit(ref))
    return 1.0 / (1.0 + np.exp(-z))


def mix(heads: np.ndarray, first, ref=None) -> np.ndarray:
    """三种情况的概率 [..., 3] + 「先手方先动」的概率 first（能广播到 [...]；None = 不知道）→ 先手方赢的概率。
    π × 先手方先动时的 + (1 − π) × 后手方先动时的（B14g 用户原则：段位只影响谁先动，胜率按先动概率混合）；
    π = effective_first(heads, first, ref)（ref 不给时 π = first）。"""
    if first is None:
        return heads[..., encode.HEAD_U]
    f = effective_first(heads, first, ref)
    return f * heads[..., encode.HEAD_F] + (1.0 - f) * heads[..., encode.HEAD_S]


def win_heads(win_logit: np.ndarray, state: np.ndarray, cal) -> np.ndarray:
    """win_logit [B, 17]（或 [B, 17, 3]）→ 每个局面自己的读出位置上三种情况「先手方赢」的概率 [B, 3]。"""
    z = win_logit[np.arange(len(state)), encode.STATE_POS[state]]
    return calibrate_heads(z, state, cal)


def win_prob(win_logit: np.ndarray, state: np.ndarray, cal, first=None, ref=None) -> np.ndarray:
    """win_logit → 每个局面「先手方赢」的概率 [B]：first（每个局面先手方先动的概率）给了就混合，否则用「不知道」的。"""
    return mix(win_heads(win_logit, state, cal), first, ref)


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
    win: np.ndarray  # [B] 先手方赢的概率（给了先动概率就是混合的，否则是「不知道谁先动」的）
    picks: np.ndarray  # [B, V] 下一手的概率（英雄编号见 vocab）
    state: np.ndarray  # [B] 局面编号
    heads: np.ndarray | None = None  # [B, 3] 先手方先动 / 后手方先动 / 不知道 三种情况下先手方赢的概率（B14g）


class RtaModel:
    def __init__(self, folder: Path):
        import onnxruntime as ort

        started = time.perf_counter()
        self.folder = folder
        self.meta = json.loads((folder / META_FILE).read_text(encoding="utf-8"))
        self.vocab = encode.Vocab.from_dict(self.meta["vocab"])
        # 每个局面一组斜率 + 截距（Platt 缩放，在验证集上拟合）；B14g 起每个头一组
        self.calibration = self.meta.get("calibration") or self.meta.get("temperature", 1.0)
        # B14g：胜率头分三种「谁先动」、不看段位（旧模型两项都是 False / True）
        self.first = bool(self.meta.get("first_heads"))
        self.grades = bool(self.meta.get("grades", True))
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(folder / MODEL_FILE), opts, providers=["CPUExecutionProvider"])
        self.load_seconds = time.perf_counter() - started

    def run(self, heroes: np.ndarray, ctx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """原始输出：win_logit [B, 17]（B14g 起 [B, 17, 3]）、pick_logits [B, 17, V]（分批跑）。"""
        wins, picks = [], []
        for s in range(0, len(heroes), MAX_BATCH):
            w, p = self.session.run(None, {"heroes": np.ascontiguousarray(heroes[s:s + MAX_BATCH], dtype=np.int64),
                                           "ctx": np.ascontiguousarray(ctx[s:s + MAX_BATCH], dtype=np.int64)})
            wins.append(w)
            picks.append(p)
        return np.concatenate(wins), np.concatenate(picks)

    def evaluate(self, states: Sequence[encode.DraftState], first=None, ref=None) -> Evaluation:
        """first：每个局面「先手方先动」的概率（[B] 或一个数）；None = 不知道（用「不知道」的头）。
        ref：同一局面按一般玩家（不知道段位、没填速度）算的先动概率，给了就按 `effective_first` 混合
        （`speed.first_pair` 一次给出两个）。"""
        x = encode.encode_states(states, self.vocab)
        win, pick = self.run(x["heroes"], x["ctx"])
        heads = win_heads(win, x["state"], self.calibration)
        return Evaluation(win=mix(heads, first, ref), picks=pick_probs(pick, x["heroes"], x["state"], self.vocab.size),
                          state=x["state"], heads=heads)

    def win(self, states: Sequence[encode.DraftState], first=None, ref=None) -> np.ndarray:
        return self.evaluate(states, first, ref).win

    def all_states(self, heroes: np.ndarray, ctx: np.ndarray) -> np.ndarray:
        """编码好的整场（heroes [B, 17]、ctx [B, 3]，例如 `Dataset.encode`）→ 12 个局面三种情况先手方赢的概率
        [B, 12, 3]（评估、开发工具用；旧模型三列一样）。分批跑、不留选人输出（整份测试集的选人输出有几 GB）。"""
        out = []
        for s in range(0, len(heroes), MAX_BATCH):
            w, _ = self.run(heroes[s:s + MAX_BATCH], ctx[s:s + MAX_BATCH])
            out.append(calibrate_heads(w[:, encode.STATE_POS], np.arange(encode.N_STATES)[None, :], self.calibration))
        return np.concatenate(out) if out else np.zeros((0, encode.N_STATES, encode.N_HEADS))

    def heads(self, states: Sequence[encode.DraftState]) -> np.ndarray:
        """[B, 3]：先手方先动 / 后手方先动 / 不知道 三种情况下先手方赢的概率（旧模型三列一样）。"""
        return self.evaluate(states).heads

    def next_picks(self, state: encode.DraftState, k: int = 8) -> list[tuple[str, float]]:
        probs = self.evaluate([state]).picks[0]
        top = [int(i) for i in np.argsort(-probs)[:k] if probs[i] > 0]
        return [(self.vocab.code(i), float(probs[i])) for i in top]

    def check(self) -> dict:
        """parity.json 核对：编码一致、胜率（B14g 起三个头）和下一手前 8 名的概率差都在容差内。"""
        parity = json.loads((self.folder / PARITY_FILE).read_text(encoding="utf-8"))
        tol = float(parity.get("tolerance", 1e-5))
        states = [encode.DraftState.from_dict(c["state"]) for c in parity["cases"]]
        x = encode.encode_states(states, self.vocab)
        ev = self.evaluate(states)
        enc_ok = all(x["heroes"][i].tolist() == c["heroes"] and x["ctx"][i].tolist() == c["ctx"]
                     for i, c in enumerate(parity["cases"]))
        diffs = [abs(ev.win[i] - c["win"]) for i, c in enumerate(parity["cases"])]
        diffs += [abs(ev.heads[i, h] - p) for i, c in enumerate(parity["cases"]) for h, p in enumerate(c.get("heads", []))]
        win_diff = float(max(diffs))
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
