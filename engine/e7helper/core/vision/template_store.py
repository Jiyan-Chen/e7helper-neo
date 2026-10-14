"""模板存储：每个模板是 `<name>.png` + 同名 `.json`（元数据，可省略）。

目录按模块划分：`engine/assets/<module_id>/<lang>/`，name 可以带子目录，如 `shop/refresh`。
模板图片以 1600x900 基准记录；`ref_size` 不是基准时加载会先缩放到基准尺寸。

json 字段（全部可选）：
- ref_size：采集时的屏幕尺寸 [w, h]，默认 [1600, 900]
- region：检索区域 [x, y, w, h]（基准坐标），省略表示全屏
- box：采集时模板在屏幕上的位置 [x, y, w, h]，用于回验和调试
- threshold：匹配阈值，默认 0.85
- grayscale：是否转灰度匹配（颜色不重要、只看形状时用），默认 false
- scales：相对缩放列表（多尺度），默认 [1.0]
- tap：点击区域 [x, y, w, h]（基准坐标，与 box 同一时刻记录），省略表示点模板本身。
  用来识别的元素和真正能点的区域不一致时用：例如大厅「秘密商店」能识别的是文字，可点的是上方图标，
  文字下半部分点了没反应。运行时按命中位置相对 box 的偏移平移（见 Template.tap_area）
- max_diff：颜色校验，命中位置与模板的平均像素差（0-255）上限，默认不校验。
  相关系数对亮度不敏感，按钮被遮罩压暗也能高分命中；需要区分亮/暗、可用/不可用时设置它
- note：备注
其他字段原样保留，模块可以自行使用。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from e7helper.core.geometry import BASE_HEIGHT, BASE_WIDTH, FULL_SCREEN, Rect
from e7helper.core.imageio import read_image, write_image
from e7helper.core.paths import module_assets_dir

DEFAULT_LANG = "cn"
DEFAULT_THRESHOLD = 0.85

_NAME_RE = re.compile(r"^[\w\-]+(/[\w\-]+)*$")


class TemplateNotFound(KeyError):
    pass


class TemplateMeta(BaseModel):
    model_config = ConfigDict(extra="allow")

    ref_size: tuple[int, int] = (BASE_WIDTH, BASE_HEIGHT)
    region: Rect | None = None
    box: Rect | None = None
    tap: Rect | None = None
    threshold: float = Field(DEFAULT_THRESHOLD, ge=0.0, le=1.0)
    grayscale: bool = False
    scales: list[float] = Field(default_factory=lambda: [1.0], min_length=1)
    max_diff: float | None = Field(None, ge=0, le=255)
    note: str = ""

    @field_validator("region", "box", "tap", mode="before")
    @classmethod
    def _parse_rect(cls, v):
        return None if v is None else Rect.parse(v)

    def to_json(self) -> str:
        data = self.model_dump(mode="json")
        # 默认值不写出，json 保持简短；ref_size 总是写出，方便人工查看
        defaults = TemplateMeta().model_dump(mode="json")
        compact = {
            k: v for k, v in data.items() if k == "ref_size" or k not in defaults or defaults[k] != v
        }
        # 每个字段一行，数组不展开，便于人工查看和 diff
        lines = [f"  {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in compact.items()]
        return "{\n" + ",\n".join(lines) + "\n}\n"


@dataclass(eq=False)
class Template:
    """一个模板。image 是基准尺寸下的 BGR 图像。"""

    name: str
    image: np.ndarray
    meta: TemplateMeta = field(default_factory=TemplateMeta)
    path: Path | None = None
    # 按 (缩放系数, 是否灰度) 缓存缩放后的模板图，由 matcher 使用
    _cache: dict[tuple[float, bool], np.ndarray] = field(default_factory=dict, repr=False)

    @property
    def size(self) -> tuple[int, int]:
        return self.image.shape[1], self.image.shape[0]

    @property
    def region(self) -> Rect:
        return self.meta.region or FULL_SCREEN

    @property
    def threshold(self) -> float:
        return self.meta.threshold

    def tap_area(self, hit: Rect) -> Rect:
        """命中位置 hit（基准坐标）对应的点击区域：没设 tap 时就是 hit 本身。"""
        tap, box = self.meta.tap, self.meta.box
        if tap is None:
            return hit
        if box is None:
            return tap
        return Rect(tap.x + hit.x - box.x, tap.y + hit.y - box.y, tap.w, tap.h)

    def scaled(self, factor: float, grayscale: bool) -> np.ndarray:
        key = (round(factor, 4), grayscale)
        img = self._cache.get(key)
        if img is None:
            img = self.image
            if abs(factor - 1.0) > 1e-4:
                w = max(1, round(img.shape[1] * factor))
                h = max(1, round(img.shape[0] * factor))
                interp = cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC
                img = cv2.resize(img, (w, h), interpolation=interp)
            if grayscale:
                img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            self._cache[key] = img
        return img


def _to_base_size(image: np.ndarray, ref_size: tuple[int, int]) -> np.ndarray:
    ref_w, _ = ref_size
    if ref_w == BASE_WIDTH:
        return image
    factor = BASE_WIDTH / ref_w
    w = max(1, round(image.shape[1] * factor))
    h = max(1, round(image.shape[0] * factor))
    return cv2.resize(image, (w, h), interpolation=cv2.INTER_AREA if factor < 1 else cv2.INTER_CUBIC)


def validate_name(name: str) -> str:
    if not _NAME_RE.match(name):
        raise ValueError(f"模板名只能包含字母、数字、下划线、连字符和 /：{name!r}")
    return name


def load_template(png: Path, name: str) -> Template:
    meta_path = png.with_suffix(".json")
    if meta_path.exists():
        meta = TemplateMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
    else:
        meta = TemplateMeta()
    image = _to_base_size(read_image(png), meta.ref_size)
    return Template(name=name, image=image, meta=meta, path=png)


class TemplateStore:
    """一个目录下的模板集合，按需加载并缓存。"""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._cache: dict[str, Template] = {}

    @classmethod
    def for_module(cls, module_id: str, lang: str = DEFAULT_LANG) -> TemplateStore:
        return cls(module_assets_dir(module_id) / lang)

    def __repr__(self) -> str:
        return f"TemplateStore({str(self.root)!r})"

    def _png(self, name: str) -> Path:
        return self.root / f"{validate_name(name)}.png"

    def names(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(p.relative_to(self.root).with_suffix("").as_posix() for p in self.root.rglob("*.png"))

    def __contains__(self, name: str) -> bool:
        return name in self._cache or self._png(name).is_file()

    def get(self, name: str) -> Template:
        tpl = self._cache.get(name)
        if tpl is None:
            png = self._png(name)
            if not png.is_file():
                raise TemplateNotFound(f"模板不存在：{name}（{self.root}）")
            tpl = load_template(png, name)
            self._cache[name] = tpl
        return tpl

    __getitem__ = get

    def load_all(self) -> list[Template]:
        return [self.get(n) for n in self.names()]

    def reload(self) -> None:
        self._cache.clear()

    def save(self, name: str, image: np.ndarray, meta: TemplateMeta | None = None, overwrite: bool = False) -> Template:
        """保存模板（image 应为基准尺寸下截取的 BGR 图像）。"""
        meta = meta or TemplateMeta()
        png = self._png(name)
        if png.exists() and not overwrite:
            raise FileExistsError(f"模板已存在：{png}")
        write_image(png, image)
        png.with_suffix(".json").write_text(meta.to_json(), encoding="utf-8")
        self._cache.pop(name, None)
        return self.get(name)
