# B14b：模型网格，在 GPU 训练环境里依次跑，曲线看 e7helper rta watch。
# 用法（在 engine/ 下）：powershell -ExecutionPolicy Bypass -File tools/rta_grid.ps1 [第几组]
# 第 1 组（最早跑的）：纯 Transformer 的 d / 层数 / λ；第 2 组：纯 Transformer 大容量对照 + 混合结构 + 因子分解机的 k
param([int]$Group = 2)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$Py = ".venv-rocm\Scripts\python.exe"
$Groups = @{
    1 = @(
        @("-m", "transformer", "--d", "64", "--layers", "2", "--lambda", "1"),
        @("-m", "transformer", "--d", "64", "--layers", "2", "--lambda", "0.5")
    )
    2 = @(
        @("-m", "transformer", "--d", "128", "--layers", "3", "--lambda", "0.5"),
        @("-m", "hybrid", "--d", "64", "--layers", "2", "--lambda", "0.5"),
        @("-m", "hybrid", "--d", "128", "--layers", "3", "--lambda", "1"),
        @("-m", "fm", "--k", "8"),
        @("-m", "fm", "--k", "32")
    )
}
foreach ($cfg in $Groups[$Group]) {
    & $Py -X utf8 -m e7helper.cli rta train --device cuda @cfg
}
