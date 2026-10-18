"""模板采集接口（B09，开发工具，GUI 的「模板采集」页用）。前缀 `/api/capture`，同样要 token。

和 CLI `capture` / `match` / `ocr` 做的事一样，只是改成在 GUI 里框选：
1. `POST /frames` 冻结当前画面（只读截图，缩放到 1600×900 基准），或 `POST /frames/upload` 上传一张图（fixtures）；
2. `POST /templates/{module}` 按矩形保存模板（png + json，写进 engine/assets），并回验：原位置分数 + 其他位置最高分；
3. `POST /match` 在冻结的帧上测试模板，`POST /ocr` 测试 OCR。

冻结的帧只在内存里保留最近 FRAME_LIMIT 张。模板写进源码目录，所以只适合开发环境（GUI 只在开发版显示这一页）。
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from typing import Literal

import cv2
import numpy as np
from fastapi import APIRouter, Body, Response
from pydantic import BaseModel, Field, field_validator

from e7helper.core import paths
from e7helper.core.geometry import BASE_HEIGHT, BASE_WIDTH, Rect
from e7helper.core.vision import TemplateMeta, TemplateStore, Vision, best_match, find_all
from e7helper.core.vision.template_store import TemplateNotFound, validate_name

from .engine import ApiError, Engine

FRAME_LIMIT = 8
RectList = tuple[int, int, int, int]


def to_base(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    if (w, h) == (BASE_WIDTH, BASE_HEIGHT):
        return frame
    return cv2.resize(frame, (BASE_WIDTH, BASE_HEIGHT), interpolation=cv2.INTER_AREA)


class FrameCache:
    """最近冻结的几张帧（基准尺寸）。"""

    def __init__(self, limit: int = FRAME_LIMIT):
        self.limit = limit
        self._frames: OrderedDict[str, np.ndarray] = OrderedDict()
        self._lock = threading.Lock()

    def put(self, frame: np.ndarray) -> str:
        fid = uuid.uuid4().hex[:10]
        with self._lock:
            self._frames[fid] = to_base(frame)
            while len(self._frames) > self.limit:
                self._frames.popitem(last=False)
        return fid

    def get(self, fid: str) -> np.ndarray:
        with self._lock:
            frame = self._frames.get(fid)
        if frame is None:
            raise ApiError(404, "unknown_frame", "这张画面已经过期，请重新截图")
        return frame


def _rect(v: RectList | None, what: str) -> Rect | None:
    if v is None:
        return None
    r = Rect(*v).clip()
    if r.area == 0:
        raise ApiError(422, "bad_rect", f"{what}在画面外或为空")
    return r


def _module_store(module_id: str) -> TemplateStore:
    if not module_id or "/" in module_id or "\\" in module_id or module_id.startswith("."):
        raise ApiError(400, "bad_module", f"不合法的模块 id：{module_id}")
    return TemplateStore.for_module(module_id)


def _match_dict(m, tpl) -> dict:
    max_diff = tpl.meta.max_diff
    ok = m.score >= tpl.threshold and (max_diff is None or m.diff <= max_diff)
    return {"name": tpl.name, "score": round(m.score, 4), "diff": round(m.diff, 1), "rect": list(m.rect),
            "threshold": tpl.threshold, "max_diff": max_diff, "hit": ok}


class SaveBody(BaseModel):
    frame: str
    name: str
    box: RectList = Field(description="模板区域 x,y,w,h（基准坐标）")
    region: RectList | None = Field(None, description="检索区域；不给且 full=false 时按 margin 外扩模板区域")
    full: bool = Field(False, description="全屏检索（位置不固定的元素）")
    margin: int = Field(40, ge=0, le=800)
    tap: RectList | None = Field(None, description="点击区域（可点区域和识别区域不一致时）")
    threshold: float = Field(0.85, ge=0.0, le=1.0)
    grayscale: bool = False
    max_diff: float | None = Field(None, ge=0, le=255)
    note: str = ""
    overwrite: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return validate_name(v)


class MatchBody(BaseModel):
    frame: str
    module: str
    names: list[str] | None = Field(None, description="不给就测试这个模块的全部模板")
    region: RectList | None = None


class OcrBody(BaseModel):
    frame: str
    rect: RectList | None = None
    mode: Literal["read", "line", "number"] = "read"


def build_capture_router(engine: Engine) -> APIRouter:
    r = APIRouter(prefix="/capture", tags=["模板采集（开发）"])
    frames = FrameCache()

    def _reload_runtime_templates() -> None:
        """保存 / 删除模板后清掉运行时识别器的模板缓存。"""
        rt = engine.runtime
        if rt is None:
            return
        vision = rt.scenes.vision
        for store in [*vision.stores, *getattr(vision, "_qualified", {}).values()]:
            store.reload()

    @r.post("/frames", summary="冻结当前画面（只读截图）")
    def freeze() -> dict:
        fid = frames.put(engine.screenshot())
        return {"id": fid, "width": BASE_WIDTH, "height": BASE_HEIGHT, "time": time.time()}

    @r.post("/frames/upload", summary="上传一张图片作为画面（例如 tests/fixtures 里的截图）")
    def upload(body: bytes = Body(..., media_type="application/octet-stream")) -> dict:
        img = cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ApiError(422, "bad_image", "图片解码失败")
        fid = frames.put(img)
        return {"id": fid, "width": BASE_WIDTH, "height": BASE_HEIGHT, "time": time.time()}

    @r.get("/frames/{fid}", summary="冻结的画面（PNG）", response_class=Response)
    def frame_png(fid: str) -> Response:
        ok, buf = cv2.imencode(".png", frames.get(fid))
        return Response(buf.tobytes(), media_type="image/png")

    @r.get("/stores", summary="有模板目录的模块（common 是跨模块共用的）")
    def stores() -> list[dict]:
        out = []
        for d in sorted(p for p in paths.ASSETS_DIR.iterdir() if p.is_dir()):
            store = TemplateStore.for_module(d.name)
            out.append({"module": d.name, "count": len(store.names())})
        known = {o["module"] for o in out}
        out += [{"module": mid, "count": 0} for mid in engine.modules if mid not in known]
        return out

    @r.get("/templates", summary="一个模块的全部模板和元数据")
    def templates(module: str) -> list[dict]:
        store = _module_store(module)
        out = []
        for name in store.names():
            try:
                tpl = store.get(name)
            except Exception as e:  # noqa: BLE001 —— 坏文件也列出来
                out.append({"name": name, "error": str(e)})
                continue
            out.append({"name": name, "size": list(tpl.size), "meta": tpl.meta.model_dump(mode="json")})
        return out

    @r.get("/templates/{module}/image/{name:path}", summary="模板图片（PNG）", response_class=Response)
    def template_png(module: str, name: str) -> Response:
        store = _module_store(module)
        try:
            tpl = store.get(name)
        except (TemplateNotFound, ValueError) as e:
            raise ApiError(404, "unknown_template", str(e)) from e
        ok, buf = cv2.imencode(".png", tpl.image)
        return Response(buf.tobytes(), media_type="image/png")

    @r.post("/templates/{module}", summary="按矩形保存模板并回验")
    def save(module: str, body: SaveBody) -> dict:
        store = _module_store(module)
        frame = frames.get(body.frame)
        box = _rect(body.box, "模板区域")
        region = None if body.full else (_rect(body.region, "检索区域") or box.expand(body.margin).clip())
        if region is not None and not region.contains(box):
            raise ApiError(422, "bad_region", "检索区域没有包含模板区域")
        meta = TemplateMeta(region=region, box=box, tap=_rect(body.tap, "点击区域"), threshold=body.threshold,
                            grayscale=body.grayscale, max_diff=body.max_diff, note=body.note)
        try:
            tpl = store.save(body.name, box.crop(frame).copy(), meta, overwrite=body.overwrite)
        except FileExistsError as e:
            raise ApiError(409, "exists", f"模板已存在：{body.name}（勾选覆盖后再保存）") from e
        _reload_runtime_templates()
        # 回验：原位置分数 + 检索区域内其他位置的最高分（越低说明区分度越好）
        own = best_match(frame, tpl, region=box.expand(4).clip())
        others = [h for h in find_all(frame, tpl, threshold=-1.0, max_count=5) if h.rect.iou(box) < 0.5]
        return {
            "name": tpl.name,
            "path": str(tpl.path),
            "size": list(tpl.size),
            "meta": tpl.meta.model_dump(mode="json"),
            "verify": {
                "own": _match_dict(own, tpl) if own else None,
                "other": _match_dict(others[0], tpl) if others else None,
            },
        }

    @r.delete("/templates/{module}/{name:path}", status_code=204, response_class=Response, summary="删除模板")
    def delete(module: str, name: str) -> Response:
        store = _module_store(module)
        png = store.root / f"{validate_name(name)}.png"
        if not png.is_file():
            raise ApiError(404, "unknown_template", f"模板不存在：{name}")
        png.unlink()
        png.with_suffix(".json").unlink(missing_ok=True)
        store.reload()
        _reload_runtime_templates()
        return Response(status_code=204)

    @r.post("/match", summary="在冻结的画面上测试模板（不设阈值的最佳位置）")
    def match(body: MatchBody) -> list[dict]:
        frame = frames.get(body.frame)
        vision = Vision.for_module(body.module)
        names = body.names or vision.stores[0].names()
        region = _rect(body.region, "检索区域")
        out = []
        for name in names:
            try:
                tpl = vision.template(name)
            except (TemplateNotFound, ValueError) as e:
                out.append({"name": name, "error": str(e)})
                continue
            t0 = time.perf_counter()
            m = best_match(frame, tpl, region)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            if m is None:
                out.append({"name": name, "error": "模板比检索区域还大", "ms": ms})
            else:
                out.append({**_match_dict(m, tpl), "ms": ms})
        return out

    @r.post("/ocr", summary="在冻结的画面上测试 OCR（第一次要加载模型，几秒）")
    def ocr(body: OcrBody) -> dict:
        frame = frames.get(body.frame)
        rect = _rect(body.rect, "识别区域")
        o = Vision.for_module("common").ocr
        t0 = time.perf_counter()
        if body.mode == "read":
            results = [{"text": x.text, "score": round(x.score, 3), "rect": list(x.rect)} for x in o.read(frame, rect)]
            data: dict = {"results": results}
        elif rect is None:
            raise ApiError(422, "bad_rect", "line / number 模式需要识别区域")
        elif body.mode == "line":
            x = o.read_line(frame, rect)
            data = {"results": [{"text": x.text, "score": round(x.score, 3), "rect": list(x.rect)}]}
        else:
            data = {"number": o.read_number(frame, rect)}
        data["ms"] = round((time.perf_counter() - t0) * 1000, 1)
        return data

    return r

