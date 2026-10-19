"""自定义流程和玩家模板接口（B11，GUI「我的流程」「模板采集」页用）。要 token。

流程（`/api/flows`）：
| 路由 | 说明 |
|---|---|
| `GET /flows` | 全部流程的概况（步数、缺少的模板、最近一次运行） |
| `GET /flows/{id}`、`POST /flows`、`PUT /flows/{id}` | 读 / 新建（分配 id）/ 保存整个流程；校验失败 422 `invalid_flow` |
| `DELETE /flows/{id}?force=` | 有计划在用时 409 `in_use`；force=true 连同这些计划一起删 |
| `POST /flows/{id}/copy` | 复制一份（名字加「副本」） |

运行就是普通任务：`POST /api/tasks {"module": "custom_flow", "config": {"flow": "<id>"}}`。

玩家模板（`/api/user-templates`，存 `<数据目录>/flows/templates/`，只给流程用）：
| 路由 | 说明 |
|---|---|
| `GET /user-templates` | `mine`（玩家模板）+ `common`（内置共用，只读），各带被哪些流程用到 |
| `GET /user-templates/image?ref=` | 模板图片（PNG），ref 是 `名字` 或 `common:名字` |
| `POST /user-templates` | 在冻结的画面（`POST /api/capture/frames`）上按矩形保存，并回验 |
| `DELETE /user-templates/{name}?force=` | 有流程在用时 409 `in_use` |
| `POST /user-templates/test` | 在冻结的画面或当前画面（只读截图）上测试几个模板 |

内置模块的模板不能通过这里修改。
"""

from __future__ import annotations

import time

import cv2
from fastapi import APIRouter, Response
from pydantic import BaseModel, Field, ValidationError, field_validator

from e7helper.core.flows import (
    COMMON_PREFIX,
    Flow,
    FlowNotFound,
    FlowStore,
    common_template_store,
    missing_templates,
    user_template_store,
)
from e7helper.core.paths import module_data_dir
from e7helper.core.vision import TemplateMeta, TemplateNotFound, Vision, best_match
from e7helper.core.vision.template_store import validate_name

from .capture import FrameCache, RectList, _match_dict, _rect, verify_template
from .engine import ApiError, Engine, _tail_jsonl, validation_detail
from .scheduler import Scheduler

FLOW_MODULE = "custom_flow"
MAX_NAME = 30


def _flow_users(store: FlowStore) -> dict[str, list[dict]]:
    """模板引用 → 用到它的流程。"""
    users: dict[str, list[dict]] = {}
    for f in store.list():
        if isinstance(f, Flow):
            for ref in f.template_refs():
                users.setdefault(ref, []).append({"id": f.id, "name": f.name})
    return users


def _last_runs() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for h in _tail_jsonl(module_data_dir(FLOW_MODULE) / "history.jsonl", 500):
        if isinstance(h, dict) and h.get("flow"):
            out[h["flow"]] = h
    return out


def _summary(f: Flow, last: dict | None) -> dict:
    return {
        "id": f.id, "name": f.name, "description": f.description, "steps": len(f.steps),
        "limits": f.limits.model_dump(), "created": f.created, "updated": f.updated,
        "missing": missing_templates(f), "last_run": last,
    }


class TemplateSaveBody(BaseModel):
    frame: str
    name: str = Field(min_length=1, max_length=MAX_NAME)
    box: RectList = Field(description="模板区域 x,y,w,h（基准坐标）")
    tap: RectList | None = Field(None, description="点击区域（能点的地方和要认的东西不一样时）")
    moving: bool = Field(False, description="位置会变：全屏找；否则只在采集位置附近找")
    dim_check: bool = Field(False, description="按钮变暗（不能点 / 被弹窗盖住）时不算")
    threshold: float = Field(0.85, ge=0.6, le=0.98)
    note: str = Field("", max_length=200)
    overwrite: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if "/" in v:
            raise ValueError("名字里不能有 /")
        return validate_name(v)


class TestBody(BaseModel):
    frame: str | None = Field(None, description="冻结的画面；不给就截当前画面（只读）")
    templates: list[str] = Field(min_length=1, max_length=20)


def build_flows_router(engine: Engine, scheduler: Scheduler, frames: FrameCache) -> APIRouter:
    r = APIRouter(tags=["自定义流程"])

    def store() -> FlowStore:
        return FlowStore()

    def get_flow(fid: str) -> Flow:
        try:
            return store().get(fid)
        except FlowNotFound:
            raise ApiError(404, "unknown_flow", f"没有这个流程：{fid}") from None
        except (ValidationError, ValueError) as e:
            raise ApiError(500, "broken_flow", f"流程文件读不了：{e}") from e

    def parse(body: dict, fid: str = "") -> Flow:
        # GET 返回的只读字段原样发回来也没关系
        body = {k: v for k, v in body.items() if k not in ("id", "missing", "created", "updated")}
        try:
            return Flow.model_validate({**body, "id": fid})
        except ValidationError as e:
            raise ApiError(422, "invalid_flow", "流程不合法", validation_detail(e)) from e

    def full(f: Flow) -> dict:
        return {**f.dump(), "missing": missing_templates(f)}

    def schedules_of(fid: str) -> list[dict]:
        return [s for s in scheduler.snapshot()["schedules"]
                if s["module"] == FLOW_MODULE and (s.get("config") or {}).get("flow") == fid]

    # ------------------------------------------------------------ 流程

    @r.get("/flows", summary="全部流程")
    def list_flows() -> list[dict]:
        last = _last_runs()
        out = []
        for f in store().list():
            if isinstance(f, Flow):
                out.append(_summary(f, last.get(f.id)))
            else:
                out.append({"id": f[0], "name": f[0], "error": f[1]})
        return out

    @r.get("/flows/{fid}", summary="一个流程的全部内容")
    def read_flow(fid: str) -> dict:
        return full(get_flow(fid))

    @r.post("/flows", status_code=201, summary="新建流程")
    def create_flow(body: dict) -> dict:
        return full(store().save(parse(body)))

    @r.put("/flows/{fid}", summary="保存流程（整体替换）")
    def save_flow(fid: str, body: dict) -> dict:
        old = get_flow(fid)
        flow = parse(body, fid)
        flow.created = old.created
        return full(store().save(flow))

    @r.post("/flows/{fid}/copy", status_code=201, summary="复制流程")
    def copy_flow(fid: str) -> dict:
        src = get_flow(fid)
        name = f"{src.name} 副本"[:40]
        return full(store().save(src.model_copy(update={"id": "", "name": name, "created": None})))

    @r.delete("/flows/{fid}", status_code=204, response_class=Response, summary="删除流程")
    def delete_flow(fid: str, force: bool = False) -> Response:
        get_flow(fid)
        used = schedules_of(fid)
        if used and not force:
            raise ApiError(409, "in_use", "有计划在用这个流程", [{"id": s["id"], "name": s["name"]} for s in used])
        for s in used:
            scheduler.delete(s["id"])
        store().delete(fid)
        return Response(status_code=204)

    # ------------------------------------------------------------ 玩家模板

    def tpl_info(tpl, ref: str, users: dict) -> dict:
        return {"ref": ref, "name": tpl.name, "size": list(tpl.size), "note": tpl.meta.note,
                "moving": tpl.meta.region is None, "dim_check": tpl.meta.max_diff is not None,
                "has_tap": tpl.meta.tap is not None, "used_by": users.get(ref, [])}

    @r.get("/user-templates", summary="玩家模板 + 内置共用模板（只读）")
    def list_templates() -> dict:
        users = _flow_users(store())
        out: dict[str, list] = {"mine": [], "common": []}
        for key, st, prefix in (("mine", user_template_store(), ""), ("common", common_template_store(), COMMON_PREFIX)):
            for name in st.names():
                try:
                    tpl = st.get(name)
                except Exception as e:  # noqa: BLE001 —— 坏文件也列出来
                    out[key].append({"ref": prefix + name, "name": name, "error": str(e), "used_by": []})
                    continue
                if key == "common" and name.startswith("popup/"):
                    continue  # 弹窗模板由引擎自动处理，不给流程用
                out[key].append(tpl_info(tpl, prefix + name, users))
        return out

    def resolve(ref: str):
        try:
            if ref.startswith(COMMON_PREFIX):
                return common_template_store().get(ref[len(COMMON_PREFIX):])
            return user_template_store().get(ref)
        except (TemplateNotFound, ValueError) as e:
            raise ApiError(404, "unknown_template", f"模板不存在：{ref}") from e

    @r.get("/user-templates/image", summary="模板图片（PNG）", response_class=Response)
    def template_image(ref: str) -> Response:
        ok, buf = cv2.imencode(".png", resolve(ref).image)
        return Response(buf.tobytes(), media_type="image/png", headers={"Cache-Control": "no-cache"})

    @r.post("/user-templates", summary="保存玩家模板并回验")
    def save_template(body: TemplateSaveBody) -> dict:
        frame = frames.get(body.frame)
        box = _rect(body.box, "模板区域")
        if box.w < 8 or box.h < 8:
            raise ApiError(422, "bad_rect", "框太小了（至少 8×8）")
        region = None if body.moving else box.expand(40).clip()
        meta = TemplateMeta(region=region, box=box, tap=_rect(body.tap, "点击区域"), threshold=body.threshold,
                            max_diff=30.0 if body.dim_check else None, note=body.note)
        st = user_template_store()
        try:
            tpl = st.save(body.name, box.crop(frame).copy(), meta, overwrite=body.overwrite)
        except FileExistsError as e:
            raise ApiError(409, "exists", f"已经有叫「{body.name}」的模板了（勾选覆盖再保存）") from e
        verify = verify_template(frame, tpl, box)
        own, other = verify["own"], verify["other"]
        if own is None or not own["hit"]:
            quality = "weak"  # 在原位置都认不出（一般是框里颜色太单一）
        elif other is not None and other["score"] >= tpl.threshold - 0.05:
            quality = "ambiguous"  # 画面上还有很像的地方
        else:
            quality = "good"
        return {**tpl_info(tpl, tpl.name, _flow_users(store())), "verify": verify, "quality": quality}

    @r.delete("/user-templates/{name}", status_code=204, response_class=Response, summary="删除玩家模板")
    def delete_template(name: str, force: bool = False) -> Response:
        st = user_template_store()
        try:
            png = st.root / f"{validate_name(name)}.png"
        except ValueError as e:
            raise ApiError(404, "unknown_template", str(e)) from e
        if not png.is_file():
            raise ApiError(404, "unknown_template", f"模板不存在：{name}")
        used = _flow_users(store()).get(name, [])
        if used and not force:
            raise ApiError(409, "in_use", "有流程在用这个模板", used)
        png.unlink()
        png.with_suffix(".json").unlink(missing_ok=True)
        return Response(status_code=204)

    @r.post("/user-templates/test", summary="在画面上测试模板（不设阈值的最佳位置）")
    def test_templates(body: TestBody) -> dict:
        frame = frames.get(body.frame) if body.frame else engine.screenshot()
        vision = Vision([user_template_store()])
        out = []
        for ref in body.templates:
            try:
                tpl = vision.template(ref)
            except (TemplateNotFound, ValueError):
                out.append({"ref": ref, "error": "模板不存在"})
                continue
            t0 = time.perf_counter()
            m = best_match(frame, tpl)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            out.append({"ref": ref, **(_match_dict(m, tpl) if m else {"error": "模板比检索区域还大"}), "ms": ms})
        return {"frame": body.frame, "results": out}

    return r


__all__ = ["FLOW_MODULE", "build_flows_router"]
