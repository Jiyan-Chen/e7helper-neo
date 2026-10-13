import logging
import sys
import types

import numpy as np
import pytest

from e7helper.modules import (
    AssistantModule,
    ModuleContext,
    ModuleKind,
    ModuleRegistryError,
    TaskModule,
    discover,
)
from e7helper.modules.registry import _module_classes, _register


class FakeDevice:
    name = "fake"
    resolution = (1600, 900)

    def screenshot(self):
        return np.zeros((900, 1600, 3), dtype=np.uint8)


def _ctx(tmp_path, device=None):
    return ModuleContext(
        device=device,
        logger=logging.getLogger("test"),
        assets_dir=tmp_path / "assets",
        data_dir=tmp_path / "data",
    )


def test_discover_finds_hello():
    modules = discover(include_entry_points=False)
    assert "hello" in modules
    assert modules["hello"].kind is ModuleKind.TASK


def test_base_classes_not_registered():
    modules = discover(include_entry_points=False)
    for cls in modules.values():
        assert cls not in (TaskModule, AssistantModule)


def test_config_schema_is_json_schema():
    schema = discover(include_entry_points=False)["hello"].config_schema()
    assert schema["type"] == "object"
    assert "greeting" in schema["properties"]


def test_hello_runs_and_respects_stop(tmp_path, caplog):
    cls = discover(include_entry_points=False)["hello"]
    ctx = _ctx(tmp_path, FakeDevice())
    module = cls(ctx, cls.config_model(screenshots=3))
    with caplog.at_level(logging.INFO, logger="test"):
        module.run()
    assert sum("1600x900" in r.message for r in caplog.records) == 3

    ctx.stop_event.set()
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="test"):
        module.run()
    assert not any("1600x900" in r.message for r in caplog.records)


def test_device_required(tmp_path):
    cls = discover(include_entry_points=False)["hello"]
    module = cls(_ctx(tmp_path))
    with pytest.raises(RuntimeError):
        module.run()


def test_assistant_module_contract(tmp_path):
    class Watcher(AssistantModule):
        id = "watcher"
        name = "watcher"

        def on_frame(self, frame):
            self.seen = frame.shape

    w = Watcher(_ctx(tmp_path))
    w.on_frame(np.zeros((900, 1600, 3), dtype=np.uint8))
    assert w.kind is ModuleKind.ASSISTANT
    assert w.seen == (900, 1600, 3)


def test_duplicate_id_rejected():
    mod_a = types.ModuleType("fake_a")
    mod_b = types.ModuleType("fake_b")

    class A(TaskModule):
        id = "dup"
        name = "a"

        def run(self):
            pass

    class B(TaskModule):
        id = "dup"
        name = "b"

        def run(self):
            pass

    A.__module__, B.__module__ = "fake_a", "fake_b"
    mod_a.A, mod_b.B = A, B
    sys.modules["fake_a"], sys.modules["fake_b"] = mod_a, mod_b
    try:
        registry: dict = {}
        for cls in _module_classes(mod_a):
            _register(registry, cls, "a")
        with pytest.raises(ModuleRegistryError):
            for cls in _module_classes(mod_b):
                _register(registry, cls, "b")
    finally:
        del sys.modules["fake_a"], sys.modules["fake_b"]
