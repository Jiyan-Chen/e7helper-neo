# PyInstaller spec：引擎冻结成 onedir（B10）。用 packaging/build.py 构建，不要直接调用。
# 产物 engine/dist/e7engine/（e7engine.exe + _internal/），由 Tauri 的 bundle.resources 带进安装包。
# E7_NO_RTA=1（build.py --no-rta，正式版）：不带 RTA 的代码和模型（e7helper/features.py 按代码在不在开关）。
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ENGINE = Path(SPECPATH).parent
NO_RTA = os.environ.get("E7_NO_RTA") == "1"
# RTA 模型训练（要 torch）只在开发机用，不进产物（B14b）；正式版整个 RTA 都不带
SKIP = ("e7helper.core.rta", "e7helper.api.rta") if NO_RTA else ("e7helper.core.rta.train",)

hiddenimports = (
    # 模块按 pkgutil 自动发现，静态分析看不到
    collect_submodules("e7helper", filter=lambda name: not name.startswith(SKIP))
    # uvicorn 按字符串导入协议实现（ws="websockets-sansio"、lifespan="on" 等）
    + collect_submodules("uvicorn")
    + collect_submodules("websockets")
)



def assets() -> list[tuple[str, str]]:
    """模板和随包数据，运行时 paths.ASSETS_DIR = sys._MEIPASS/assets；正式版去掉 assets/data/rta。"""
    root = ENGINE / "assets"
    if not NO_RTA:
        return [(str(root), "assets")]
    out = []
    for p in root.iterdir():
        if p.name != "data":
            out.append((str(p), f"assets/{p.name}" if p.is_dir() else "assets"))
            continue
        for q in p.iterdir():
            if q.name != "rta":
                out.append((str(q), f"assets/data/{q.name}" if q.is_dir() else "assets/data"))
    return out


datas = [
    *assets(),
    *collect_data_files("rapidocr"),  # config.yaml、default_models.yaml、models/*.onnx（不联网下载）
]

a = Analysis(
    [str(Path(SPECPATH) / "entry.py")],
    pathex=[str(ENGINE)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "_pytest", "httpx", "torch", "onnx", "onnxscript", *SKIP],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    # 冻结版忽略 PYTHON* 环境变量（PYTHONIOENCODING 不起作用），这里直接打开 UTF-8 模式，
    # 否则输出（包括 GUI 拉起时的 engine-stdout.log）是 GBK
    [("X utf8", None, "OPTION")],
    exclude_binaries=True,
    name="e7engine",
    console=True,  # 仍可当 CLI 用；GUI 拉起时加 CREATE_NO_WINDOW，不弹窗
    upx=False,
    icon=str(ENGINE.parent / "app" / "src-tauri" / "icons" / "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="e7engine", upx=False)
