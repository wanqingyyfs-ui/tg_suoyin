# TG 索引控制中心

TG 索引控制中心是本项目的 Windows 桌面管理程序，用一个无控制台窗口统一托管：

- 前端网站服务
- 本地管理后台
- Telegram Bot
- 资源、频道和群组管理
- 消息索引管理
- 广告管理
- 环境变量与基础配置
- 实时日志和数据库备份

## 运行方式

### 使用 GitHub Actions 便携包

1. 在仓库的 Actions 页面打开 `Build Windows Control Center`。
2. 下载构建产物 `TG-Suoyin-Control-Center-Windows`。
3. 解压 `TG-Suoyin-Control-Center-portable.zip`。
4. 双击 `TG-Suoyin-Control-Center.exe`。
5. 在“设置”页面填写 `TELEGRAM_BOT_TOKEN` 等配置并保存。
6. 回到“总览”页面启动前端、后台和 Bot。

程序启动和托管服务时不会打开 CMD、PowerShell 或其他终端窗口。关闭主窗口默认最小化到系统托盘，已启动服务继续运行。真正退出请使用托盘菜单中的“退出并停止全部”。

## 本地源码运行

```powershell
cd "D:\编程\tg_suoyin"
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-control-center.txt
python -m control_center
```

也可以执行：

```powershell
npm run control
```

## 本地打包

需要：

- Windows 10/11
- Python 3.12
- Node.js 22
- PowerShell 5.1 或 PowerShell 7

执行：

```powershell
cd "D:\编程\tg_suoyin"
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\build_control_center.ps1
```

构建结果：

```text
dist\TG-Suoyin-Control-Center-portable\
dist\TG-Suoyin-Control-Center-portable.zip
```

## 面板功能

### 总览

可独立启动、停止、重启前端、后台和 Bot，也可一键启动或停止全部服务。显示数据库统计并提供前端刷新、前端构建和数据库备份。

### 资源管理

- 搜索现有资源
- 批量添加公开 Telegram 链接或 `@username`
- 编辑标题、类型、分类和显示状态
- 多选显示、隐藏、开启监听、关闭监听
- 多选删除资源，并同时删除对应消息索引与 links 记录

危险删除前默认使用 SQLite Backup API 自动备份数据库。

### 消息管理

- 按关键词和资源 ID 筛选
- 查看来源、消息 ID、时间、内容预览、媒体信息、关键词和跳转链接
- 多选删除消息索引
- 清空指定资源的消息索引

### 广告管理

支持新增、编辑、多选删除、启用、禁用和排序。

### 设置

可管理：

- `SITE_URL`
- `TELEGRAM_BOT_TOKEN`
- Bot 请求和 polling 超时
- Webhook Host、Port、Secret
- 后台 Host、Port、Token
- 前端 Host、Port
- 自动启动
- 服务异常自动重启
- 关闭窗口最小化到托盘
- 删除前自动备份
- 数据变更后自动刷新前端数据

敏感值在面板中使用密码输入框显示，日志会自动遮蔽已知 Token 和 Secret。

### 日志

所有服务日志都在程序内查看，同时轮转写入：

```text
logs\control.log
logs\frontend.log
logs\admin.log
logs\bot.log
```

## 数据与安全

- 主数据库仍为 `data/rectg.db`。
- 数据库连接启用 `busy_timeout`、WAL 和事务。
- 删除资源和消息默认先备份到 `data/backups/`。
- `.env` 不进入 Git，面板会原子写入并保留 `.env.bak`。
- 控制中心使用单实例锁，防止重复启动多个面板。
- 服务异常退出可自动重启，连续失败最多重试 5 次。

## 前端更新

资源或广告变更后，控制中心默认执行数据导出，并将新的 `data.json`、`sitemap.xml` 和 `robots.txt` 同步到已经构建的前端目录。修改 Astro 页面源码后，需要点击“构建前端”或重新运行打包脚本。
