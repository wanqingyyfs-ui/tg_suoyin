# rectg

一个基于 SQLite、Python 爬虫和 Astro 前端的 Telegram 中文频道/群组搜索引擎项目。

本项目不再把 README 当作主数据源，而是以 SQLite 作为长期维护源，通过 Python 脚本维护、抓取、清洗、分类、导出，再由 Astro 构建静态搜索站点。

## 当前维护仓库

```text
https://github.com/wanqingyyfs-ui/rectg
```

## 本地项目位置

```text
D:\wanqing\projects\rectg
```

## 技术栈

- Python 3.13+
- SQLite
- requests
- beautifulsoup4
- lxml
- opencc-python-reimplemented
- emoji
- Markdown
- Node.js
- npm
- Astro
- pinyin-match
- @vercel/analytics
- @vercel/speed-insights

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
│   ├── package.json
│   └── package-lock.json
├── package.json
├── requirements.txt
├── README.md
└── vercel.json
```

## 激活虚拟环境

```powershell
cd D:\wanqing\projects\rectg
.\.venv\Scripts\Activate.ps1
```

验证依赖：

```powershell
python -c "import sys, requests, bs4, lxml; print(sys.executable); print('OK')"
```

## 安装依赖

```powershell
cd D:\wanqing\projects\rectg
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd D:\wanqing\projects\rectg\web
npm install
```

## 数据流程

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

README 不再作为主数据源。

## 数据库表

### links

保存待抓取的 Telegram 链接。

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

保存已抓取、已整理的频道/群组数据。

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

### ads

保存广告位数据。

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

`export_frontend_data.py` 也会自动确保 `ads` 表存在。

## 构建

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

## 添加频道/群组

```powershell
python scripts\add_entry.py https://t.me/your_username --type channel
python scripts\add_entry.py your_group_username --type group
python scripts\add_entry.py your_username --type channel --crawl
python scripts\add_entry.py your_username --keep
```

## 抓取

```powershell
python scripts\crawl.py --new --no-active
python scripts\crawl.py --limit 5 --no-active
```

## 清洗和自动分类

```powershell
python scripts\categorize.py
```

## 手动编辑分类

```powershell
python scripts\edit_category.py stats
python scripts\edit_category.py categories
python scripts\edit_category.py get your_username
python scripts\edit_category.py set your_username "💻 数码科技"
python scripts\edit_category.py list --uncategorized --limit 30
```

修改后：

```powershell
python scripts\export_frontend_data.py
npm run build
```

## 手动编辑状态

查看：

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

## 广告位管理

初始化：

```powershell
python scripts\manage_ads.py init
```

新增广告：

```powershell
python scripts\manage_ads.py add home_top "首页顶部广告" --url "https://example.com" --description "广告说明"
```

查看广告：

```powershell
python scripts\manage_ads.py list
python scripts\manage_ads.py list --all
```

更新广告：

```powershell
python scripts\manage_ads.py update 1 --title "新标题" --sort-order 10
```

启用 / 禁用：

```powershell
python scripts\manage_ads.py disable 1
python scripts\manage_ads.py enable 1
```

删除：

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

当前前端如果暂时不读取 `ads` 字段，不影响原有 `categories` 和 `types`。

## 推荐维护流程

### 添加一个新频道

```powershell
python scripts\add_entry.py your_username --type channel --crawl
python scripts\categorize.py
python scripts\export_frontend_data.py
npm run build
```

### 调整分类

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

## Git 工作流

```powershell
git status --short
git add README.md scripts/edit_category.py scripts/edit_status.py scripts/manage_ads.py scripts/export_frontend_data.py data/rectg.db web/public/data.json web/public/sitemap.xml web/public/robots.txt
git commit -m "Add category status and ads management"
git push
```

## 后续路线

完成分类编辑、状态管理、README 同步、广告表之后，下一步进入 Telegram 搜索 Bot：

```text
用户输入关键词
    ↓
Bot 查询 SQLite entries
    ↓
返回频道/群组标题、简介、人数、链接
    ↓
后续支持分页、分类筛选和广告插入
```
