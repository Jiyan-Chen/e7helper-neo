"""冻结版引擎入口（PyInstaller，B10）：和 `e7helper` 命令完全相同，GUI 用 `e7engine.exe serve --port 0` 拉起。"""

import multiprocessing

from e7helper.cli import app

if __name__ == "__main__":
    multiprocessing.freeze_support()
    app(prog_name="e7engine")
