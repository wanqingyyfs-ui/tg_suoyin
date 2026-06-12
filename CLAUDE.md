# rectg 项目工作规则

## 项目简介

**rectg** - Telegram 中文频道/群组搜索引擎

- **后端**: Python 3.13 + SQLite
- **前端**: Astro 5.x + Node.js
- **数据源**: Telegram 公开页面爬虫
- **核心数据**: `data/rectg.db` (SQLite)
- **部署**: 静态站点（Vercel/Cloudflare Pages）

**数据流程**: SQLite → export_frontend_data.py → data.json → Astro 构建 → 静态站点

**环境配置**: 项目支持通过 `.env` 文件或环境变量配置站点域名等参数，确保灵活性

---

## 核心目录

```
rectg/
├── data/rectg.db              # 主数据库（核心资产，禁止删除）
├── scripts/                   # Python 脚本工具
│   ├── crawl.py              # 数据爬取
│   ├── categorize.py         # 自动分类
│   ├── edit_category.py      # 分类管理
│   ├── edit_status.py        # 状态管理
│   ├── manage_ads.py         # 广告管理
│   ├── export_frontend_data.py  # 导出前端数据
│   ├── search_entries.py     # 搜索核心
│   ├── bot.py                # Telegram Bot
│   └── admin_server.py       # 后台服务
├── web/                       # Astro 前端
│   ├── src/pages/index.astro # 首页
│   ├── src/pages/p/[id].astro # 详情页
│   └── public/data.json      # 前端数据（从 SQLite 导出）
└── .venv/                     # Python 虚拟环境
```

---

## 常用命令

### 环境配置
```powershell
# 首次使用：复制环境变量示例
cp .env.example .env
# 编辑 .env 填写实际配置（如 TELEGRAM_BOT_TOKEN）

# 自定义站点域名（可选）
# 在 .env 中添加: SITE_URL=https://your-domain.com
```

### Python 环境
```powershell
# 激活虚拟环境（必须先执行）
.\.venv\Scripts\Activate.ps1
```

### 数据管理
```powershell
# 添加新频道
python scripts\add_entry.py username --type channel --crawl

# 爬取数据
python scripts\crawl.py --new --no-active

# 自动分类
python scripts\categorize.py

# 编辑分类
python scripts\edit_category.py get username
python scripts\edit_category.py set username "💻 数码科技"

# 编辑状态
python scripts\edit_status.py get username
python scripts\edit_status.py set username --keep 1 --valid 1 --private 0 --clear-reason

# 导出前端数据
python scripts\export_frontend_data.py
```

### 前端开发
```powershell
# 开发模式（热更新）
cd web
npm run dev   # 访问 http://localhost:4321

# 生产构建
npm run build  # 从根目录执行，自动导出数据并构建
```

### 启动服务
```powershell
# Bot（脚本会自动定位项目目录）
.\run_bot.ps1  # 或 python scripts\bot.py

# 后台管理（脚本会自动定位项目目录）
.\run_admin.ps1  # 或 python scripts\admin_server.py
```

---

## 安全规则（严格执行）

### 数据库保护
- ⛔ **禁止删除** `data/rectg.db`
- ⛔ **禁止直接修改** 数据库文件
- ✅ **必须使用** scripts 脚本操作数据库
- ✅ **操作前备份**:
  ```powershell
  cp data/rectg.db data/rectg.db.backup
  ```

### 敏感信息保护
- ⛔ **禁止修改** `.env` 文件中的 Token/API Key
- ⛔ **禁止提交** `.env` 到 Git（`.env.example` 可以提交）
- ⛔ **禁止打印** 敏感信息到日志
- ✅ **首次使用**: 复制 `.env.example` 为 `.env` 并填写配置

### 文件扫描限制
- ⛔ **禁止扫描** 以下目录（性能和安全）:
  - `node_modules/`
  - `.venv/`
  - `web/node_modules/`
  - `web/dist/`
  - `.git/`
  - `.astro/`
- ✅ 使用 Glob/Grep 时指定具体路径

---

## 协作规则

### 代码修改原则
1. **先读后写**: 修改文件前必须先用 Read 工具读取
2. **增量修改**: 优先使用 Edit 工具，避免全文重写
3. **测试验证**: 修改后必须测试验证
4. **说明改动**: 每次修改后列出改动文件和内容

### 修改前确认
- 修改数据库结构前询问用户
- 删除文件前询问用户
- 破坏性操作前询问用户（`git reset --hard`, `rm -rf` 等）

### Git 提交规范
```powershell
# 不提交的文件（已在 .gitignore）
- .venv/
- node_modules/
- web/dist/
- .env (但 .env.example 可提交)
- *.log
- *.backup

# 推荐提交（启动脚本已从 .gitignore 移除）
git add data/rectg.db scripts/ web/src/ web/public/data.json run_*.ps1
git commit -m "描述改动"
git push
```

---

## 配置管理

### 域名配置
项目中的站点域名通过环境变量配置，避免硬编码：

```bash
# 方式 1: .env 文件（推荐）
SITE_URL=https://your-domain.com

# 方式 2: 构建时环境变量
export SITE_URL=https://your-domain.com
npm run build
```

**影响范围**:
- SEO sitemap 和 robots.txt
- Open Graph 图片链接
- Schema.org 结构化数据

**默认值**: `https://www.rectg.com`

---

## 快速参考

### 完整维护流程
```powershell
# 1. 添加新频道并爬取
python scripts\add_entry.py username --type channel --crawl

# 2. 自动分类
python scripts\categorize.py

# 3. 检查并调整分类（可选）
python scripts\edit_category.py get username
python scripts\edit_category.py set username "分类名"

# 4. 导出并构建
python scripts\export_frontend_data.py
npm run build

# 5. 提交
git add data/rectg.db web/public/data.json
git commit -m "Add new channel"
git push
```

### 故障排查
- Python 模块找不到 → 检查是否激活虚拟环境
- npm 命令失败 → `cd web && npm install`
- 前端数据不更新 → 运行 `python scripts\export_frontend_data.py`
- 数据库损坏 → 从 `data/rectg.db.backup` 恢复

### 数据库查询（只读）
```powershell
# 统计总数
python -c "import sqlite3; print(sqlite3.connect('data/rectg.db').execute('SELECT COUNT(*) FROM entries').fetchone()[0])"

# 查看分类统计
python scripts\edit_category.py stats
```

---

## 默认行为

- **语言**: 默认中文回复
- **权限**: 破坏性操作前必须询问
- **日志**: 重要操作后输出清晰的结果摘要
