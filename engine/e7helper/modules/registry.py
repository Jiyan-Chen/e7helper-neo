"""模块发现：扫描 e7helper.modules 下的子包 + entry-point 组 `e7helper.modules`。"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
from importlib.metadata import entry_points
from types import ModuleType

from .base import Module

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "e7helper.modules"


class ModuleRegistryError(RuntimeError):
    pass


def _module_classes(mod: ModuleType) -> list[type[Module]]:
    found = []
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        if (
            issubclass(obj, Module)
            and obj.__module__ == mod.__name__
            and not inspect.isabstract(obj)
            and getattr(obj, "id", None)
        ):
            found.append(obj)
    return found


def _register(registry: dict[str, type[Module]], cls: type[Module], source: str) -> None:
    existing = registry.get(cls.id)
    if existing is not None and existing is not cls:
        raise ModuleRegistryError(
            f"模块 id 重复：{cls.id!r}（{existing.__module__} 与 {cls.__module__}）"
        )
    registry[cls.id] = cls
    log.debug("registered module %s from %s", cls.id, source)


def discover(package: str = "e7helper.modules", include_entry_points: bool = True) -> dict[str, type[Module]]:
    registry: dict[str, type[Module]] = {}

    pkg = importlib.import_module(package)
    for info in pkgutil.walk_packages(pkg.__path__, prefix=f"{package}."):
        mod = importlib.import_module(info.name)
        for cls in _module_classes(mod):
            _register(registry, cls, info.name)

    if include_entry_points:
        for ep in entry_points(group=ENTRY_POINT_GROUP):
            obj = ep.load()
            classes = [obj] if inspect.isclass(obj) else _module_classes(obj)
            for cls in classes:
                _register(registry, cls, f"entry-point {ep.name}")

    return dict(sorted(registry.items()))
