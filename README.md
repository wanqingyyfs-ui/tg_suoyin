# rectg

一个基于 SQLite、Python 爬虫和 Astro 前端的 Telegram 中文频道/群组搜索引擎项目。

本项目当前目标不是维护一份静态 README 资源清单，而是构建一个可以长期维护、持续收录、方便搜索、后续可接入 Telegram Bot、广告位和后台管理的 Telegram 中文资源数据库。

## 项目定位

rectg 用于收录、维护和展示 Telegram 中文频道与群组。

当前核心能力：

- 维护 Telegram 频道/群组链接
- 抓取 Telegram 公开页面信息
- 保存频道/群组基础数据到 SQLite
- 根据规则过滤无效、私密、不适合展示的数据
- 从 SQLite 导出前端搜索数据
- 使用 Astro 构建静态搜索站点
- 为后续 Bot、后台管理、广告系统打基础

## 当前状态

已完成：

- GitHub 项目已下载到本地
- Python 虚拟环境已创建
- Python 依赖已安装
- 前端依赖已安装
- `scripts/parse_links.py` 已修复
- README 表格链接可以解析进数据库
- SQLite 数据库已作为长期维护源
- Telegram 公开页面爬虫已验证可用
- 过滤规则已放宽
- 已新增 SQLite 导出前端数据脚本
- 根目录已支持统一构建命令
- 本地修改已同步到自己的 GitHub 仓库

当前长期数据流程：

```text
data/rectg.db
    ↓
scripts/export_frontend_data.py
    ↓
web/public/data.json
    ↓
Astro 前端展示和搜索
```

## 技术栈

### 后端 / 数据处理

- Python 3.13+
- SQLite
- requests
- beautifulsoup4
- lxml
- opencc-python-reimplemented
- emoji
- Markdown

### 前端

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
│   ├── crawl.py
│   ├── export_frontend_data.py
│   ├── filter_rules.py
│   └── parse_links.py
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

## 本地项目位置

```text
D:\wanqing\projects\rectg
```

## Python 虚拟环境

虚拟环境位置：

```text
D:\wanqing\projects\rectg\.venv
```

激活方式：

```powershell
cd D:\wanqing\projects\rectg
.\.venv\Scripts\Activate.ps1
```

## 安装依赖

### 安装 Python 依赖

```powershell
cd D:\wanqing\projects\rectg
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 安装前端依赖

```powershell
cd D:\wanqing\projects\rectg\web
npm install
```

## 常用命令

### 启动前端开发服务

```powershell
cd D:\wanqing\projects\rectg\web
npm run dev
```

### 从 SQLite 导出前端数据

```powershell
cd D:\wanqing\projects\rectg
python scripts\export_frontend_data.py
```

执行成功后会生成或更新：

```text
web/public/data.json
web/public/sitemap.xml
web/public/robots.txt
```

### 构建正式站点

在项目根目录执行：

```powershell
cd D:\wanqing\projects\rectg
npm run build
```

根目录 `package.json` 的构建命令会进入 `web` 目录：

```json
{
  "build": "cd web && npm run build"
}
```

`web/package.json` 的构建命令会先导出 SQLite 数据，再执行 Astro 构建：

```json
{
  "build": "python ../scripts/export_frontend_data.py && astro build"
}
```

也就是说，执行：

```powershell
npm run build
```

会自动完成：

```text
SQLite 数据库
    ↓
导出 web/public/data.json
    ↓
生成 sitemap.xml
    ↓
生成 robots.txt
    ↓
Astro build
```

### 预览正式构建

```powershell
cd D:\wanqing\projects\rectg\web
npm run preview
```

如果默认端口被占用：

```powershell
npm run preview -- --port 4322
```

## 数据库说明

主数据库：

```text
data/rectg.db
```

当前长期维护应以 SQLite 为主。

README 不再作为主数据源。

当前主要数据表：

### links

用于保存待抓取的 Telegram 链接。

常见字段：

- `url`
- `username`
- `name`
- `type_hint`
- `created_at`
- `updated_at`

### entries

用于保存已抓取、已整理的频道/群组数据。

常见字段：

- `title`
- `username`
- `url`
- `type`
- `count`
- `description`
- `clean_desc`
- `category`
- `valid`
- `private`
- `keep`
- `filter_reason`

## 前端数据导出规则

`scripts/export_frontend_data.py` 会从 `data/rectg.db` 读取满足以下条件的数据：

```sql
keep = 1
AND valid = 1
AND private = 0
```

然后导出到：

```text
web/public/data.json
```

同时生成：

```text
web/public/sitemap.xml
web/public/robots.txt
```

前端 Astro 项目通过 `web/public/data.json` 展示和搜索数据。

## 爬虫说明

### 测试抓取

```powershell
cd D:\wanqing\projects\rectg
python scripts\crawl.py --limit 5 --no-active
```

### 抓取新链接

```powershell
cd D:\wanqing\projects\rectg
python scripts\crawl.py --new --no-active
```

`--new` 表示抓取 links 表中尚未抓取或需要新增处理的链接。

`--no-active` 表示不额外检测活跃状态，适合当前开发阶段快速抓取。

## 过滤规则

过滤规则文件：

```text
scripts/filter_rules.py
```

当前已放宽门槛，适合自建 Telegram 搜索数据库：

```python
MIN_CHANNEL_SUBSCRIBERS = 1
MIN_GROUP_MEMBERS = 1
```

这样小频道、小群组也可以被收录和展示。

当前过滤逻辑会排除：

- 无效链接
- 私密频道/群组
- 无法识别类型的数据
- 非中文内容
- 繁体中文内容
- 命中高风险关键词的数据
- 订阅数或成员数低于门槛的数据
- 长期不活跃频道

## 手动添加频道/群组流程

当前临时流程如下。

后续会开发 `scripts/add_entry.py`，把下面流程封装成一个管理脚本。

### 1. 写入 links 表

```powershell
cd D:\wanqing\projects\rectg

@'
import sqlite3
from datetime import datetime

name = "频道名称"
url = "https://t.me/your_username"
username = url.rstrip("/").split("/")[-1]
now = datetime.now().isoformat(timespec="seconds")

conn = sqlite3.connect("data/rectg.db")
cur = conn.cursor()

cur.execute("""
INSERT OR IGNORE INTO links (
    url,
    username,
    name,
    type_hint,
    created_at,
    updated_at
)
VALUES (?, ?, ?, ?, ?, ?)
""", (
    url,
    username,
    name,
    None,
    now,
    now
))

conn.commit()
print("本次影响行数：", cur.rowcount)
conn.close()
'@ | python
```

### 2. 抓取新链接

```powershell
python scripts\crawl.py --new --no-active
```

### 3. 如果被过滤，手动放行

```powershell
@'
import sqlite3

username = "your_username"

conn = sqlite3.connect("data/rectg.db")
cur = conn.cursor()

cur.execute("""
UPDATE entries
SET keep = 1,
    filter_reason = ''
WHERE username = ?
""", (username,))

conn.commit()
print("本次影响行数：", cur.rowcount)
conn.close()
'@ | python
```

### 4. 重新构建

```powershell
npm run build
```

### 5. 预览

```powershell
cd web
npm run preview
```

## Git 工作流

### 查看状态

```powershell
git status
```

### 添加修改

```powershell
git add .
```

### 提交修改

```powershell
git commit -m "Describe your change"
```

### 推送到 GitHub

```powershell
git push
```

## GitHub 仓库

当前维护仓库：

```text
https://github.com/wanqingyyfs-ui/rectg
```

当前仓库是基于原 rectg 项目继续开发。

## .gitignore 规则

不建议提交：

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
```

当前建议继续提交：

```text
data/rectg.db
web/public/data.json
web/public/sitemap.xml
web/public/robots.txt
```

原因：

- `data/rectg.db` 是当前长期维护源
- `web/public/data.json` 是前端静态搜索数据
- `sitemap.xml` 和 `robots.txt` 当前由导出脚本生成，前端构建需要使用

后续如果改成 CI/CD 自动生成，可以再考虑把生成文件从 Git 追踪中移除。

## 后续开发计划

### 1. 添加频道/群组管理脚本

建议文件：

```text
scripts/add_entry.py
```

目标：

- 输入 Telegram 链接或 username
- 自动标准化为 `https://t.me/username`
- 自动提取 username
- 自动写入 `links` 表
- 自动避免重复插入
- 可选择调用爬虫抓取
- 自动检查 `entries` 表是否生成
- 可选择设置 `keep = 1`
- 最后提示执行 `npm run build`

### 2. 分类编辑功能

建议文件：

```text
scripts/edit_category.py
```

目标：

- 按 username 修改分类
- 批量调整分类
- 查看当前所有分类统计
- 查看未分类数据
- 支持导出后重新构建

### 3. 广告位数据库表

建议新增表：

```text
ads
```

目标字段：

- `id`
- `position`
- `title`
- `description`
- `url`
- `image_url`
- `sort_order`
- `enabled`
- `created_at`
- `updated_at`

后续前端可读取广告数据并展示在：

- 首页顶部
- 搜索结果中间
- 分类页顶部
- 详情页底部

### 4. Telegram 搜索 Bot

目标：

- 用户输入关键词
- Bot 从 SQLite 搜索 `entries`
- 返回频道/群组标题、简介、人数、链接
- 支持分页
- 支持分类筛选
- 后续支持广告插入

### 5. 后台管理页面

目标：

- 管理频道/群组
- 管理分类
- 管理广告
- 管理 `keep`
- 管理 `valid`
- 管理 `private`
- 查看抓取失败原因
- 支持批量编辑
- 支持重新导出前端数据

### 6. 部署

可选方向：

- Vercel
- Cloudflare Pages
- 自有服务器
- GitHub Actions 自动构建

部署前需要确认：

- 构建环境可以执行 Python
- `scripts/export_frontend_data.py` 可以正常运行
- `data/rectg.db` 是否随仓库发布
- 是否需要在部署阶段自动生成 `data.json`
- 是否需要隐藏部分数据库内容

## 开发原则

本项目后续开发遵循以下原则：

- SQLite 是长期维护源
- README 不再作为主数据源
- 前端只消费导出的 `data.json`
- 脚本优先保持简单、稳定、可读
- 每次新增功能先做最小可用版本
- 不随意删除已有代码
- 删除任何已有代码前必须说明理由
- 修改数据库结构前先备份
- 所有自动化脚本都要有明确输出
- 优先保证本地可运行，再考虑自动化部署
- 优先做能马上提升维护效率的功能

## 当前优先任务

下一步优先开发：

```text
scripts/add_entry.py
```

也就是“添加频道/群组”的管理脚本。

最小可用版本应该先做到：

1. 输入 Telegram 链接或 username
2. 标准化链接
3. 写入 `links` 表
4. 避免重复插入
5. 输出清楚的执行结果

后续再逐步增加：

1. 自动调用爬虫
2. 自动查询 entries 表
3. 自动放行 keep
4. 自动导出前端数据
5. 自动构建前端

## 免责声明

本项目仅整理 Telegram 公开频道与群组信息，用于导航、搜索和研究参考。

项目不对第三方频道/群组中的内容负责。

使用者应自行判断信息真实性，并遵守所在地法律法规。

如有侵权、失效、错误收录或不希望展示，请联系维护者处理。

## License

本项目基于原 rectg 项目继续开发，保留原项目 License。

后续新增代码、数据维护规则和项目说明以本仓库 README 为准。