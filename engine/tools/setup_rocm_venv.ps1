# B14b：建 GPU 训练环境 engine/.venv-rocm（AMD 显卡 + Windows ROCm 版 torch）。
# AMD 官方的 Windows 轮子只有 Python 3.12，所以单独建一个 venv，不动引擎的 .venv（3.13）。
# 用法（在 engine/ 下）：powershell -ExecutionPolicy Bypass -File tools/setup_rocm_venv.ps1
# 之后：.venv-rocm\Scripts\python.exe -m e7helper.cli rta train --device cuda ...
$ErrorActionPreference = "Stop"
$Rocm = "https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1"
$env:UV_DEFAULT_INDEX = "https://repo.huaweicloud.com/repository/pypi/simple"
# uv 的 Python 下载默认走 GitHub，换成国内镜像
if (-not $env:UV_PYTHON_INSTALL_MIRROR) {
    $env:UV_PYTHON_INSTALL_MIRROR = "https://registry.npmmirror.com/-/binary/python-build-standalone"
}
Set-Location (Split-Path $PSScriptRoot -Parent)
# Python 3.12 装到 engine/.python：默认的 AppData 在 Claude 桌面版（MSIX）的会话里会被重定向，外面的终端找不到
if (-not $env:UV_PYTHON_INSTALL_DIR) {
    $env:UV_PYTHON_INSTALL_DIR = Join-Path (Get-Location) ".python"
}

python -m uv python install 3.12
python -m uv venv .venv-rocm --python 3.12 --managed-python --clear
$Py = ".venv-rocm\Scripts\python.exe"
# 运行库（核心 + 显卡库）和 torch；rocm_sdk_devel 是编译用的，不装
python -m uv pip install --python $Py `
    "$Rocm/rocm-7.2.1.tar.gz" `
    "$Rocm/rocm_sdk_core-7.2.1-py3-none-win_amd64.whl" `
    "$Rocm/rocm_sdk_libraries_custom-7.2.1-py3-none-win_amd64.whl" `
    "$Rocm/torch-2.9.1%2Brocm7.2.1-cp312-cp312-win_amd64.whl"
# 引擎本身（训练代码在 e7helper.core.rta.train）+ 导出要的包
python -m uv pip install --python $Py -e . onnx onnxscript pytest
& $Py -c "import torch; print('torch', torch.__version__, 'gpu', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
