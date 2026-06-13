# TG 索引

TG 索引是一个基于 SQLite、Python 数据处理脚本和 Astro 前端的 Telegram 中文频道、群组、机器人导航项目。

当前维护仓库：
https://github.com/wanqingyyfs-ui/tg_suoyin

历史名称：rectg。主数据库文件名暂时保留为 data/rectg.db。

## 当前状态

项目当前使用 SQLite 作为长期维护源，不再把 README 当作主数据源。

当前前端导出结果为 5 个一级分类：

- 📰 资讯内容
- 💻 技术资源
- 🎬 影音娱乐
- 👥 生活社群
- 🧭 工具导航

当前过滤阈值：

- 频道最低订阅数：1000
- 群组最低成员数：200
- 频道不活跃阈值：90 天
- 繁体中文过滤阈值：0.10

当前数据规模以最新生成的 web/public/data.json 为准。

## 数据链路

data/rectg.db -> scripts/categorize.py -> scripts/export_frontend_data.py -> web/public/data.json、web/public/sitemap.xml、web/public/robots.txt -> Astro build -> Vercel 静态部署。

配套采集器项目数据链路：

tg_suoyin_collector/exports/tg_suoyin_links.jsonl -> scripts/import_collected_links.py -> links 表 -> scripts/crawl.py --new -> entries 表 -> npm run rebuild。

## 常用命令

安装依赖：

python -m pip install -r requirements.txt
npm install

重新清洗、分类和过滤：

python scripts/categorize.py

导出前端数据：

npm run export

构建前端：

npm run build

从采集器导入候选链接：

python scripts/import_collected_links.py --file ../tg_suoyin_collector/exports/tg_suoyin_links.jsonl
npm run import-collected -- --file ../tg_suoyin_collector/exports/tg_suoyin_links.jsonl

导入采集器数据后的推荐流程：

python scripts/crawl.py --new
npm run rebuild
npm run build

搜索数据库：

python scripts/search_entries.py 科技 --limit 10
python scripts/search_entries.py 影视 --type channel
python scripts/search_entries.py 网盘 --format json

## 主要文件

- data/rectg.db：主数据库
- scripts/categories.py：分类顺序和 5 大类映射
- scripts/categorize.py：清洗、过滤和细分类
- scripts/filter_rules.py：过滤规则
- scripts/export_frontend_data.py：导出前端数据、站点地图和 robots.txt
- scripts/import_collected_links.py：导入 tg_suoyin_collector 审核通过的候选链接
- scripts/search_entries.py：命令行搜索工具
- scripts/manage_ads.py：广告位管理
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
7. 采集器只导入 links 表，最终展示仍必须经过 crawl、filter、categorize、export 流程。
