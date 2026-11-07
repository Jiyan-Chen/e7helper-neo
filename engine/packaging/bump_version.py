"""改版本号：5 处一起改（build.py 会检查它们一致），再更新两个锁文件。

在 engine/ 下：
    python packaging/bump_version.py 0.5.0
    python packaging/bump_version.py 0.5.0-beta.1     # 测试版带预发布后缀；uv.lock 里会规范成 0.5.0b1

之后提交、打标签、build.py、pnpm bundle（见 docs/HANDOFF.md「打包」）。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
REPO = ENGINE.parent
MIRROR = "https://repo.huaweicloud.com/repository/pypi/simple"  # 本机直连 PyPI 太慢（CLAUDE.md）


def current() -> str:
    init = (ENGINE / "e7helper" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__ = "([^"]+)"', init).group(1)


def main() -> None:
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?", sys.argv[1]):
        sys.exit("用法：python packaging/bump_version.py <新版本号>，例如 0.5.0 或 0.5.0-beta.1")
    old, new = current(), sys.argv[1]
    spots = {
        "engine/e7helper/__init__.py": '__version__ = "{}"',
        "engine/pyproject.toml": 'version = "{}"',
        "app/package.json": '"version": "{}"',
        "app/src-tauri/tauri.conf.json": '"version": "{}"',
        "app/src-tauri/Cargo.toml": 'version = "{}"',
    }
    for rel, pattern in spots.items():
        path = REPO / rel
        text = path.read_bytes().decode("utf-8")
        a, b = pattern.format(old), pattern.format(new)
        if text.count(a) != 1:
            sys.exit(f"{rel} 里找不到唯一的 {a}")
        path.write_bytes(text.replace(a, b, 1).encode("utf-8"))  # 保留原来的换行符
        print(f"{rel}: {old} → {new}")
    env = {**os.environ, "UV_DEFAULT_INDEX": os.environ.get("UV_DEFAULT_INDEX", MIRROR)}
    subprocess.run([sys.executable, "-m", "uv", "lock"], cwd=ENGINE, env=env, check=True)
    subprocess.run(["cargo", "update", "--workspace", "--offline"], cwd=REPO / "app" / "src-tauri", check=True)


if __name__ == "__main__":
    main()
