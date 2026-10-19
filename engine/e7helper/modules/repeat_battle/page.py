"""重复刷关界面的识别：顶栏读数、讨伐列表、准备界面、托管战斗（顶栏图标、进度框、设置框）、行动力不足框、
光谱核心购买框（异界，B12a）、战后界面。

全部是纯函数（输入 Vision + 帧），不点击，方便用 fixtures 离线测试。坐标一律是 1600x900 基准（实测 B06）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import re

import cv2
import numpy as np

from e7helper.core.geometry import Rect, Scaler
from e7helper.core.vision import Match, Vision, normalize_text

from .config import Hunt, Tier

# ---------------------------------------------------------------- 讨伐列表 / 准备界面

HUNT_LIST = Rect(1285, 160, 300, 740)  # 右侧「可进入的地下城」卡片列表（可上下滑动）
HUNT_SWIPE = ((1428, 760), (1428, 300))  # 向上滑动列表（看下面的地下城）
_HUNT_NAME_MIN_H = 26
# 中间的难度卡片：随选中的地下城变化（大多有 中级~异界 四张，食人魔只有「讨伐异界」，B12a 实测）
TIER_LIST = Rect(955, 170, 300, 700)
PREP_HUNT = Rect(1155, 92, 330, 42)  # 准备界面右上「讨伐双足飞龙」
PREP_TIER = Rect(1155, 142, 300, 42)  # 「讨伐地狱级」
MODE_TOGGLE = Rect(1520, 796, 60, 64)  # 右下角 快速战斗 / 普通战斗 切换钮（异界没有快速战斗，也没有这个钮）
_PREP_COST_DX, _PREP_COST_W = -145, 115  # 开始按钮左边「消耗/持有」，相对按钮文字模板

# ---------------------------------------------------------------- 顶栏

_NUM_GAP, _NUM_H = 4, 44
_ENERGY_W, _SKYSTONE_W = 110, 110
_CORE_W = 52  # 光谱核心数字右边紧挨着行动力图标

# 托管时钟图标：完成后左上角有静止的红点；进行中是外圈一段橙色光弧在转。红点区域相对表盘模板命中框。
# 从「重新进行」回到准备界面时，顶栏部分图标（托管、背包、邮件、菜单）变灰，亮度约为平时的 0.38，
# 所以按表盘最亮值归一化后再判红色。单帧时光弧扫过红点位置也能到 0.56，要靠多帧红点位置不变区分（实测 B06）。
_DOT = (-22, -18, 16, 16)
DOT_RATIO = 0.45  # 完成：0.59~0.60（变灰时也一样）

# ---------------------------------------------------------------- 托管战斗

CLOSE_POINT = (800, 878)  # 托管框底部「轻触后关闭 / 点击关闭」的下半部分：离「中断」按钮下沿 60 像素；
# 框关闭后同一位置在准备界面是空白（「推荐配置」按钮下沿约 862），万一框已关闭也点不到按钮
SETTLED_CLOSE = (800, 658)  # 「结算完毕」框的「点击关闭」
AUTO_PROGRESS = Rect(835, 300, 80, 36)  # 进度框「战斗进度：4/4」的数字
AUTO_STAGE = Rect(700, 142, 200, 40)  # 进度框「讨伐地狱级」
# 设置框
# 右上「行动力（异界：光谱核心）图标 数字 叶子图标 数字」，整组右对齐，数字位数变了位置就变（B12a：行动力 110 时
# 按固定区域读成了 10），所以整行识别，取最后两个数字
SETUP_HEADER = Rect(1030, 66, 230, 50)
SETUP_RUN_ENERGY = Rect(1038, 316, 50, 34)  # 1 次消耗行动力（异界：光谱核心）
SETUP_RUN_LEAF = Rect(1150, 316, 85, 34)  # 1 次消耗生命之叶：普通难度「0.25」，异界「2」
SETUP_CHECK = Rect(697, 383, 38, 38)  # 「优先使用持有的行动力」勾选框
SETUP_CHECK_LABEL = Rect(745, 388, 225, 28)
SETUP_COUNT = Rect(900, 515, 140, 45)  # 「1/100」：预计使用生命之叶（普通难度每片打 4 次；异界每次 2 片，+1 加一次）
SETUP_MIN = Rect(695, 517, 62, 40)  # 「最少」
SETUP_MINUS = Rect(768, 517, 60, 40)  # 「-1」
SETUP_PLUS = Rect(1095, 517, 60, 40)  # 「+1」
SETUP_USE_ENERGY = Rect(880, 622, 70, 40)  # 下方「将使用」行动力
SETUP_USE_LEAF = Rect(1025, 622, 60, 40)  # 下方「将使用」生命之叶
SETUP_ESTIMATE = Rect(770, 680, 400, 30)  # 「预计完成：约4次·预计时长：约0小时7分钟」
RUNS_PER_UNIT = 4  # 普通难度每份（1 片叶子）打 4 次
OW_LEAVES_PER_RUN = 2  # 异界每次 2 片叶子（或 1 个光谱核心），份数框按叶子数显示、每点一次 +1 加 2（B12a 实测）
_CHECK_GREEN = 0.1  # 勾选后绿色对勾占勾选框约 20%
_LABEL_ENABLED = 130  # 可勾选时标签文字是白的（98 分位灰度 186），不可勾选时变灰（71）

# ---------------------------------------------------------------- 行动力不足框

LEFT_OPTION = Rect(480, 386, 284, 158)  # 生命之叶选项
RIGHT_OPTION = Rect(836, 386, 284, 158)  # 天空石选项
_LEFT_EDGE = Rect(490, 380, 270, 14)  # 选中的选项上边框是亮黄色（最亮一行约 233，未选中约 42）
_RIGHT_EDGE = Rect(840, 380, 270, 14)
SELECTED_BRIGHT = 150
_LEAF_COST, _LEAF_GAIN, _LEAF_HOLD = Rect(520, 478, 40, 32), Rect(672, 478, 56, 32), Rect(565, 511, 115, 32)
_SKY_COST, _SKY_GAIN, _SKY_HOLD = Rect(872, 478, 52, 32), Rect(1030, 478, 56, 32), Rect(912, 511, 140, 32)

# ---------------------------------------------------------------- 光谱核心购买框（点顶栏核心图标打开，B12a）

CORE_LEFT_OPTION = Rect(478, 298, 288, 164)  # 生命之叶 2 → 1
CORE_RIGHT_OPTION = Rect(835, 298, 288, 164)  # 天空石 80 → 1
_CORE_LEFT_EDGE = Rect(490, 292, 270, 14)  # 选中的选项上边框是亮黄色（最亮一行约 199，未选中约 16）
_CORE_RIGHT_EDGE = Rect(845, 292, 265, 14)
_CORE_LEAF_COST, _CORE_LEAF_GAIN = Rect(515, 392, 45, 34), Rect(680, 392, 45, 34)
_CORE_SKY_COST, _CORE_SKY_GAIN = Rect(870, 392, 55, 34), Rect(1038, 392, 45, 34)
_CORE_LEAF_HOLD, _CORE_SKY_HOLD = Rect(555, 425, 130, 34), Rect(905, 425, 150, 34)
CORE_QTY = Rect(750, 510, 100, 62)  # 「1/3」：这次买几个 / 最多能买几个

# ---------------------------------------------------------------- 战后

_AFTER_COST_DX, _AFTER_COST_W = -120, 95  # 「重新进行」左边「消耗/持有」
CLEAR_TAP = Rect(600, 520, 400, 200)  # CLEAR 画面点空白处继续


class PrepMode(StrEnum):
    QUICK = "quick"  # 按钮是「快速战斗」（扫荡，本模块不用）
    BATTLE = "battle"  # 按钮是「战斗开始」


class AutoState(StrEnum):
    NONE = "none"  # 顶栏没有托管图标：没有托管（或已结算）
    RUNNING = "running"
    DONE = "done"  # 已完成，等待结算


@dataclass(frozen=True)
class Prep:
    mode: PrepMode
    button: Match  # 「战斗开始」或「快速战斗」
    cost: int | None  # 一次消耗的行动力（快速模式是 次数×单次）
    held: int | None  # 按钮上显示的持有行动力
    no_record: bool  # 「无记录」：没有通关记录，开不了托管

    @property
    def enough(self) -> bool:
        return self.cost is not None and self.held is not None and self.held >= self.cost


@dataclass(frozen=True)
class AutoProgress:
    state: AutoState  # RUNNING（按钮是「中断」）/ DONE（「结算」）/ NONE（已结算，按钮是「关闭」）
    done: int | None
    total: int | None
    button: Match | None  # 「结算」或「关闭」；进行中是 None（「中断」绝不能点）
    stage: str


@dataclass(frozen=True)
class AutoSetup:
    energy: int | None  # 持有行动力（异界：光谱核心）
    leaves: int | None  # 持有生命之叶
    run_energy: int | None  # 1 次消耗行动力（异界：光谱核心）
    run_leaves: float | None  # 1 次消耗生命之叶（普通 0.25，异界 2）
    count: int | None  # 份数框：预计使用生命之叶（普通难度每片打 4 次，异界每次 2 片）
    count_max: int | None
    use_energy: int | None  # 将使用的行动力（异界：光谱核心）
    use_leaves: int | None  # 将使用的生命之叶
    checked: bool  # 已勾选「优先使用持有的行动力」
    check_enabled: bool  # 可以勾选（行动力不够一份时不可勾选）
    estimate: str
    start: Match

    def __str__(self) -> str:
        return (f"持有 {self.energy}、叶子 {self.leaves}；1 次 {self.run_energy} 或 {self.run_leaves} 片叶子；份数 "
                f"{self.count}/{self.count_max}；将使用 {self.use_energy}、叶子 {self.use_leaves}；"
                f"优先使用持有的 {'开' if self.checked else '关'}{'' if self.check_enabled else '（不可选）'}；{self.estimate}")


@dataclass(frozen=True)
class EnergyDialog:
    leaf: bool  # 左边是生命之叶选项
    skystone: bool  # 右边是天空石选项
    left_selected: bool
    right_selected: bool
    leaf_cost: int | None
    leaf_gain: int | None
    leaf_hold: int | None
    sky_cost: int | None
    sky_gain: int | None
    sky_hold: int | None
    buy: Match
    cancel: Match

    def __str__(self) -> str:
        sel = "叶子" if self.left_selected else ("天空石" if self.right_selected else "?")
        return (f"叶子 {self.leaf_cost} → {self.leaf_gain}（持有 {self.leaf_hold}），天空石 {self.sky_cost} → "
                f"{self.sky_gain}（持有 {self.sky_hold}），选中：{sel}")


@dataclass(frozen=True)
class CoreDialog(EnergyDialog):
    """「购买光谱核心」框：选项和行动力不足框一样（左叶子 / 右天空石），多一个购买数量。"""

    qty: int | None  # 这次买几个（打开时是 1）
    qty_max: int | None  # 最多能买几个

    def __str__(self) -> str:
        return f"{super().__str__()}，数量 {self.qty}/{self.qty_max}"


# ---------------------------------------------------------------- 顶栏


def _num_right_of(vision: Vision, frame: np.ndarray, ref: str, width: int, fraction: bool) -> int | None:
    m = vision.find(frame, ref)
    if m is None:
        return None
    r = m.rect
    region = Rect(r.right + _NUM_GAP, r.y + r.h // 2 - _NUM_H // 2, width, _NUM_H)
    if fraction:
        frac = vision.ocr.read_fraction(frame, region)
        return None if frac is None else frac[0]
    return vision.ocr.read_number(frame, region)


def read_energy(vision: Vision, frame: np.ndarray) -> int | None:
    """顶栏行动力「当前/上限」的当前值（可能超过上限）。顶栏布局随界面变化，先定位图标。"""
    return _num_right_of(vision, frame, "top/energy", _ENERGY_W, True)


def read_skystone(vision: Vision, frame: np.ndarray) -> int | None:
    return _num_right_of(vision, frame, "top/skystone", _SKYSTONE_W, False)


def read_core(vision: Vision, frame: np.ndarray) -> int | None:
    """顶栏光谱核心（异界代币）持有数。只在讨伐列表、准备界面等显示，大厅没有。"""
    return _num_right_of(vision, frame, "top/core", _CORE_W, False)


def auto_dot(vision: Vision, frame: np.ndarray) -> np.ndarray | None:
    """顶栏托管图标红点位置的红色掩码（基准尺寸 16x16 的 bool 数组）；没有托管图标返回 None。"""
    m = vision.find(frame, "top/auto_clock")
    if m is None:
        return None
    s = Scaler(frame.shape[1], frame.shape[0])
    dx, dy, w, h = _DOT
    patch = s.rect_to_device(Rect(m.rect.x + dx, max(0, m.rect.y + dy), w, h)).crop(frame)
    face = s.rect_to_device(m.rect).crop(frame)
    if patch.size == 0 or face.size == 0:
        return np.zeros((h, w), bool)
    patch = cv2.resize(patch, (w, h), interpolation=cv2.INTER_AREA).astype(np.int16)
    ref = float(face.max())  # 表盘的白色：平时 255，变灰时约 98
    b, g, r = patch[..., 0], patch[..., 1], patch[..., 2]
    return (r > 0.5 * ref) & (r > 1.5 * g) & (r > 2 * b)


def auto_state(vision: Vision, frame: np.ndarray) -> AutoState:
    """单帧判断顶栏托管图标：没有图标 NONE；红点位置够红是 DONE 候选，否则 RUNNING。

    光弧扫过红点位置时单帧也会是 DONE，调用方要隔 0.5 秒以上连看几帧，红点位置不变才算完成（见 dots_match）。
    """
    dot = auto_dot(vision, frame)
    if dot is None:
        return AutoState.NONE
    return AutoState.DONE if float(dot.mean()) >= DOT_RATIO else AutoState.RUNNING


def dots_match(a: np.ndarray, b: np.ndarray, min_iou: float = 0.8) -> bool:
    """两帧的红点掩码重合（IoU）：完成时红点静止 ≥0.89；进行中光弧在转，隔 1 秒从没有两帧同时够红（实测 B06）。"""
    union = (a | b).sum()
    return union > 0 and (a & b).sum() / union >= min_iou


# ---------------------------------------------------------------- 讨伐列表 / 准备界面


def find_hunt(vision: Vision, frame: np.ndarray, hunt: Hunt) -> Rect | None:
    """在讨伐列表里找目标地下城的名字（OCR，约 0.4 秒），返回名字的位置；不在当前可见范围返回 None。"""
    want = normalize_text(f"讨伐{hunt.value}")
    for r in vision.ocr.read(frame, HUNT_LIST):
        # 名字被屏幕底边截掉一半时也能认出来（高约 18，完整约 35），但点不准，当作不在可见范围（B12a）
        if normalize_text(r.text) == want and r.rect.h >= _HUNT_NAME_MIN_H:
            return r.rect
    return None


def find_tier(vision: Vision, frame: np.ndarray, tier: Tier) -> Rect | None:
    """在中间的难度卡片里找「讨伐<难度>」（OCR）；这个地下城没有该难度时返回 None。

    要求整行相等：卡片说明里也有「可在讨伐异界中获得」。
    """
    want = normalize_text(f"讨伐{tier.value}")
    for r in vision.ocr.read(frame, TIER_LIST):
        if normalize_text(r.text) == want:
            return r.rect
    return None


def read_prep(vision: Vision, frame: np.ndarray) -> Prep | None:
    """准备界面当前的模式和行动力。按钮模板设了 max_diff，淡入时不命中，返回 None。"""
    button = vision.find(frame, "prep/start")
    mode = PrepMode.BATTLE
    if button is None:
        button = vision.find(frame, "prep/quick")
        mode = PrepMode.QUICK
    if button is None:
        return None
    r = button.rect
    frac = vision.ocr.read_fraction(frame, Rect(r.x + _PREP_COST_DX, r.y - 2, _PREP_COST_W, r.h + 4))
    return Prep(mode, button, None if frac is None else frac[0], None if frac is None else frac[1],
                vision.find(frame, "prep/norecord") is not None)


def read_stage(vision: Vision, frame: np.ndarray) -> tuple[str, str]:
    """准备界面右上的关卡名和难度（例如「讨伐双足飞龙」「讨伐地狱级」），已归一化。"""
    ocr = vision.ocr
    return normalize_text(ocr.read_line(frame, PREP_HUNT).text), normalize_text(ocr.read_line(frame, PREP_TIER).text)


# ---------------------------------------------------------------- 托管战斗


def read_auto_progress(vision: Vision, frame: np.ndarray) -> AutoProgress | None:
    """托管进度框（标题居中「托管战斗」）。按钮认不出（淡入中、「结算中」）时返回 None。"""
    if vision.find(frame, "auto/title") is None:
        return None
    if vision.find(frame, "auto/abort") is not None:
        state, button = AutoState.RUNNING, None
    elif (settle := vision.find(frame, "auto/settle")) is not None:
        state, button = AutoState.DONE, settle
    elif (close := vision.find(frame, "auto/close")) is not None:
        state, button = AutoState.NONE, close
    else:
        return None
    frac = vision.ocr.read_fraction(frame, AUTO_PROGRESS)
    stage = normalize_text(vision.ocr.read_line(frame, AUTO_STAGE).text)
    return AutoProgress(state, None if frac is None else frac[0], None if frac is None else frac[1], button, stage)


def _green_ratio(frame: np.ndarray, rect: Rect) -> float:
    p = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(rect).crop(frame).astype(np.int16)
    b, g, r = p[..., 0], p[..., 1], p[..., 2]
    return float(((g > 150) & (g > r + 40) & (g > b + 40)).mean()) if p.size else 0.0


def _bright_p98(frame: np.ndarray, rect: Rect) -> float:
    patch = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(rect).crop(frame)
    return float(np.percentile(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), 98)) if patch.size else 0.0


def read_auto_setup(vision: Vision, frame: np.ndarray) -> AutoSetup | None:
    """托管设置框（「托管战斗设置」页签）。「开始」按钮的 max_diff 不通过（淡入中、被确认框压暗）时返回 None。"""
    if vision.find(frame, "auto/setup_title") is None or vision.find(frame, "auto/tab_setup") is None:
        return None
    start = vision.find(frame, "auto/start")
    if start is None:
        return None
    ocr = vision.ocr
    frac = ocr.read_fraction(frame, SETUP_COUNT)
    nums = [int(t) for r in ocr.read(frame, SETUP_HEADER) if (t := r.text.replace(",", "")).isdigit()]
    return AutoSetup(
        energy=nums[-2] if len(nums) >= 2 else None,
        leaves=nums[-1] if len(nums) >= 2 else None,
        run_energy=ocr.read_number(frame, SETUP_RUN_ENERGY),
        run_leaves=_parse_float(ocr.read_line(frame, SETUP_RUN_LEAF).text),
        count=None if frac is None else frac[0],
        count_max=None if frac is None else frac[1],
        use_energy=ocr.read_number(frame, SETUP_USE_ENERGY),
        use_leaves=ocr.read_number(frame, SETUP_USE_LEAF),
        checked=_green_ratio(frame, SETUP_CHECK) >= _CHECK_GREEN,
        check_enabled=_bright_p98(frame, SETUP_CHECK_LABEL) >= _LABEL_ENABLED,
        estimate=normalize_text(ocr.read_line(frame, SETUP_ESTIMATE).text),
        start=start,
    )


def _parse_float(text: str) -> float | None:
    m = re.search(r"\d+(?:\.\d+)?", text)
    return float(m.group()) if m else None


def plan_auto(energy: int, run_energy: int, max_leaves: int, prefer_energy: bool,
              max_units: int = 0, *, runs_per_unit: int = RUNS_PER_UNIT,
              leaves_per_unit: int = 1) -> tuple[int, int, int]:
    """托管份数框要设的值，以及预计使用的行动力（异界：光谱核心）和叶子：(份数框的值, 行动力, 叶子)。

    份数框显示的是叶子数，一「份」是点一次 +1 加的量：普通难度 1 片叶子 = 4 次（runs_per_unit=4,
    leaves_per_unit=1），异界 2 片叶子 = 1 次（runs_per_unit=1, leaves_per_unit=2）。勾选「优先使用持有的…」时
    先用行动力 / 核心凑整份，剩下的用叶子（最多 max_leaves 片）。max_units > 0 时份数不超过它（先少用叶子）。
    份数框最多 100。
    """
    unit = run_energy * runs_per_unit
    energy_units = energy // unit if prefer_energy and unit > 0 else 0
    units = min(100 // leaves_per_unit, energy_units + max_leaves // leaves_per_unit, max_units or 100)
    use_energy_units = min(units, energy_units)
    return units * leaves_per_unit, use_energy_units * unit, (units - use_energy_units) * leaves_per_unit


# ---------------------------------------------------------------- 行动力不足框


def _edge_bright(frame: np.ndarray, rect: Rect) -> float:
    r = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(rect)
    patch = cv2.cvtColor(r.crop(frame), cv2.COLOR_BGR2GRAY)
    return float(patch.mean(axis=1).max()) if patch.size else 0.0


def read_energy_dialog(vision: Vision, frame: np.ndarray) -> EnergyDialog | None:
    """「行动力不足」框完全显示时（购买/取消按钮的 max_diff 通过）返回其内容。"""
    if vision.find(frame, "energy/title") is None:
        return None
    buy, cancel = vision.find(frame, "energy/buy"), vision.find(frame, "energy/cancel")
    if buy is None or cancel is None:
        return None
    ocr = vision.ocr
    return EnergyDialog(
        leaf=vision.find(frame, "energy/leaf") is not None,
        skystone=vision.find(frame, "energy/skystone") is not None,
        left_selected=_edge_bright(frame, _LEFT_EDGE) >= SELECTED_BRIGHT,
        right_selected=_edge_bright(frame, _RIGHT_EDGE) >= SELECTED_BRIGHT,
        leaf_cost=ocr.read_number(frame, _LEAF_COST),
        leaf_gain=ocr.read_number(frame, _LEAF_GAIN),
        leaf_hold=ocr.read_number(frame, _LEAF_HOLD),
        sky_cost=ocr.read_number(frame, _SKY_COST),
        sky_gain=ocr.read_number(frame, _SKY_GAIN),
        sky_hold=ocr.read_number(frame, _SKY_HOLD),
        buy=buy,
        cancel=cancel,
    )


def read_core_dialog(vision: Vision, frame: np.ndarray) -> CoreDialog | None:
    """「购买光谱核心」框完全显示时（购买 / 取消按钮的 max_diff 通过）返回其内容。"""
    if vision.find(frame, "core/title") is None:
        return None
    buy, cancel = vision.find(frame, "core/buy"), vision.find(frame, "core/cancel")
    if buy is None or cancel is None:
        return None
    ocr = vision.ocr
    qty = ocr.read_fraction(frame, CORE_QTY)
    return CoreDialog(
        leaf=vision.find(frame, "core/leaf") is not None,
        skystone=vision.find(frame, "core/skystone") is not None,
        left_selected=_edge_bright(frame, _CORE_LEFT_EDGE) >= SELECTED_BRIGHT,
        right_selected=_edge_bright(frame, _CORE_RIGHT_EDGE) >= SELECTED_BRIGHT,
        leaf_cost=ocr.read_number(frame, _CORE_LEAF_COST),
        leaf_gain=ocr.read_number(frame, _CORE_LEAF_GAIN),
        leaf_hold=ocr.read_number(frame, _CORE_LEAF_HOLD),
        sky_cost=ocr.read_number(frame, _CORE_SKY_COST),
        sky_gain=ocr.read_number(frame, _CORE_SKY_GAIN),
        sky_hold=ocr.read_number(frame, _CORE_SKY_HOLD),
        buy=buy,
        cancel=cancel,
        qty=None if qty is None else qty[0],
        qty_max=None if qty is None else qty[1],
    )


# ---------------------------------------------------------------- 战斗 / 战后


def read_after_energy(vision: Vision, frame: np.ndarray) -> tuple[int, int] | None:
    """战后界面「重新进行」左边的「消耗/持有」。"""
    m = vision.find(frame, "after/retry")
    if m is None:
        return None
    r = m.rect
    return vision.ocr.read_fraction(frame, Rect(r.x + _AFTER_COST_DX, r.y - 2, _AFTER_COST_W, r.h + 4))


def auto_icon(vision: Vision, frame: np.ndarray) -> np.ndarray | None:
    """战斗中自动战斗图标区域的灰度图；图标没认出时返回 None（开启后一直旋转，是否开启由调用方比较连续几帧）。"""
    m = vision.find(frame, "battle/auto")
    if m is None:
        return None
    r = Scaler(frame.shape[1], frame.shape[0]).rect_to_device(m.rect)
    patch = r.crop(frame)
    return cv2.cvtColor(cv2.resize(patch, (m.rect.w, m.rect.h)), cv2.COLOR_BGR2GRAY).astype(np.float32)


def patch_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.abs(a - b).mean()) if a.shape == b.shape else 255.0
