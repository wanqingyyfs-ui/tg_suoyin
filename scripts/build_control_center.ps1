param(
    [switch]$SkipInstall,
    [switch]$NoZip
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $PyLauncher = Get-Command py -ErrorAction SilentlyContinue
    if ($PyLauncher) {
        & py -3.12 -m venv ".venv"
    } else {
        $Python = Get-Command python -ErrorAction Stop
        & $Python.Source -m venv ".venv"
    }
}

if (-not (Test-Path $VenvPython)) {
    throw "虚拟环境创建失败：$VenvPython"
}

if (-not $SkipInstall) {
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r "requirements-control-center.txt"

    $Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $Npm) {
        $Npm = Get-Command npm -ErrorAction Stop
    }
    & $Npm.Source --prefix "web" ci
}

$Npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $Npm) {
    $Npm = Get-Command npm -ErrorAction Stop
}

& $VenvPython "scripts\export_frontend_data.py"
& $Npm.Source --prefix "web" run build

$BuildRoot = Join-Path $Root "build\control-center"
$ExeDist = Join-Path $Root "dist\control-center-exe"
$Portable = Join-Path $Root "dist\TG-Suoyin-Control-Center-portable"
$ZipPath = Join-Path $Root "dist\TG-Suoyin-Control-Center-portable.zip"

Remove-Item $BuildRoot -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $ExeDist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $Portable -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item $ZipPath -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Path $BuildRoot, $ExeDist, $Portable -Force | Out-Null

& $VenvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name "TG-Suoyin-Control-Center" `
    --distpath $ExeDist `
    --workpath $BuildRoot `
    --specpath $BuildRoot `
    --hidden-import "PySide6.QtCore" `
    --hidden-import "PySide6.QtGui" `
    --hidden-import "PySide6.QtWidgets" `
    "control_center\__main__.py"

$ExePath = Join-Path $ExeDist "TG-Suoyin-Control-Center.exe"
if (-not (Test-Path $ExePath)) {
    throw "EXE 构建失败：$ExePath"
}

Copy-Item $ExePath $Portable
Copy-Item "bot.py" $Portable
Copy-Item "LICENSE" $Portable
Copy-Item "README.md" $Portable
Copy-Item "README-CONTROL-CENTER.md" $Portable
Copy-Item ".env.example" $Portable
Copy-Item "scripts" $Portable -Recurse

New-Item -ItemType Directory -Path (Join-Path $Portable "data") -Force | Out-Null
Copy-Item "data\rectg.db" (Join-Path $Portable "data\rectg.db")

New-Item -ItemType Directory -Path (Join-Path $Portable "web") -Force | Out-Null
Copy-Item "web\dist" (Join-Path $Portable "web\dist") -Recurse
New-Item -ItemType Directory -Path (Join-Path $Portable "logs") -Force | Out-Null

$StartScript = @'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process -FilePath (Join-Path $Root "TG-Suoyin-Control-Center.exe") -WorkingDirectory $Root
'@
Set-Content -Path (Join-Path $Portable "启动控制中心.ps1") -Value $StartScript -Encoding UTF8

if (-not $NoZip) {
    Compress-Archive -Path (Join-Path $Portable "*") -DestinationPath $ZipPath -CompressionLevel Optimal -Force
}

Write-Host ""
Write-Host "✅ 控制中心构建完成" -ForegroundColor Green
Write-Host "便携目录：$Portable"
if (-not $NoZip) {
    Write-Host "便携压缩包：$ZipPath"
}
