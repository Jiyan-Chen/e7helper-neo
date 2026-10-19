"""流程和玩家模板的存储（B11）。

- 流程：`<数据目录>/flows/<id>.json`，一个文件一个流程，写入用临时文件 + 替换；
- 玩家模板：`<数据目录>/flows/templates/<名字>.png` + `.json`，格式和内置模板一样（`TemplateStore`）。

流程运行时的模板查找（`flow_vision`）：不带前缀的名字只在玩家模板里找；`common:名字` 是内置共用模板（只读）。
内置模块的模板不开放给流程，也不能通过玩家接口修改。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

from pydantic import ValidationError

from e7helper.core import paths
from e7helper.core.vision import COMMON_ID, TemplateNotFound, TemplateStore, Vision

from .model import COMMON_PREFIX, Flow


class FlowNotFound(KeyError):
    pass


def user_template_store() -> TemplateStore:
    return TemplateStore(paths.user_templates_dir())


def common_template_store() -> TemplateStore:
    return TemplateStore.for_module(COMMON_ID)


def flow_vision() -> Vision:
    """流程用的识别器：只有玩家模板这一层，`common:` 前缀走 Vision 的限定引用。"""
    return Vision([user_template_store()])


def template_exists(ref: str, user: TemplateStore | None = None, common: TemplateStore | None = None) -> bool:
    try:
        if ref.startswith(COMMON_PREFIX):
            return ref[len(COMMON_PREFIX):] in (common or common_template_store())
        return ref in (user or user_template_store())
    except ValueError:  # 名字不合法
        return False


def missing_templates(flow: Flow) -> list[str]:
    user, common = user_template_store(), common_template_store()
    return sorted(r for r in flow.template_refs() if not template_exists(r, user, common))


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


class FlowStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else paths.flows_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, flow_id: str) -> Path:
        Flow.model_validate({"id": flow_id, "name": "x"})  # 校验 id，防止路径穿越
        return self.root / f"{flow_id}.json"

    def ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))

    def exists(self, flow_id: str) -> bool:
        try:
            return self._path(flow_id).is_file()
        except ValidationError:
            return False

    def get(self, flow_id: str) -> Flow:
        try:
            path = self._path(flow_id)
        except ValidationError as e:
            raise FlowNotFound(flow_id) from e
        if not path.is_file():
            raise FlowNotFound(flow_id)
        flow = Flow.model_validate_json(path.read_text(encoding="utf-8"))
        flow.id = flow_id
        return flow

    def list(self) -> list[Flow | tuple[str, str]]:
        """全部流程，按名字排序；读不了的文件返回 (id, 错误)。"""
        out: list[Flow | tuple[str, str]] = []
        for fid in self.ids():
            try:
                out.append(self.get(fid))
            except (ValidationError, ValueError, OSError) as e:
                out.append((fid, str(e)))
        return sorted(out, key=lambda f: f.name if isinstance(f, Flow) else f"￿{f[0]}")

    def new_id(self) -> str:
        while True:
            fid = "f" + uuid.uuid4().hex[:7]
            if not (self.root / f"{fid}.json").exists():
                return fid

    def save(self, flow: Flow) -> Flow:
        """保存（没有 id 时分配一个）。返回保存后的流程。"""
        now = time.time()
        flow = flow.model_copy(deep=True)
        if not flow.id:
            flow.id = self.new_id()
            flow.created = now
        elif flow.created is None:
            old = self.get(flow.id) if self.exists(flow.id) else None
            flow.created = old.created if old and old.created else now
        flow.updated = now
        _write_atomic(self._path(flow.id), json.dumps(flow.dump(), ensure_ascii=False, indent=2) + "\n")
        return flow

    def delete(self, flow_id: str) -> None:
        path = self._path(flow_id)
        if not path.is_file():
            raise FlowNotFound(flow_id)
        path.unlink()

    def users_of(self, template_ref: str) -> list[Flow]:
        """用到某个模板的流程。"""
        return [f for f in self.list() if isinstance(f, Flow) and template_ref in f.template_refs()]


__all__ = [
    "FlowNotFound",
    "FlowStore",
    "TemplateNotFound",
    "common_template_store",
    "flow_vision",
    "missing_templates",
    "template_exists",
    "user_template_store",
]
