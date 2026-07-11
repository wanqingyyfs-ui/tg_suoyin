$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

Write-Host "[1/6] 安装 Python 项目依赖" -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-control-center.txt

Write-Host "[2/6] 安装前端依赖" -ForegroundColor Cyan
npm install --prefix web

Write-Host "[3/6] 从 SQLite 导出最新前端数据" -ForegroundColor Cyan
python scripts/export_frontend_data.py

Write-Host "[4/6] 构建 Astro 前端" -ForegroundColor Cyan
npm run build --prefix web

Write-Host "[5/6] 构建 Windows 桌面程序" -ForegroundColor Cyan
python -m PyInstaller --clean --noconfirm TGControlCenter.spec

$PackageDir = Join-Path $Root "dist\TG索引控制中心"
$ZipPath = Join-Path $Root "dist\TG索引控制中心-Windows-x64.zip"
if (Test-Path $ZipPath) {
    Remove-Item $ZipPath -Force
}

Write-Host "[6/6] 生成便携版压缩包" -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath -CompressionLevel Optimal

Write-Host ""
Write-Host "构建完成：" -ForegroundColor Green
Write-Host (Join-Path $PackageDir "TG索引控制中心.exe") -ForegroundColor Green
Write-Host $ZipPath -ForegroundColor Green
