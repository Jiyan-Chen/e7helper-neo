"""场景与弹窗的定义。

场景（Scene）：一个完整界面，例如大厅、秘密商店。用「必须全部命中」和「不能命中」的模板组合判定。
弹窗（Popup）：盖在场景上的对话框/面板，判定方式同上，另外说明怎么关闭（Dismiss）。

模板引用的写法与 Vision 相同：`title/shop` 在 common 里找；`secret_shop:title` 是限定引用，
到 assets/secret_shop/cn/ 里找（模块注册自己的场景时用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from e7helper.core.geometry import Rect

# 没认出具体弹窗、但画面被遮罩压暗时，报告这个弹窗名，关闭方式是返回键
OBSCURED = "obscured"


class DismissKind(StrEnum):
    TAP = "tap"  # 点击某个模板的命中位置
    POINT = "point"  # 点击固定坐标（基准坐标）
    BACK = "back"  # Android 返回键
    NONE = "none"  # 不能自动关闭，需要任务自己处理


@dataclass(frozen=True)
class Dismiss:
    kind: DismissKind
    target: str | None = None  # TAP：模板引用
    point: tuple[int, int] | None = None  # POINT：基准坐标

    @classmethod
    def tap(cls, ref: str) -> Dismiss:
        return cls(DismissKind.TAP, target=ref)

    @classmethod
    def at(cls, x: int, y: int) -> Dismiss:
        return cls(DismissKind.POINT, point=(x, y))

    @classmethod
    def back(cls) -> Dismiss:
        return cls(DismissKind.BACK)

    @classmethod
    def none(cls) -> Dismiss:
        return cls(DismissKind.NONE)

    def __str__(self) -> str:
        if self.kind is DismissKind.TAP:
            return f"点击 {self.target}"
        if self.kind is DismissKind.POINT:
            return f"点击 {self.point}"
        return {DismissKind.BACK: "返回键", DismissKind.NONE: "不自动关闭"}[self.kind]


def _tuple(v) -> tuple[str, ...]:
    return (v,) if isinstance(v, str) else tuple(v)


@dataclass(frozen=True)
class Scene:
    name: str
    all_of: tuple[str, ...]
    none_of: tuple[str, ...] = ()
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "all_of", _tuple(self.all_of))
        object.__setattr__(self, "none_of", _tuple(self.none_of))
        if not self.all_of:
            raise ValueError(f"场景 {self.name} 至少需要一个 all_of 模板")


@dataclass(frozen=True)
class Popup:
    name: str
    all_of: tuple[str, ...]
    dismiss: Dismiss
    none_of: tuple[str, ...] = ()
    # 可选文字条件：模板都命中后，再 OCR text_region，归一化后包含 text 才算（区分按钮相同的弹窗）
    text: str | None = None
    text_region: Rect | None = None
    # dismiss_popups 是否自动关闭它。False 表示需要任务自己决定（例如要不要重试）
    auto: bool = True
    # 关闭后游戏要重新加载（断线回标题、标题画面进游戏）：dismiss_popups 会等加载结束再继续（B10a）
    reload: bool = False
    note: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "all_of", _tuple(self.all_of))
        object.__setattr__(self, "none_of", _tuple(self.none_of))
        if not self.all_of and self.name != OBSCURED:
            raise ValueError(f"弹窗 {self.name} 至少需要一个 all_of 模板")
        if (self.text is None) != (self.text_region is None):
            raise ValueError(f"弹窗 {self.name}：text 与 text_region 必须同时设置")
        if self.dismiss.kind is DismissKind.NONE and self.auto:
            raise ValueError(f"弹窗 {self.name}：Dismiss.none() 时 auto 必须为 False")


OBSCURED_POPUP = Popup(OBSCURED, (), Dismiss.back(), note="未识别的弹窗（画面被遮罩压暗），用返回键关闭")
