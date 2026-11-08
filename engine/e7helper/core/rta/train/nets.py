"""RTA 模型的网络（B14b）：Transformer 和三个基线，输入都是 encode 的 heroes [B, 17] + ctx [B, 3]。

统一接口 `predict(heroes, ctx) -> (win [B, 12] 或 [B, 12, 3], pick [B, 10, V] 或 None)`：
win 是 12 个局面「先手方赢」的 logit，pick 是已选 n = 0…9 手时下一手的 logit（还没屏蔽不可选的）。
只用 torch 2.9 也有的接口（GPU 训练环境是 ROCm 版 torch 2.9）。

B14g 两个开关（`build(grades=, first=)`，旧 run 的设置里没有这两项 = 旧结构 grades=True、first=False）：
- grades：CTX 加不加双方段位档。新模型不加（战绩站的段位是赛后的，会把比赛结果漏进来）；
- first：胜率头分三种「谁先动」（encode.FIRST_HEADS：先手方先动 / 后手方先动 / 不知道），win 多一维 [.., 3]。
  先动 / 后动的差 = Transformer 两个头的差 + 2 × Δ，Δ = 每个局面一个常数 + 在场英雄各自的「先动敏感度」之和
  （`FirstTerm`，可解释的部分）；「不知道」是单独的头（不是两者的平均：有的阵容本来就几乎总是先动）。
"""

from __future__ import annotations

import math

import torch
import torch.nn.functional as F
from torch import nn

from .. import encode, rules

NEG = -1e9  # 注意力和选人屏蔽用的大负数（不用 -inf，导出 ONNX 后数值更稳）

STATE_POS = torch.as_tensor(encode.STATE_POS)
PICK_STATE_POS = STATE_POS[:encode.N_PICKS]  # 局面 0…9 的读出位置
HEAD_SIGN = torch.tensor([1.0, -1.0, 0.0])  # 三个头里 Δ 的符号：先手方先动 +、后手方先动 −、不知道 0


def _coef_matrix() -> torch.Tensor:
    """[12, 17]：局面 n 时每个位置的英雄算哪一方（先手 +1、后手 −1、不算 0）；n = 11 再减掉被禁的。"""
    c = torch.zeros(encode.N_STATES, encode.SEQ_LEN)
    for n in range(encode.N_STATES):
        for k in range(min(n, encode.N_PICKS)):
            c[n, encode.PICK_POS + k] = 1.0 if rules.PICK_ORDER[k] == "F" else -1.0
    c[encode.POSTBAN, encode.BAN_POS["F"]] = -1.0
    c[encode.POSTBAN, encode.BAN_POS["S"]] = 1.0
    return c


def _field_matrix() -> torch.Tensor:
    """[12, 17]：局面 n 时在场的英雄（不分哪一方）：已选的 +1；后禁之后再减掉双方被禁的那名。"""
    c = torch.zeros(encode.N_STATES, encode.SEQ_LEN)
    for n in range(encode.N_STATES):
        c[n, encode.PICK_POS:encode.PICK_POS + min(n, encode.N_PICKS)] = 1.0
    c[encode.POSTBAN, encode.BAN_POS["F"]] = -1.0
    c[encode.POSTBAN, encode.BAN_POS["S"]] = -1.0
    return c


class ContextBias(nn.Module):
    """先手 + 段位（旧结构）+ 开战规则 + 局面编号的偏置（三个基线共用）。"""

    def __init__(self, n_rules: int, grades: bool = True):
        super().__init__()
        self.grades = grades
        self.state = nn.Parameter(torch.zeros(encode.N_STATES))
        if grades:
            self.grade_f = nn.Embedding(encode.N_GRADES, encode.N_STATES)
            self.grade_s = nn.Embedding(encode.N_GRADES, encode.N_STATES)
            nn.init.zeros_(self.grade_f.weight)
            nn.init.zeros_(self.grade_s.weight)
        self.rule = nn.Embedding(n_rules, encode.N_STATES)
        nn.init.zeros_(self.rule.weight)

    def forward(self, ctx: torch.Tensor) -> torch.Tensor:
        out = self.state + self.rule(ctx[:, 2])
        if self.grades:
            out = out + self.grade_f(ctx[:, 0]) + self.grade_s(ctx[:, 1])
        return out


class FirstTerm(nn.Module):
    """先动的影响（B14g）：Δ [B, 12] = 每个局面一个常数 + 在场英雄各自的「先动敏感度」之和。

    敏感度 tₕ = 英雄 h 所在的一方先动时比后动时（logit）多出的一半，不分在哪一方：先手方的英雄在先手方先动时 +tₕ；
    后手方的英雄在后手方先动时让先手方 −tₕ、在先手方先动时 +tₕ，所以两种情况的差都是 2 × Σ tₕ。
    `heads(base)` → 三个头 [B, 12, 3]：base + Δ、base − Δ、base + 每个局面一个「不知道」的偏移。"""

    def __init__(self, n_heroes: int, per_hero: bool = True):
        super().__init__()
        self.state = nn.Parameter(torch.zeros(encode.N_STATES))
        self.unknown = nn.Parameter(torch.zeros(encode.N_STATES))
        self.per_hero = per_hero
        if per_hero:
            self.t = nn.Embedding(n_heroes, 1, padding_idx=encode.PAD)
            nn.init.zeros_(self.t.weight)
        self.register_buffer("field", _field_matrix())
        self.register_buffer("sign", HEAD_SIGN.clone())
        self.register_buffer("is_unknown", torch.tensor([0.0, 0.0, 1.0]))

    def delta(self, heroes: torch.Tensor) -> torch.Tensor:
        d = self.state.expand(heroes.shape[0], -1)
        if self.per_hero:
            d = d + self.t(heroes).squeeze(-1) @ self.field.T
        return d

    def heads(self, base: torch.Tensor, heroes: torch.Tensor) -> torch.Tensor:
        d = self.delta(heroes)
        return base[..., None] + d[..., None] * self.sign + self.unknown[:, None] * self.is_unknown


class ContextLR(nn.Module):
    """B0：只看先手、开战规则（旧结构还有段位）；first 时加每个局面一个先动常数。"""
    has_pick = False

    def __init__(self, n_heroes: int, n_rules: int, grades: bool = True, first: bool = False):
        super().__init__()
        self.bias = ContextBias(n_rules, grades)
        self.first = FirstTerm(n_heroes, per_hero=False) if first else None

    def predict(self, heroes, ctx):
        out = self.bias(ctx)
        return (self.first.heads(out, heroes) if self.first is not None else out), None


class HeroLR(nn.Module):
    """B1：B0 + 每名英雄一个强度（先手方 +、后手方 −，后禁之后去掉被禁的）；first 时加先动敏感度。"""
    has_pick = False

    def __init__(self, n_heroes: int, n_rules: int, grades: bool = True, first: bool = False):
        super().__init__()
        self.bias = ContextBias(n_rules, grades)
        self.strength = nn.Embedding(n_heroes, 1, padding_idx=encode.PAD)
        nn.init.zeros_(self.strength.weight)
        self.register_buffer("coef", _coef_matrix())
        self.first = FirstTerm(n_heroes) if first else None

    def predict(self, heroes, ctx):
        s = self.strength(heroes).squeeze(-1)  # [B, 17]
        out = self.bias(ctx) + s @ self.coef.T
        return (self.first.heads(out, heroes) if self.first is not None else out), None


class FactorizationMachine(nn.Module):
    """B2：B1 + 搭档（同一方两两 ⟨vᵢ, vⱼ⟩）+ 克制（双方两两 ⟨uᵢ, wⱼ⟩ − ⟨uⱼ, wᵢ⟩），对先后手反对称；first 时加先动敏感度。"""
    has_pick = False

    def __init__(self, n_heroes: int, n_rules: int, k: int = 16, grades: bool = True, first: bool = False):
        super().__init__()
        self.bias = ContextBias(n_rules, grades)
        self.strength = nn.Embedding(n_heroes, 1, padding_idx=encode.PAD)
        self.v = nn.Embedding(n_heroes, k, padding_idx=encode.PAD)
        self.u = nn.Embedding(n_heroes, k, padding_idx=encode.PAD)
        self.w = nn.Embedding(n_heroes, k, padding_idx=encode.PAD)
        nn.init.zeros_(self.strength.weight)
        for emb in (self.v, self.u, self.w):
            nn.init.normal_(emb.weight, std=0.01)
            with torch.no_grad():
                emb.weight[encode.PAD].zero_()
        coef = _coef_matrix()
        self.register_buffer("coef", coef)
        self.register_buffer("member_f", (coef[:, :encode.BAN_POS["F"]] > 0).float())  # [12, 15] 先手方的选秀位置
        self.register_buffer("member_s", (coef[:, :encode.BAN_POS["F"]] < 0).float())
        post = torch.zeros(encode.N_STATES, 1)
        post[encode.POSTBAN] = 1.0
        self.register_buffer("post", post, persistent=False)  # [12, 1]，只有后禁之后那一行是 1
        self.first = FirstTerm(n_heroes) if first else None

    def _members(self, heroes):
        """[B, 12, 15]：局面 n 时每个位置的英雄是不是还在这一方（后禁之后去掉被禁的那名）。不用原地修改，导出 ONNX 稳。"""
        picks = heroes[:, :encode.BAN_POS["F"]]
        keep_f = (picks != heroes[:, encode.BAN_POS["F"], None]).float()[:, None, :]  # [B, 1, 15]
        keep_s = (picks != heroes[:, encode.BAN_POS["S"], None]).float()[:, None, :]
        mf = self.member_f * (1 - self.post + self.post * keep_f)
        ms = self.member_s * (1 - self.post + self.post * keep_s)
        return mf, ms

    @staticmethod
    def _pairs(m, e):
        """Σ_{i<j} ⟨eᵢ, eⱼ⟩ = (‖Σe‖² − Σ‖e‖²) / 2，m [B,12,15]、e [B,15,k] → [B,12]。"""
        s = m @ e  # [B, 12, k]
        sq = (m * (e * e).sum(-1).unsqueeze(1)).sum(-1)  # Σ mᵢ‖eᵢ‖²（m 只有 0 / 1）
        return 0.5 * ((s * s).sum(-1) - sq)

    def predict(self, heroes, ctx):
        s = self.strength(heroes).squeeze(-1)
        out = self.bias(ctx) + s @ self.coef.T
        mf, ms = self._members(heroes)
        picks = heroes[:, :encode.BAN_POS["F"]]
        v, u, w = self.v(picks), self.u(picks), self.w(picks)
        out = out + self._pairs(mf, v) - self._pairs(ms, v)
        uf, us, wf, ws = mf @ u, ms @ u, mf @ w, ms @ w
        out = out + (uf * ws).sum(-1) - (us * wf).sum(-1)
        return (self.first.heads(out, heroes) if self.first is not None else out), None


class Attention(nn.Module):
    def __init__(self, d: int, heads: int, dropout: float):
        super().__init__()
        self.heads = heads
        self.qkv = nn.Linear(d, 3 * d)
        self.out = nn.Linear(d, d)
        self.drop = nn.Dropout(dropout)

    def forward(self, x, bias):
        b, t, c = x.shape
        h = self.heads
        q, k, v = self.qkv(x).reshape(b, t, 3, h, c // h).permute(2, 0, 3, 1, 4)
        att = (q @ k.transpose(-2, -1)) * (1.0 / math.sqrt(c // h)) + bias
        att = self.drop(torch.softmax(att, dim=-1))
        y = (att @ v).transpose(1, 2).reshape(b, t, c)
        return self.out(y)


class Block(nn.Module):
    def __init__(self, d: int, heads: int, ffn: int, dropout: float):
        super().__init__()
        self.ln1 = nn.LayerNorm(d)
        self.attn = Attention(d, heads, dropout)
        self.ln2 = nn.LayerNorm(d)
        self.ffn = nn.Sequential(nn.Linear(d, ffn), nn.GELU(), nn.Linear(ffn, d))
        self.drop = nn.Dropout(dropout)

    def forward(self, x, bias):
        x = x + self.drop(self.attn(self.ln1(x), bias))
        return x + self.drop(self.ffn(self.ln2(x)))


class DraftTransformer(nn.Module):
    """胜率头 + 选人头。CTX 位置加上开战规则嵌入（旧结构还有段位）；0–4 互相可见、之后因果；选人头和英雄嵌入共享权重。
    first 时胜率头输出三种「谁先动」（Linear(d → 3)），选人头不变（选秀时还不知道谁先动）。"""
    has_pick = True

    def __init__(self, n_heroes: int, n_rules: int, d: int = 64, layers: int = 2, heads: int = 4, ffn_mult: int = 4,
                 dropout: float = 0.1, grades: bool = True, first: bool = False):
        super().__init__()
        self.grades, self.first_heads = grades, first
        self.hero = nn.Embedding(n_heroes, d)
        self.kind = nn.Embedding(encode.N_TYPES, d)  # 不能叫 type：会和 nn.Module.type() 撞名
        self.pos = nn.Embedding(encode.N_POSITIONS, d)
        if grades:
            self.grade_f = nn.Embedding(encode.N_GRADES, d)
            self.grade_s = nn.Embedding(encode.N_GRADES, d)
        self.rule = nn.Embedding(n_rules, d)
        self.drop = nn.Dropout(dropout)
        self.blocks = nn.ModuleList(Block(d, heads, ffn_mult * d, dropout) for _ in range(layers))
        self.ln = nn.LayerNorm(d)
        self.win = nn.Linear(d, encode.N_HEADS if first else 1)
        self.pick_proj = nn.Linear(d, d)
        self.pick_bias = nn.Parameter(torch.zeros(n_heroes))
        self.register_buffer("types", torch.as_tensor(encode.TOKEN_TYPES))
        self.register_buffer("positions", torch.as_tensor(encode.POSITION_IDS))
        self.register_buffer("attn_bias", torch.where(torch.as_tensor(encode.attention_mask()), 0.0, NEG))
        is_ctx = torch.zeros(encode.SEQ_LEN, 1)
        is_ctx[0] = 1.0
        self.register_buffer("is_ctx", is_ctx)
        self.apply(self._init)

    @staticmethod
    def _init(m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, std=0.02)
            nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, std=0.02)

    def forward(self, heroes: torch.Tensor, ctx: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """→ win_logit [B, 17]（first 时 [B, 17, 3]）、pick_logits [B, 17, V]（每个位置都输出，调用方按 STATE_POS 取）。"""
        c = self.rule(ctx[:, 2])  # [B, d]
        if self.grades:
            c = c + self.grade_f(ctx[:, 0]) + self.grade_s(ctx[:, 1])
        x = self.hero(heroes) + self.kind(self.types) + self.pos(self.positions) + self.is_ctx * c[:, None, :]
        x = self.drop(x)
        for block in self.blocks:
            x = block(x, self.attn_bias)
        h = self.ln(x)
        win = self.win(h)
        if not self.first_heads:
            win = win.squeeze(-1)
        pick = self.pick_proj(h) @ self.hero.weight.T + self.pick_bias
        return win, pick

    def predict(self, heroes, ctx):
        win, pick = self(heroes, ctx)
        return win[:, STATE_POS.to(win.device)], pick[:, PICK_STATE_POS.to(pick.device)]


class HybridTransformer(DraftTransformer):
    """Transformer + 因子分解机（宽 + 深）：胜率 logit = 因子分解机（强度 + 搭档 + 克制）+ Transformer 的修正。

    因子分解机学两两关系很快，Transformer 补上下文（局面、预禁、段位和英雄的组合）；选人头和 DraftTransformer 一样。
    输出格式不变（每个位置的 win_logit / pick_logits），因子分解机的 12 个局面加到各自的读出位置上。
    """

    def __init__(self, n_heroes: int, n_rules: int, k: int = 16, grades: bool = True, first: bool = False, **kw):
        super().__init__(n_heroes, n_rules, grades=grades, first=first, **kw)
        self.fm = FactorizationMachine(n_heroes, n_rules, k, grades=grades, first=first)
        place = torch.zeros(encode.N_STATES, encode.SEQ_LEN)
        place[torch.arange(encode.N_STATES), STATE_POS] = 1.0
        self.register_buffer("place", place, persistent=False)  # [12, 17]：局面 → 读出位置

    def forward(self, heroes: torch.Tensor, ctx: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        win, pick = super().forward(heroes, ctx)
        wide, _ = self.fm.predict(heroes, ctx)
        if self.first_heads:  # wide [B, 12, 3] → 各自的读出位置 [B, 17, 3]
            return win + torch.matmul(self.place.T, wide), pick
        return win + wide @ self.place, pick


MODELS = {"lr0": ContextLR, "lr": HeroLR, "fm": FactorizationMachine, "transformer": DraftTransformer,
          "hybrid": HybridTransformer}
ONNX_MODELS = ("transformer", "hybrid")  # 能导出随包的（输出每个位置的胜率和选人）


def build(kind: str, n_heroes: int, n_rules: int, grades: bool = False, first: bool = True, **kw) -> nn.Module:
    """grades / first 的默认是 B14g 的新结构（不看段位、三种「谁先动」）；读旧 run 时按它的设置传。"""
    if kind not in MODELS:
        raise ValueError(f"不认识的模型 {kind}（{'/'.join(MODELS)}）")
    flags = {"grades": grades, "first": first}
    if kind in ONNX_MODELS:
        args = {k: kw[k] for k in ("d", "layers", "heads", "dropout") if k in kw}
        if kind == "hybrid" and "k" in kw:
            args["k"] = kw["k"]
        return MODELS[kind](n_heroes, n_rules, **args, **flags)
    if kind == "fm":
        return FactorizationMachine(n_heroes, n_rules, **({"k": kw["k"]} if "k" in kw else {}), **flags)
    return MODELS[kind](n_heroes, n_rules, **flags)


# —— 训练和评估共用的张量工具 ——

TARGET_POS = torch.tensor([[p for p, _ in encode.pick_targets(n)] + [encode.PICK_POS + n] * (2 - len(encode.pick_targets(n)))
                           for n in range(encode.N_PICKS)])  # [10, 2]
TARGET_W = torch.tensor([[w for _, w in encode.pick_targets(n)] + [0.0] * (2 - len(encode.pick_targets(n)))
                         for n in range(encode.N_PICKS)])  # [10, 2]


def pick_available(heroes: torch.Tensor, size: int) -> torch.Tensor:
    """[B, 10, V] 布尔：局面 0…9 时下一手能选谁（PAD 不能；被预禁 / 已选的不能；UNK 可以，它代表一类英雄）。"""
    onehot = torch.zeros(heroes.shape[0], encode.SEQ_LEN, size, dtype=torch.bool, device=heroes.device)
    onehot.scatter_(2, heroes.unsqueeze(-1), True)
    onehot[:, 0] = False
    taken = torch.cummax(onehot[:, :encode.PICK_POS + encode.N_PICKS - 1].to(torch.uint8), dim=1).values.bool()
    taken = taken[:, PICK_STATE_POS.to(heroes.device)]  # [B, 10, V]
    taken[..., encode.UNK] = False
    taken[..., encode.PAD] = True
    return ~taken


def pick_targets(heroes: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
    """→ 目标英雄 [B, 10, 2] 和权重 [10, 2]。"""
    return heroes[:, TARGET_POS.to(heroes.device)], TARGET_W.to(heroes.device)


def win_loss_of(win: torch.Tensor, y: torch.Tensor, head: torch.Tensor | None = None) -> torch.Tensor:
    """胜率损失（12 个局面平均）。win [B, 12]：普通 BCE。win [B, 12, 3]（B14g）：每场都算「不知道」头，知道谁先动的
    再算那一方先动的头，所有项一起平均 = Σ(BCE_不知道 + 已知 × BCE_先动) / Σ(1 + 已知)；head 是每场的头编号
    （encode.first_heads，2 = 不知道），None = 全部不知道。"""
    if win.dim() == 2:
        return F.binary_cross_entropy_with_logits(win, y[:, None].expand_as(win))
    yy = y[:, None].expand(-1, win.shape[1])
    lu = F.binary_cross_entropy_with_logits(win[..., encode.HEAD_U], yy, reduction="none").mean(1)  # [B]
    if head is None:
        return lu.mean()
    known = (head < encode.HEAD_U).to(win.dtype)
    idx = head.clamp(max=encode.HEAD_S)[:, None, None].expand(-1, win.shape[1], 1)
    lf = F.binary_cross_entropy_with_logits(win.gather(2, idx).squeeze(-1), yy, reduction="none").mean(1)
    return (lu.sum() + (lf * known).sum()) / (len(lu) + known.sum())


def losses(model: nn.Module, heroes, ctx, y, size: int, head: torch.Tensor | None = None
           ) -> tuple[torch.Tensor, torch.Tensor | None, torch.Tensor, torch.Tensor | None]:
    """→ 胜率损失（`win_loss_of`）、选人交叉熵（10 个局面平均，没有选人头时 None）、两种 logit。"""
    win, pick = model.predict(heroes, ctx)
    win_loss = win_loss_of(win, y, head)
    if pick is None:
        return win_loss, None, win, None
    pick = pick.masked_fill(~pick_available(heroes, size), NEG)
    logp = torch.log_softmax(pick, dim=-1)
    tgt, w = pick_targets(heroes)
    pick_ce = -(logp.gather(2, tgt) * w).sum(-1).mean()
    return win_loss, pick_ce, win, pick
