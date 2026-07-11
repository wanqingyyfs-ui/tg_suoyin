# TG 索引

TG 索引是一个基于 SQLite、Python 数据处理脚本和 Astro 前端的 Telegram 中文频道、群组、机器人导航项目。

当前维护仓库：
https://github.com/wanqingyyfs-ui/tg_suoyin

历史名称：rectg。主数据库文件名暂时保留为 data/rectg.db。

## 详细使用与交接文档

当前所有已实现功能、运行入口、Bot 行为、数据库结构、数据链路、控制中心、管理后台、前端构建、GitHub Actions、同步方式和故障排查统一记录在：

- [项目使用与交接说明](./项目使用说明.md)

新的开发对话或维护人员应先阅读该文档，再读取任务相关源码。

## 当前状态

项目当前使用 SQLite 作为长期维护源，不再把 README 当作主数据源。

当前分类体系为 24 个一级大类：

- 📰 新闻政经
- 💻 科技AI
- 🧰 软件工具
- 🎬 影视音乐
- 🎮 游戏动漫
- 📚 学习知识
- 💼 商业职场
- 💰 财经投资
- 💎 加密Web3
- 🎲 博彩资源
- 🔞 成人资源
- 🩶 灰产资源
- 🛡️ 军事安全
- 🏥 健康运动
- 🏠 生活消费
- 🌍 地区本地
- 👥 兴趣社群
- 🏛️ 人文社会
- 🚗 汽车交通
- 🛒 电商交易
- 🏘️ 房产家居
- 📢 营销广告
- 🤖 机器人服务
- 🧭 综合导航

说明：tg_shaixuan 负责前置筛选链接；tg_suoyin 只负责对已接受的公开 Telegram 资源进行抓取、分类、清洗、搜索和展示。tg_suoyin 不按内容行业做过滤，不再因为成人、博彩、灰产、政治、宗教等通用词删除或隐藏资源。

当前数据规模以最新生成的 web/public/data.json 为准。

## 数据链路

data/rectg.db -> scripts/categorize.py -> scripts/export_frontend_data.py -> web/public/data.json、web/public/sitemap.xml、web/public/robots.txt -> Astro build -> Vercel 静态部署。

配套筛选器项目数据链路：

tg_shaixuan 导出文件 -> scripts/import_collected_links.py -> links 表 -> scripts/crawl.py --new -> entries 表 -> npm run rebuild。

## 当前运行入口

- Telegram Bot：`python bot.py poll` 或 `./run_bot.ps1`
- Windows 控制中心：双击 `TG-Suoyin-Control-Center.exe`，源码方式为 `python -m control_center`
- 完整浏览器管理后台：`python scripts/admin_dashboard.py` 或 `npm run admin`
- 前端开发：`npm run dev`
- 先导出再构建前端：`npm run frontend:prepare`

Bot 唯一公开入口是根目录 `bot.py`；`bot_core.py` 是底层模块；旧的 `scripts/bot.py` 已删除。

## 常用命令

安装依赖：

python -m pip install -r requirements.txt
npm install

重新清洗和分类：

python scripts/categorize.py

导出前端数据：

npm run export

一键重整数据库分类并重新导出前端数据：

npm run rebuild

构建前端：

npm run build

从筛选器导入候选链接：

python scripts/import_collected_links.py --file ../tg_shaixuan/exports/tg_suoyin_links.jsonl
npm run import-collected -- --file ../tg_shaixuan/exports/tg_suoyin_links.jsonl

导入筛选器数据后的推荐流程：

python scripts/crawl.py --new
npm run rebuild
npm run build

搜索数据库：

python scripts/search_entries.py 科技 --limit 10
python scripts/search_entries.py 影视 --type channel
python scripts/search_entries.py 网盘 --format json

## 主要文件

- data/rectg.db：主数据库
- bot.py：Telegram Bot 唯一公开入口和搜索交互层
- bot_core.py：Bot polling、Webhook、消息索引和媒体处理底层
- scripts/bot_api_client.py：Telegram Bot API 客户端
- scripts/categories.py：分类顺序、默认分类和历史分类归并规则
- scripts/categorize.py：文本清洗和 24 大类分类
- scripts/filter_rules.py：旧脚本兼容空壳，不再执行内容过滤
- scripts/export_frontend_data.py：导出前端数据、站点地图和 robots.txt
- scripts/import_collected_links.py：导入 tg_shaixuan 审核通过的候选链接
- scripts/search_entries.py：命令行搜索工具
- scripts/message_indexer.py：消息锚点索引和监听数据结构
- scripts/admin_dashboard.py：当前完整浏览器管理后台
- scripts/manage_ads.py：广告位管理
- control_center/：Windows 桌面控制中心源码
- web/src：Astro 前端源码
- web/public/data.json：前端静态数据
- web/public/sitemap.xml：站点地图

## 维护原则

1. 不恢复 README 数据源。
2. 不恢复 web/build-data.js。
3. 不混用旧仓库 wanqingyyfs-ui/rectg。
4. 不写死 https://www.rectg.com。
5. 分类常量统一由 scripts/categories.py 管理。
6. 部署前必须确认 data.json 和 sitemap.xml 已由最新数据库重新生成。
7. tg_suoyin 只做抓取、分类、搜索、展示，不做内容行业过滤。
8. tg_shaixuan 负责筛选、淘汰和审核；它输出给 tg_suoyin 的链接默认是可接受资源。
9. Bot 统一从根目录 bot.py 启动，不恢复 scripts/bot.py。
10. 详细当前行为以项目使用说明.md和实际代码为准。