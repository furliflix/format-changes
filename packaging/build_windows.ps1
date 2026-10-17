# 在 Windows 上打包出 dist\FormatChanges\FormatChanges.exe
# 方便你自己先体验打包后的效果；也可以顺手发给用 Windows 的同学/老师。
#
# 用法（在项目根目录，PowerShell 里）：
#     powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

Write-Host "==> [1/5] 准备虚拟环境"
python -m venv .venv-build
. .\.venv-build\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt

Write-Host "==> [2/5] 生成图标"
python packaging\make_icon.py

Write-Host "==> [3/5] 运行自检"
python tests\smoke_cli.py

Write-Host "==> [4/5] PyInstaller 打包"
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist) { Remove-Item -Recurse -Force dist }
python -m PyInstaller --noconfirm --clean FormatChanges.spec

Write-Host "==> [5/5] 完成！可执行文件：dist\FormatChanges\FormatChanges.exe"
