# TG 索引

TG 索引是一个基于 SQLite、Python 数据处理脚本和 Astro 前端的 Telegram 中文频道、群组、机器人导航项目。

当前维护仓库：
https://github.com/wanqingyyfs-ui/tg_suoyin

历史名称：rectg。主数据库文件名暂时保留为 data/rectg.db。

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
- scripts/categories.py：分类顺序、默认分类和历史分类归并规则
- scripts/categorize.py：文本清洗和 24 大类分类
- scripts/filter_rules.py：旧脚本兼容空壳，不再执行内容过滤
- scripts/export_frontend_data.py：导出前端数据、站点地图和 robots.txt
- scripts/import_collected_links.py：导入 tg_shaixuan 审核通过的候选链接
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
7. tg_suoyin 只做抓取、分类、搜索、展示，不做内容行业过滤。
8. tg_shaixuan 负责筛选、淘汰和审核；它输出给 tg_suoyin 的链接默认是可接受资源。
9. 新增分类时必须同步更新 scripts/categories.py、scripts/categorize.py、scripts/export_frontend_data.py。
