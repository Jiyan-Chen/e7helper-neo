"""竞技场 NPC 界面的识别：旗帜读数、准备界面模式、结算、补旗框、自动战斗图标。

全部是纯函数（输入 Vision + 帧），不点击，方便用 fixtures 离线测试。坐标一律是 1600x900 基准（实测 B05）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cv2
import numpy as np

from e7helper.core.geometry import Rect, Scaler
from e7helper.core.vision import Match, Vision

# NPC 列表第一行的名字一带（点这里选中对手；左边的头像和右边的阵容不点）
FIRST_ROW = Rect(500, 255, 220, 50)
# 准备界面：快速对战 / 普通战斗切换钮（白底闪电图标，普通模式时变暗）
MODE_TOGGLE = Rect(1162, 796, 62, 64)
# 准备界面：本日快速对战剩余次数「10/10」（只在快速模式显示）
QUICK_LEFT = Rect(640, 832, 110, 40)

# 补旗框（buy/title 命中时）：左边是友情点数选项，右边是天空石选项，选中的那个有亮边框
BUY_COST = Rect(505, 478, 70, 34)  # 友情点数消耗「100」
BUY_GAIN = Rect(685, 478, 32, 34)  # 换到的旗帜「5」
BUY_HOLD = Rect(540, 510, 170, 34)  # 「持有：193789」
_LEFT_EDGE = Rect(520, 378, 200, 14)  # 左选项上边框（选中时最亮的一行约 235，未选中约 40）
_RIGHT_EDGE = Rect(875, 378, 200, 14)  # 右选项同一位置
SELECTED_BRIGHT = 150

# 顶栏旗帜：图标右侧「当前/上限」
_FLAG_GAP, _FLAG_W = 4, 64


class PrepMode(StrEnum):
    QUICK = "quick"  # 按钮是「快速对战」
    BATTLE = "battle"  # 按钮是「战斗开始」


@dataclass(frozen=True)
class Prep:
    mode: PrepMode
    button: Match  # 「快速对战」或「战斗开始」按钮
    quick_left: int | None  # 本日快速对战剩余次数（只在快速模式读得到）


@dataclass(frozen=True)
class BuyDialog:
    friendship: bool  # 左边选项是友情点数
    left_selected: bool  # 友情点数选项被选中（亮边框）
    right_selected: bool  # 天空石选项被选中
    cost: int | None  # 友情点数消耗
    gain: int | None  # 换到的旗帜数
    hold: int | None  # 持有的友情点数
    ok: Match  # 「购买」按钮
    cancel: Match  # 「取消」按钮

    def __str__(self) -> str:
        sel = "友情点数" if self.left_selected else ("天空石" if self.right_selected else "?")
        return f"{self.cost} 友情点数 → {self.gain} 面旗帜，持有 {self.hold}，选中：{sel}"


def read_flags(vision: Vision, frame: np.ndarray) -> int | None:
    """顶栏旗帜的当前数量（可能超过上限 5，例如补旗后的 8/5）。"""
    m = vision.find(frame, "top/flag")
    if m is None:
        return None
    r = m.rect
    frac = vision.ocr.read_fraction(frame, Rect(r.right + _FLAG_GAP, r.y - 2, _FLAG_W, r.h + 4))
    return None if frac is None else frac[0]


def read_prep(vision: Vision, frame: np.ndarray) -> Prep | None:
    """准备界面当前的模式。按钮模板设了 max_diff，加载/淡入时不命中，返回 None。"""
    quick = vision.find(frame, "prep/quick")
    if quick is not None:
        frac = vision.ocr.read_fraction(frame, QUICK_LEFT)
        return Prep(PrepMode.QUICK, quick, None if frac is None else frac[0])
    start = vision.find(frame, "prep/start")
    if start is not None:
        return Prep(PrepMode.BATTLE, start, None)
    return None


def is_victory(vision: Vision, frame: np.ndarray) -> bool:
    """结算界面是胜利（快速对战是「Victory」，普通战斗是「VICTORY」）。没见过失败界面，认不出就当不是胜利。"""
    return vision.find(frame, "result/victory_quick") is not None or vision.find(frame, "result/victory") is not None


def _edge_bright(frame: np.ndarray, rect: Rect) -> float:
    """边框带里最亮一行的平均灰度。"""
    r = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(rect)
    patch = cv2.cvtColor(r.crop(frame), cv2.COLOR_BGR2GRAY)
    return float(patch.mean(axis=1).max()) if patch.size else 0.0


def read_buy_dialog(vision: Vision, frame: np.ndarray) -> BuyDialog | None:
    """补旗框完全显示时（购买/取消按钮的 max_diff 通过）返回其内容。"""
    if vision.find(frame, "buy/title") is None:
        return None
    ok, cancel = vision.find(frame, "buy/ok"), vision.find(frame, "buy/cancel")
    if ok is None or cancel is None:
        return None
    ocr = vision.ocr
    return BuyDialog(
        friendship=vision.find(frame, "buy/friendship") is not None,
        left_selected=_edge_bright(frame, _LEFT_EDGE) >= SELECTED_BRIGHT,
        right_selected=_edge_bright(frame, _RIGHT_EDGE) >= SELECTED_BRIGHT,
        cost=ocr.read_number(frame, BUY_COST),
        gain=ocr.read_number(frame, BUY_GAIN),
        hold=ocr.read_number(frame, BUY_HOLD),
        ok=ok,
        cancel=cancel,
    )


def auto_icon(vision: Vision, frame: np.ndarray) -> np.ndarray | None:
    """战斗中自动战斗图标所在区域的灰度图（缩放到基准尺寸）；图标没认出时返回 None。

    未开启时图标静止；开启后一直旋转，模板多数帧认不出。是否开启由调用方比较连续几帧判断。
    """
    m = vision.find(frame, "battle/auto")
    if m is None:
        return None
    r = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(m.rect)
    patch = r.crop(frame)
    return cv2.cvtColor(cv2.resize(patch, (m.rect.w, m.rect.h)), cv2.COLOR_BGR2GRAY).astype(np.float32)


def patch_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean()) if a.shape == b.shape else 255.0
