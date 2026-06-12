# 自动定位到脚本所在目录的父目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 检查 Token
if (-not $env:TELEGRAM_BOT_TOKEN) {
  $env:TELEGRAM_BOT_TOKEN = Read-Host "请输入 TELEGRAM_BOT_TOKEN"
}

# 启动 Bot
python scripts\bot.py
