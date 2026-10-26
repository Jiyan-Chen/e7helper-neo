"""RTA 模型训练（B14b，开发用）：网络、训练循环、评估、ONNX 导出、训练曲线页。

要 torch（依赖组 `train`，或 GPU 环境 `.venv-rocm`，见 tools/setup_rocm_venv.ps1）。冻结引擎不带这个包，
运行时推理在 `core/rta/model.py`（只要 onnxruntime）。这里的 `__init__` 不导入 torch，曲线页（watch）不需要它。
"""

from __future__ import annotations

from pathlib import Path


def runs_dir() -> Path:
    """训练输出目录：采集库旁边的 runs/（F:\\e7helper-data\\rta\\runs）。"""
    from ..crawl import default_db_path

    return default_db_path().parent / "runs"


def require_torch():
    """导入 torch；没装时给出装依赖组的提示。"""
    try:
        import torch
    except ImportError as e:
        raise RuntimeError("没装 torch：在 engine/ 下跑 python -m uv sync --group train"
                           "（GPU 训练用 tools/setup_rocm_venv.ps1 建的 .venv-rocm）") from e
    return torch
