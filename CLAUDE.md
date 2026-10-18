# e7helper-neo

第七史诗**国服（简中）**、**仅 MuMu 模拟器**的助手平台：先做日常自动化，后续接入 RTA BP 助手等模块。

## 新会话先读
1. `docs/HANDOFF.md`：当前进度、下一块任务、注意事项
2. `docs/ROADMAP.md`：任务块清单与状态
3. `docs/architecture.md`：模块契约与扩展方式

## 工作流（必须遵守）
- **每个会话只做一个任务块（Bxx）**，开始时在 ROADMAP 里把它标成「进行中」。
- 完成后：
  1. 在 `docs/reviews/Bxx.md` 写审核记录，包括变更清单、验证命令、实测输出、已知问题。
  2. ROADMAP 状态改为「待审核」。
  3. 交给用户审核后**停下等待**，不要自行开始下一块。
- 用户审核通过后：
  1. ROADMAP 改为「已通过」，在审核记录里补上用户意见。
  2. 更新 `docs/HANDOFF.md`。
  3. 给出下一会话的启动提示词。由用户开新会话继续。
- 不要自行 git commit / push，除非用户要求。

## 关键约定
- 基准坐标系 **1600×900**（`e7helper/core/geometry.py`）。模板、坐标、区域一律按基准记录，运行时由 `Scaler` 换算。
- 截图统一为 BGR uint8 `(H, W, 3)`。读写图片用 `core.imageio.read_image` / `write_image`，因为 `cv2.imread` / `imwrite` 不支持中文路径。
- 设备层：IPC（`external_renderer_ipc.dll`）为主，MuMu 自带的 `adb.exe` 为后备。上层只依赖 `e7helper.device.Device`。
- 进程入口必须先调用 `core.stdio.isolate_native_stdout()`，因为 DLL 会往原生 stdout/stderr 写调试信息。Rich Console 一律用 `core.log.make_console()` 创建。
- 依赖安装：本机直连 PyPI 只有约 3KB/s，所以要设置 `UV_DEFAULT_INDEX=https://repo.huaweicloud.com/repository/pypi/simple`。`uv.lock` 目前锁定的也是这个镜像。
- 功能一律写成模块：`TaskModule`（会点击游戏，同一时间只能跑一个）或 `AssistantModule`（只读帧，可以并行）。放在 `engine/e7helper/modules/<id>/`，会被自动发现。
- 模块资源放在 `engine/assets/<module_id>/cn/`，用户数据放在 `%LOCALAPPDATA%\e7helper\modules\<id>\`。
- 游戏包名：`com.zlongame.cn.epicseven`。
- 代码注释和文档用简体中文，标识符用英文。

## 常用命令（在 `engine/` 下）
uv 是用 `pip install --user` 装的，不在 PATH 上，所以统一用 `python -m uv` 调用。
```
python -m uv sync
python -m uv run pytest                        # 单元测试
E7_DEVICE_TESTS=1 python -m uv run pytest -m device   # 真机测试（需 MuMu 运行）
python -m uv run e7helper doctor | bench | screenshot | tap X Y | modules | run <id>
```

## 本机环境（开发者）
- MuMu 6.8.7（B07 时 `doctor` 显示），安装在 `E:\MuMuPlayer-12.0`（新版 `nx_main` 结构），实例 0：Android 15，1600×900，adb `127.0.0.1:16384`。
- Python 3.13 x64。
