# TG 索引项目协作与交接规则

> 本文件给代码助手和后续开发对话使用。完整项目功能、入口、数据流、命令和故障排查见：[`项目使用说明.md`](./项目使用说明.md)。
>
> 当前仓库：`wanqingyyfs-ui/tg_suoyin`  
> Windows 本地路径：`D:\编程\tg_suoyin`  
> 历史名称：`rectg`，数据库文件名仍为 `data/rectg.db`。

## 1. 接手任务的固定顺序

先执行：

```powershell
cd "D:\编程\tg_suoyin"
git status
git log -5 --oneline
git remote -v
```

然后：

1. 阅读 `项目使用说明.md`。
2. 读取与任务直接相关的当前源码，不依赖历史对话中的旧文件结构。
3. 检查 `data/rectg.db`、`web/public/`、`web/dist/` 是否有本地运行修改。
4. 修改前建立可回滚分支；通过检查后用 PR 合并 `main`。
5. 只记录和实现当前明确要求，不把未来设想写进说明文档。

## 2. 项目定位

TG 索引是基于 SQLite、Python、Astro 和 Telegram Bot API 的公开 Telegram 资源索引项目，当前包括：

- 候选链接导入；
- Telegram 公开页面抓取；
- 24 个一级大类清洗和分类；
- SQLite 资源搜索；
- Astro 静态网站和详情页；
- Telegram Bot 资源/消息搜索、分页和消息锚点索引；
- 浏览器管理后台；
- PySide6 Windows 控制中心；
- 广告管理；
- GitHub Actions Windows EXE 与 `web/dist` 自动构建发布。

职责边界：`tg_shaixuan` 负责前置筛选和审核；`tg_suoyin` 负责已接受公开资源的抓取、分类、搜索和展示，不按行业关键词执行内容过滤。

## 3. 唯一数据源和分类源

主数据库：

```text
data/rectg.db
```

README 不是数据源，不恢复旧 `web/build-data.js` 数据链路。

当前分类标准唯一来源：

```text
scripts/categories.py
```

当前共有 24 个一级大类。`scripts/edit_category.py` 仍包含历史分类列表，不可把它当作当前分类标准；写入新分类时可能需要 `--allow-new`。

当前前端导出和资源搜索实际可见条件是：

```sql
valid = 1 AND private = 0
```

当前 `export_frontend_data.py` 和 `search_entries.py` 没有使用 `keep` 作为排除条件。

## 4. 当前入口

### Bot

唯一公开入口：

```text
bot.py
```

底层模块：

```text
bot_core.py
```

API 客户端：

```text
scripts/bot_api_client.py
```

已删除且禁止恢复：

```text
scripts/bot.py
```

启动：

```powershell
python bot.py poll
.\run_bot.ps1
```

不要把 `bot_core.py` 当成第二套独立 Bot。控制中心也必须运行根目录 `bot.py`。

### 完整浏览器后台

```powershell
python scripts\admin_dashboard.py
npm run admin
```

控制中心“后台”服务也运行 `admin_dashboard.py`。

`run_admin.ps1` 当前仍运行兼容后台 `scripts/admin_server.py`，其功能不包含完整消息监听管理。

### Windows 控制中心

```powershell
python -m control_center
npm run control
```

正式 EXE：

```text
TG-Suoyin-Control-Center.exe
```

### 前端

```powershell
npm run dev
npm run frontend:prepare
npm run build
```

注意：根目录 `npm run build` 当前只构建 Astro，不先导出数据库。需要先导出再构建时使用 `npm run frontend:prepare`。

## 5. Bot 当前固定行为

Bot 搜索交互位于 `bot.py`：

- 每页 14 条；
- 标题包含关键词和总结果数；
- 第二页从序号 15 开始；
- 结果保持“序号 + emoji + 可选媒体信息 + 20 字限长锚文本”；
- 只有六个按钮：`全部`、`群频`、`消息`、`最新`、`上一页`、`下一页`；
- `全部`：资源和消息综合搜索；
- `群频`：只含频道和群组；
- `消息`：只含消息索引；
- `最新`：保留当前模式并按时间优先；
- 私聊可直接发送关键词或 `/search`、`/s`；
- 群内只响应消息开头的 `@机器人用户名 关键词`；
- 普通群消息不自动回复，但已开启监听的频道/群组消息可以建立索引；
- callback 查询状态是内存缓存，Bot 重启后旧按钮可能失效；
- 同一个 Token 不能同时运行多个 polling 进程。

修改按钮、分页、结果格式、排序和筛选优先改 `bot.py`；修改 polling、webhook、媒体或底层索引流程再改 `bot_core.py`。

## 6. 数据链路

```text
tg_shaixuan 导出
  -> scripts/import_collected_links.py
  -> links
  -> scripts/crawl.py
  -> entries
  -> scripts/categorize.py / scripts/rebuild_index.py
  -> scripts/export_frontend_data.py
  -> web/public/data.json + sitemap.xml + robots.txt
  -> Astro build
  -> web/dist
```

消息链路：

```text
entries 开启监听
  -> bot.py 接收 update
  -> scripts/message_indexer.py
  -> message_index
  -> Bot“全部/消息”搜索和后台消息管理
```

`message_index` 不导出到静态网站。

## 7. 关键文件职责

| 需求 | 文件 |
|---|---|
| Bot 搜索按钮、分页、总数、排序 | `bot.py` |
| Bot polling、webhook、媒体、统计 | `bot_core.py` |
| Telegram API 请求 | `scripts/bot_api_client.py` |
| 消息索引和监听字段 | `scripts/message_indexer.py` |
| 监听 CLI | `scripts/manage_listeners.py` |
| 分类名称、顺序和旧分类归并 | `scripts/categories.py` |
| 分类规则 | `scripts/categorize.py` |
| 数据导出、SEO、广告导出 | `scripts/export_frontend_data.py` |
| 资源搜索 | `scripts/search_entries.py` |
| 爬虫 | `scripts/crawl.py` |
| 候选链接导入 | `scripts/import_collected_links.py` |
| 完整浏览器后台 | `scripts/admin_dashboard.py` |
| 控制中心 GUI | `control_center/app.py` |
| 控制中心环境、数据库、备份和服务 | `control_center/runtime.py` |
| 首页 | `web/src/pages/index.astro` |
| 详情页 | `web/src/pages/p/[id].astro` |
| Windows 构建 | `scripts/build_control_center.ps1`、`.github/workflows/build-control-center.yml` |

## 8. 安全规则

### 数据库

- 禁止删除 `data/rectg.db`。
- 破坏性数据库操作前必须备份到项目目录外或使用控制中心 SQLite Backup API。
- 不直接删除正在使用的 `-wal`、`-shm` 文件。
- `crawl.py --no-resume` 会清空 `entries`，必须先备份。
- 删除资源、清空消息索引、批量 SQL 更新前必须备份。

简单停机备份：

```powershell
Copy-Item data\rectg.db "D:\rectg-backup-$(Get-Date -Format yyyyMMdd-HHmmss).db"
```

### 敏感信息

- 不读取、输出、提交 `.env` 中的 Token 或 Secret。
- `.env` 不进入 Git，`.env.example` 可以提交。
- 不把敏感值写进日志、PR、Issue 或文档。

### 生成文件

当前 Git 跟踪：

- `data/rectg.db`
- `web/public/data.json`
- `web/public/sitemap.xml`
- `web/public/robots.txt`
- `web/dist/`
- `TG-Suoyin-Control-Center.exe`
- `CONTROL_CENTER_BUILD.txt`

运行后台、Bot、控制中心、导出或构建后出现修改可能是正常现象，但禁止未经审查执行：

```powershell
git add -A
```

先执行：

```powershell
git status --short
git diff --stat
```

大量 `web/dist/p/*/index.html` 删除通常表示当前数据库导出的资源集合变少，提交前必须核对数据库数量和备份。

## 9. 修改和提交规则

1. 先读后写。
2. 只修改与任务有关的文件。
3. 不在 `main` 上直接进行大改；建立功能分支和回滚分支。
4. 删除文件前确认没有入口或构建依赖。
5. 代码修改后执行对应语法、构建或运行测试。
6. 文档与实际代码冲突时，以代码为准，并同步修正文档。
7. 不提交 `.env`、日志、虚拟环境、依赖目录或数据库备份。
8. GitHub Actions 在源码合并 `main` 后可能自动追加：

```text
chore: publish Windows control center [skip ci]
```

该提交会更新正式 EXE、`CONTROL_CENTER_BUILD.txt` 和 `web/dist`，属于当前正常流程。

## 10. 最低验证

Python：

```powershell
python -m py_compile bot.py bot_core.py scripts\bot_api_client.py
python -m compileall -q control_center scripts
```

导出和前端：

```powershell
python scripts\export_frontend_data.py
npm --prefix web run build
```

Bot：

```powershell
python bot.py poll
```

至少检查：总数标题、六个按钮、14 条分页、第二页从 15 编号、模式切换、首页和末页提示、群内 mention 触发。

控制中心：

```powershell
python -m control_center
```

正式打包：

```powershell
.\scripts\build_control_center.ps1
```

## 11. 本地同步规则

工作区干净：

```powershell
git switch main
git pull --ff-only origin main
```

工作区有数据库或构建文件修改时，必须先在项目外备份数据库，再决定 stash、提交或放弃。不要对二进制数据库盲目 `stash pop` 或 `git reset --hard`。

完整命令、数据库结构、各项功能和故障排查以 `项目使用说明.md` 为准。