# rectg

一个基于 SQLite、Python 爬虫和 Astro 前端的 Telegram 中文频道/群组搜索引擎项目。

本项目不再把 README 当作主数据源，而是以 SQLite 作为长期维护源，通过 Python 脚本维护、抓取、清洗、分类、状态管理、广告管理、导出，再由 Astro 构建静态搜索站点。

## 当前维护仓库

```text
https://github.com/wanqingyyfs-ui/rectg
```

## 本地项目位置

```text
D:\wanqing\projects\rectg
```

## 当前阶段状态

已完成：

```text
✅ 本地项目部署
✅ Python 虚拟环境
✅ Python 依赖安装
✅ 前端依赖安装
✅ README 不再作为主数据源
✅ SQLite 作为长期维护源
✅ links 表维护入口
✅ entries 表抓取和清洗
✅ Telegram 公开页面爬虫
✅ 过滤规则放宽
✅ SQLite 导出前端 data.json
✅ Astro 前端构建
✅ scripts/add_entry.py 添加频道/群组
✅ scripts/edit_category.py 分类编辑
✅ scripts/edit_status.py 状态管理
✅ scripts/manage_ads.py 广告位管理
✅ ads 表初始化
✅ export_frontend_data.py 导出 ads 字段
✅ npm run build 验证通过
```

最近验证结果：

```text
python scripts\edit_category.py stats        ✅ 正常
python scripts\edit_status.py list           ✅ 正常
python scripts\manage_ads.py init            ✅ 正常
python scripts\manage_ads.py add/list/update/disable/delete ✅ 正常
python scripts\export_frontend_data.py       ✅ 输出 Ads: 0
npm run build                                ✅ 542 page(s) built
```

当前长期流程：

```text
data/rectg.db
    ↓
scripts/export_frontend_data.py
    ↓
web/public/data.json
web/public/sitemap.xml
web/public/robots.txt
    ↓
Astro 前端展示和搜索
```

## 技术栈

### 后端 / 数据处理

```text
Python 3.13+
SQLite
requests
beautifulsoup4
lxml
opencc-python-reimplemented
emoji
Markdown
```

### 前端

```text
Node.js
npm
Astro
pinyin-match
@vercel/analytics
@vercel/speed-insights
```

## 项目目录

```text
rectg/
├── data/
│   └── rectg.db
├── scripts/
│   ├── add_entry.py
│   ├── categorize.py
│   ├── crawl.py
│   ├── edit_category.py
│   ├── edit_status.py
│   ├── export_frontend_data.py
│   ├── filter_rules.py
│   ├── generate_readme.py
│   ├── manage_ads.py
│   ├── parse_links.py
│   ├── refilter.py
│   └── scrape_tgnav.py
├── web/
│   ├── public/
│   │   ├── data.json
│   │   ├── robots.txt
│   │   └── sitemap.xml
│   ├── src/
│   │   └── pages/
│   │       ├── index.astro
│   │       └── p/
│   │           └── [id].astro
│   ├── package.json
│   └── package-lock.json
├── package.json
├── requirements.txt
├── README.md
└── vercel.json
```

## 虚拟环境

激活方式：

```powershell
cd D:\wanqing\projects\rectg
.\.venv\Scripts\Activate.ps1
```

验证 Python 依赖：

```powershell
python -c "import sys, requests, bs4, lxml; print(sys.executable); print('OK')"
```

预期 Python 路径：

```text
D:\wanqing\projects\rectg\.venv\Scripts\python.exe
```

## 安装依赖

### Python 依赖

```powershell
cd D:\wanqing\projects\rectg
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 前端依赖

```powershell
cd D:\wanqing\projects\rectg\web
npm install
```

## 数据库说明

主数据库：

```text
data/rectg.db
```

README 不再作为主数据源。长期维护必须以 SQLite 为准。

### links

保存待抓取的 Telegram 链接。

字段：

```text
id
url
username
name
type_hint
created_at
updated_at
```

### entries

保存已抓取、已整理、可筛选展示的频道/群组数据。

字段：

```text
id
telegram_id
username
url
type
title
description
clean_title
clean_desc
category
avatar
count
last_active
valid
private
keep
filter_reason
created_at
updated_at
```

前端导出只读取：

```sql
keep = 1
AND valid = 1
AND private = 0
```

### ads

保存广告位数据。

字段：

```text
id
position
title
description
url
image_url
sort_order
enabled
created_at
updated_at
```

初始化：

```powershell
python scripts\manage_ads.py init
```

`export_frontend_data.py` 会自动确保 `ads` 表存在。

## 构建说明

根目录构建：

```powershell
cd D:\wanqing\projects\rectg
npm run build
```

根目录 `package.json`：

```json
{
  "build": "cd web && npm run build"
}
```

`web/package.json`：

```json
{
  "build": "python ../scripts/export_frontend_data.py && astro build"
}
```

执行 `npm run build` 会自动完成：

```text
SQLite
    ↓
export_frontend_data.py
    ↓
web/public/data.json
web/public/sitemap.xml
web/public/robots.txt
    ↓
astro build
```

## 添加频道/群组

脚本：

```text
scripts/add_entry.py
```

添加公开频道：

```powershell
python scripts\add_entry.py https://t.me/your_username --type channel
```

添加公开群组：

```powershell
python scripts\add_entry.py your_group_username --type group
```

添加后立即抓取：

```powershell
python scripts\add_entry.py your_username --type channel --crawl
```

已有 entries 时强制展示：

```powershell
python scripts\add_entry.py your_username --keep
```

注意：`--keep` 只适合人工确认安全、有效、可展示的数据。

## 抓取数据

抓取新链接：

```powershell
python scripts\crawl.py --new --no-active
```

测试抓取前 5 条：

```powershell
python scripts\crawl.py --limit 5 --no-active
```

全量重爬：

```powershell
python scripts\crawl.py --no-resume --no-active
```

## 清洗和自动分类

脚本：

```text
scripts/categorize.py
```

执行：

```powershell
python scripts\categorize.py
```

该脚本用于：

```text
重新评估 keep / filter_reason
清洗标题
清洗简介
自动分类
```

## 手动编辑分类

脚本：

```text
scripts/edit_category.py
```

查看分类统计：

```powershell
python scripts\edit_category.py stats
```

查看内置分类：

```powershell
python scripts\edit_category.py categories
```

查看单个频道/群组分类：

```powershell
python scripts\edit_category.py get your_username
```

修改分类：

```powershell
python scripts\edit_category.py set your_username "💻 数码科技"
```

如果终端 emoji 输入异常，可以先用 ASCII 测试：

```powershell
python scripts\edit_category.py set your_username TEST_CATEGORY --allow-new
```

查看未分类 / 综合其他数据：

```powershell
python scripts\edit_category.py list --uncategorized --limit 30
```

分类修改后：

```powershell
python scripts\export_frontend_data.py
npm run build
```

## 手动编辑状态

脚本：

```text
scripts/edit_status.py
```

查看状态：

```powershell
python scripts\edit_status.py get your_username
```

手动放行：

```powershell
python scripts\edit_status.py set your_username --keep 1 --valid 1 --private 0 --clear-reason
```

手动隐藏：

```powershell
python scripts\edit_status.py set your_username --keep 0 --reason "人工隐藏"
```

查看被过滤数据：

```powershell
python scripts\edit_status.py list --filtered --limit 30
```

查看私密数据：

```powershell
python scripts\edit_status.py list --private --limit 30
```

## 广告位管理

脚本：

```text
scripts/manage_ads.py
```

初始化 ads 表：

```powershell
python scripts\manage_ads.py init
```

新增广告：

```powershell
python scripts\manage_ads.py add home_top "首页顶部广告" --url "https://example.com" --description "广告说明"
```

新增但默认禁用：

```powershell
python scripts\manage_ads.py add home_top "测试广告" --url "https://example.com" --description "测试说明" --disabled
```

查看启用广告：

```powershell
python scripts\manage_ads.py list
```

查看全部广告：

```powershell
python scripts\manage_ads.py list --all
```

启用广告：

```powershell
python scripts\manage_ads.py enable 1
```

禁用广告：

```powershell
python scripts\manage_ads.py disable 1
```

更新广告：

```powershell
python scripts\manage_ads.py update 1 --title "新标题" --sort-order 10
```

删除广告：

```powershell
python scripts\manage_ads.py delete 1 --yes
```

广告会导出到 `web/public/data.json` 顶层：

```json
{
  "categories": [],
  "types": [],
  "ads": {
    "items": [],
    "positions": {}
  }
}
```

当前前端暂时不读取 `ads` 字段，不影响原有 `categories` 和 `types`。

## 前端数据导出

脚本：

```text
scripts/export_frontend_data.py
```

执行：

```powershell
python scripts\export_frontend_data.py
```

成功输出示例：

```text
✅ Generated data.json from SQLite: D:\wanqing\projects\rectg\web\public\data.json
✅ Categories: 22
✅ Types: 2
✅ Items: 545
✅ Ads: 0
```

生成文件：

```text
web/public/data.json
web/public/sitemap.xml
web/public/robots.txt
```

## 常用维护流程

### 添加一个新频道

```powershell
python scripts\add_entry.py your_username --type channel --crawl
python scripts\categorize.py
python scripts\export_frontend_data.py
npm run build
```

### 修改分类

```powershell
python scripts\edit_category.py get your_username
python scripts\edit_category.py set your_username "💻 数码科技"
python scripts\export_frontend_data.py
npm run build
```

### 手动放行

```powershell
python scripts\edit_status.py get your_username
python scripts\edit_status.py set your_username --keep 1 --valid 1 --private 0 --clear-reason
python scripts\export_frontend_data.py
npm run build
```

### 新增广告

```powershell
python scripts\manage_ads.py init
python scripts\manage_ads.py add home_top "首页顶部广告" --url "https://example.com"
python scripts\export_frontend_data.py
npm run build
```

## 当前已知注意事项

### PowerShell 长脚本粘贴问题

PowerShell 的 `PSReadLine` 在粘贴超长 here-string 时可能崩溃。建议：

```text
不要在终端里粘贴过长 Python 脚本
优先用短命令测试
复杂脚本应写入 .py 文件再执行
```

### Emoji 分类输入问题

某些终端可能把 emoji 显示成 `??`。如果分类命令失败，优先执行：

```powershell
python scripts\edit_category.py categories
```

确认终端是否能正常显示内置分类。

### 测试后恢复数据

测试分类时，如果把 `sucaiwanqing16888` 改成了 `TEST_CATEGORY`，恢复方式：

```powershell
python -c "import sqlite3; conn=sqlite3.connect('data/rectg.db'); conn.execute('UPDATE entries SET category = NULL WHERE username = ?', ('sucaiwanqing16888',)); conn.commit(); conn.close(); print('restored category')"
```

## Git 工作流

查看状态：

```powershell
git status --short
```

推荐提交：

```powershell
git add README.md `
  data/rectg.db `
  scripts/add_entry.py `
  scripts/edit_category.py `
  scripts/edit_status.py `
  scripts/manage_ads.py `
  scripts/export_frontend_data.py `
  web/public/data.json `
  web/public/sitemap.xml `
  web/public/robots.txt
```

提交：

```powershell
git commit -m "Update project maintenance workflow"
```

推送：

```powershell
git push
```

不要提交：

```text
.venv/
node_modules/
web/node_modules/
web/dist/
.astro/
web/.astro/
.env
.env.*
*.log
*.bak
*.backup
*.tmp
*.temp
rectg_steps_1_4_fixed.zip
PACKAGE_MANIFEST.json
```

## 下一步开发路线

### 第 5 步：搜索核心脚本

先不要直接写 Telegram Bot。下一步应该新增搜索核心脚本：

```text
scripts/search_entries.py
```

目标：

```text
输入关键词
从 SQLite entries 搜索
只返回 keep=1、valid=1、private=0 的数据
支持 title / clean_title / description / clean_desc / username / category 搜索
支持 type 筛选 channel / group / bot
支持 category 筛选
支持 limit
支持 page
输出标题、简介、人数、链接、分类
```

建议命令：

```powershell
python scripts\search_entries.py 科技
python scripts\search_entries.py AI --limit 10
python scripts\search_entries.py 影视 --type channel
python scripts\search_entries.py 网盘 --page 2
python scripts\search_entries.py 科技 --category "💻 数码科技"
```

### 第 6 步：Telegram 搜索 Bot

搜索核心稳定后，再新增：

```text
scripts/bot.py
```

目标：

```text
用户输入关键词
Bot 调用搜索核心
返回频道/群组标题、简介、人数、链接
支持分页
支持分类筛选
后续支持广告插入
```

建议依赖：

```text
python-telegram-bot
python-dotenv
```

需要更新：

```text
requirements.txt
```

`.env` 示例：

```text
TELEGRAM_BOT_TOKEN=你的 Bot Token
```

`.env` 不允许提交到 Git。

### 第 7 步：Bot 广告插入

Bot 搜索可用后，再从 ads 表读取广告：

```text
position = bot_search_inline
enabled = 1
```

建议插入位置：

```text
每页搜索结果第 3 条后
没有广告则不显示
```

### 第 8 步：前端广告展示

当前 `data.json` 已经导出 ads，但前端还没展示。

需要修改：

```text
web/src/pages/index.astro
```

目标：

```text
读取 data.ads.positions.home_top
读取 data.ads.positions.home_sidebar
在首页展示广告
不破坏现有搜索功能
```

### 第 9 步：后台管理

等脚本和 Bot 稳定后再做后台。

后台本质上是把这些脚本网页化：

```text
add_entry.py
edit_category.py
edit_status.py
manage_ads.py
export_frontend_data.py
```

优先目标：

```text
管理频道/群组
管理分类
管理 keep / valid / private
管理广告
触发导出
```

### 第 10 步：部署

优先本地构建稳定，再部署。

路线：

```text
本地 npm run build
GitHub push
Vercel / Cloudflare Pages / 服务器部署
配置域名
提交 sitemap
```

如果部署环境跑 Python 不稳定，就采用：

```text
本地导出 web/public/data.json
提交 data.json
部署环境只跑 astro build
```

### 第 11 步：自动化维护

最后再做自动化：

```text
定时 crawl
定时 categorize
定时 export
自动 commit
自动部署
```

可选方案：

```text
GitHub Actions
服务器 cron
Windows 任务计划程序
```
