"""构建冻结版引擎并做冒烟测试（B10）。

在 engine/ 下：
    python -m uv run --group build python packaging/build.py            # 检查版本号 → PyInstaller → 冒烟测试
    python -m uv run --group build python packaging/build.py --smoke    # 只对已有产物做冒烟测试

冒烟测试不碰设备：`serve --no-connect --paused`，数据目录用临时目录。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
REPO = ENGINE.parent
APP = REPO / "app"
DIST = ENGINE / "dist" / "e7engine"
EXE = DIST / "e7engine.exe"
EXPECTED_MODULES = {"arena_npc", "daily", "hello", "repeat_battle", "secret_shop"}


def versions() -> dict[str, str]:
    init = (ENGINE / "e7helper" / "__init__.py").read_text(encoding="utf-8")
    return {
        "engine/e7helper/__init__.py": re.search(r'__version__ = "([^"]+)"', init).group(1),
        "engine/pyproject.toml": tomllib.loads((ENGINE / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"],
        "app/package.json": json.loads((APP / "package.json").read_text(encoding="utf-8"))["version"],
        "app/src-tauri/tauri.conf.json": json.loads((APP / "src-tauri" / "tauri.conf.json").read_text(encoding="utf-8"))["version"],
        "app/src-tauri/Cargo.toml": tomllib.loads((APP / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8"))["package"]["version"],
    }


def check_versions() -> str:
    found = versions()
    if len(set(found.values())) != 1:
        lines = "\n".join(f"  {k}: {v}" for k, v in found.items())
        sys.exit(f"版本号不一致：\n{lines}")
    version = next(iter(found.values()))
    print(f"版本号 {version}（{len(found)} 处一致）")
    return version


def build() -> None:
    shutil.rmtree(DIST, ignore_errors=True)
    started = time.time()
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
         "--distpath", str(ENGINE / "dist"), "--workpath", str(ENGINE / "build"),
         str(ENGINE / "packaging" / "e7engine.spec")],
        cwd=ENGINE, check=True,
    )
    print(f"PyInstaller 完成：{time.time() - started:.0f} 秒")


def dir_size(path: Path) -> tuple[int, int]:
    files = [p for p in path.rglob("*") if p.is_file()]
    return sum(p.stat().st_size for p in files), len(files)


def _run(args: list[str], env: dict[str, str]) -> str:
    out = subprocess.run([str(EXE), *args], env=env, capture_output=True, timeout=120)
    text = out.stdout.decode("utf-8", "replace") + out.stderr.decode("utf-8", "replace")
    if out.returncode != 0:
        sys.exit(f"e7engine {' '.join(args)} 失败（{out.returncode}）：\n{text}")
    return text


def smoke() -> None:
    if not EXE.exists():
        sys.exit(f"找不到 {EXE}，先构建")
    with tempfile.TemporaryDirectory(prefix="e7smoke-") as tmp:
        env = {**os.environ, "E7_DATA_DIR": tmp, "PYTHONIOENCODING": "utf-8", "E7_API_TOKEN": "smoke-token"}

        text = _run(["modules"], env)
        missing = [m for m in EXPECTED_MODULES if m not in text]
        if missing:
            sys.exit(f"模块发现不全，缺 {missing}：\n{text}")
        print(f"[ok] modules：{len(EXPECTED_MODULES)} 个模块都在")

        fixture = ENGINE / "tests" / "fixtures" / "secret_shop.png"
        text = _run(["match", "secret_shop", "title", "-f", str(fixture)], env)
        if "title" not in text:
            sys.exit(f"模板匹配异常：\n{text}")
        text = _run(["ocr", "-f", str(fixture)], env)
        found = re.search(r"(\d+) 条", text)
        if "模型加载" not in text or not found or int(found.group(1)) == 0:
            sys.exit(f"OCR 异常：\n{text}")
        print(f"[ok] 模板匹配；OCR 模型加载并识别出 {found.group(1)} 条文字")

        _smoke_serve(env, Path(tmp))


def _smoke_serve(env: dict[str, str], data: Path) -> None:
    info_path = data / "api.json"
    log = (data / "serve.log").open("wb")
    started = time.time()
    proc = subprocess.Popen([str(EXE), "serve", "--port", "0", "--no-connect", "--paused"],
                            env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        url = None
        while time.time() - started < 60:
            if proc.poll() is not None:
                sys.exit(f"serve 退出了（{proc.returncode}）：\n{(data / 'serve.log').read_text('utf-8', 'replace')}")
            try:
                info = json.loads(info_path.read_text(encoding="utf-8"))
                urllib.request.urlopen(info["url"] + "/api/health", timeout=1).read()
                url = info["url"]
                break
            except (OSError, ValueError, KeyError):
                time.sleep(0.1)
        if url is None:
            sys.exit("serve 60 秒内没有就绪")
        print(f"[ok] serve 就绪：{time.time() - started:.1f} 秒")

        def call(path: str, method: str = "GET"):
            req = urllib.request.Request(url + path, method=method, headers={"Authorization": "Bearer smoke-token"})
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"null")

        _, mods = call("/api/modules")
        assert {m["id"] for m in mods} == EXPECTED_MODULES, mods
        _, status = call("/api/status")
        assert status["device"]["connected"] is False and status["scheduler"]["paused"] is True, status
        _, detail = call("/api/modules/daily")
        assert "properties" in detail["config_schema"], detail
        print("[ok] REST：modules / status / config_schema")

        asyncio.run(_smoke_ws(url))
        print("[ok] WebSocket：/ws hello、/ws/frames 未连接状态")

        code, _ = call("/api/shutdown", "POST")
        assert code == 202
        proc.wait(timeout=15)
        assert not info_path.exists(), "退出后 api.json 还在"
        print(f"[ok] /api/shutdown：正常退出（{proc.returncode}），api.json 已删除")
    finally:
        if proc.poll() is None:
            proc.kill()
        log.close()


async def _smoke_ws(url: str) -> None:
    import websockets

    ws_url = url.replace("http://", "ws://")
    async with websockets.connect(f"{ws_url}/ws?token=smoke-token") as ws:
        hello = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert hello["type"] == "hello", hello
        await ws.send(json.dumps({"id": "1", "op": "ping"}))
        reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert reply["type"] == "reply" and reply["ok"], reply
    async with websockets.connect(f"{ws_url}/ws/frames?token=smoke-token") as ws:
        msg = json.loads(await asyncio.wait_for(ws.recv(), 10))
        assert msg == {"type": "status", "connected": False}, msg


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--smoke", action="store_true", help="只对已有产物做冒烟测试")
    parser.add_argument("--no-smoke", action="store_true", help="只构建，不做冒烟测试")
    args = parser.parse_args()

    check_versions()
    if not args.smoke:
        build()
    size, count = dir_size(DIST)
    print(f"产物 {DIST}：{size / 1e6:.0f} MB，{count} 个文件")
    if not args.no_smoke:
        smoke()
        print("冒烟测试通过")


if __name__ == "__main__":
    main()
