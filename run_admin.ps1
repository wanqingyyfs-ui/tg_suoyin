# 自动定位到脚本所在目录的父目录
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# 激活虚拟环境
.\.venv\Scripts\Activate.ps1

# 启动后台管理
python scripts\admin_server.py
