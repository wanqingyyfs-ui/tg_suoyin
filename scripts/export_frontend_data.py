from pathlib import Path
import json
import os
import re
import sqlite3
import xml.sax.saxutils as xml_escape

from categories import CATEGORY_ORDER, get_top_category, normalize_entry_category, top_category_sort_key

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "rectg.db"
OUT_DIR = ROOT / "web" / "public"
OUT_FILE = OUT_DIR / "data.json"
SITEMAP_FILE = OUT_DIR / "sitemap.xml"
ROBOTS_FILE = OUT_DIR / "robots.txt"

SITE_URL = os.environ.get("SITE_URL", "https://tg-suoyin.vercel.app").rstrip("/")

TYPE_LABELS = {
    "channel": "频道",
    "group": "群组",
    "bot": "机器人",
}

SEO_KEYWORDS = {
    "新闻政经": "新闻 快讯 时事 政经 国际 社会 媒体 热点 舆论",
    "科技AI": "AI 科技 数码 编程 开发 开源 GitHub Python Linux Docker ChatGPT OpenAI",
    "软件工具": "软件 工具 App 插件 脚本 自动化 浏览器 效率 下载器 客户端",
    "影视音乐": "电影 电视剧 纪录片 音乐 播客 音频 有声书 网盘影视 4K",
    "游戏动漫": "游戏 手游 Steam 电竞 动漫 漫画 二次元 ACG 番剧 主机",
    "学习知识": "学习 课程 教程 电子书 资料 语言 考试 论文 知识库 设计 摄影",
    "商业职场": "招聘 求职 创业 运营 职场 远程工作 自由职业 副业 项目合作",
    "财经投资": "财经 股票 基金 理财 宏观经济 房产投资 外汇 投资研究",
    "加密Web3": "加密货币 区块链 比特币 以太坊 Web3 NFT DeFi 交易所 钱包",
    "博彩资源": "博彩 彩票 赌场 体育竞猜 棋牌 บาคาร่า 盘口 赔率 投注",
    "成人资源": "成人 色情 福利 写真 番号 擦边 NSFW R18 成人社群",
    "灰产资源": "灰产 接码 养号 账号资源 引流 矩阵 私域 流量变现 渠道",
    "军事安全": "军事 国防 武器 装备 战争 地缘冲突 军迷 战报 安全局势",
    "健康运动": "健康 医疗 健身 减脂 运动 体育 心理 养生 营养",
    "生活消费": "生活 美食 购物 优惠 穿搭 宠物 母婴 旅游 吃喝玩乐",
    "地区本地": "同城 本地 海外华人 城市 国家 地区 金边 柬埔寨 日本 香港",
    "兴趣社群": "交友 闲聊 情感 树洞 同好 摄影 车友 爱好者 社群",
    "人文社会": "历史 文化 哲学 宗教 法律 艺术 文学 社会议题 人文社科",
    "汽车交通": "汽车 摩托 二手车 车友 交通 物流 出行 货运 改装",
    "电商交易": "电商 货源 批发 代购 二手交易 供需 买卖 跨境电商",
    "房产家居": "房产 租房 买房 装修 家居 建材 物业 公寓 地产",
    "营销广告": "广告 推广 投放 营销 SEO 私域 流量 渠道 代理 广告位",
    "机器人服务": "Telegram 机器人 Bot 自动回复 搜索机器人 下载机器人 翻译机器人 客服机器人",
    "综合导航": "Telegram 索引 导航 目录 搜群 频道大全 群组大全 合集 入口",
}

EXPECTED_CATEGORY_SET = set(CATEGORY_ORDER)


def normalize_export_category(category: str | None, entry_type: str) -> str:
    normalized = normalize_entry_category(category, entry_type)
    if normalized in EXPECTED_CATEGORY_SET:
        return normalized
    return normalize_entry_category(None, entry_type)


def make_id(username, url, title):
    raw = username or ""
    if not raw and url and "t.me/" in url:
        raw = url.split("t.me/", 1)[1].replace("joinchat/", "").split("?", 1)[0]
    if not raw:
        raw = title or ""
    raw = raw.strip().lower()
    raw = re.sub(r"[^a-zA-Z0-9_\-\u4e00-\u9fa5]", "", raw)
    return raw or "item"


def split_category(full_name):
    full_name = (full_name or "").strip()
    match = re.match(r"^(\S+)\s+(.*)$", full_name)
    if match:
        icon, name = match.group(1), match.group(2).strip()
    else:
        icon, name = "", full_name
    return {
        "icon": icon,
        "name": name,
        "fullName": full_name,
        "keywords": SEO_KEYWORDS.get(name, ""),
        "id": name.lower(),
    }


def init_ads_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            position        TEXT NOT NULL,
            title           TEXT NOT NULL,
            description     TEXT,
            url             TEXT NOT NULL,
            image_url       TEXT,
            sort_order      INTEGER DEFAULT 0,
            enabled         INTEGER DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ads_position_enabled_sort
        ON ads(position, enabled, sort_order, id)
        """
    )
    conn.commit()


def load_ads(cur: sqlite3.Cursor) -> dict:
    rows = cur.execute(
        """
        SELECT id, position, title, description, url, image_url, sort_order
        FROM ads
        WHERE enabled = 1
        ORDER BY position COLLATE NOCASE, sort_order ASC, id ASC
        """
    ).fetchall()

    items = []
    positions = {}

    for row in rows:
        item = {
            "id": row["id"],
            "position": row["position"],
            "title": row["title"],
            "description": row["description"] or "",
            "url": row["url"],
            "imageUrl": row["image_url"] or "",
            "sortOrder": row["sort_order"] or 0,
        }
        items.append(item)
        positions.setdefault(row["position"], []).append(item)

    return {
        "items": items,
        "positions": positions,
    }


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"数据库不存在：{DB_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    init_ads_table(conn)

    rows = cur.execute(
        """
        SELECT title, username, url, type, count, clean_desc, description, category
        FROM entries
        WHERE keep = 1
          AND valid = 1
          AND private = 0
        ORDER BY
            CASE type
                WHEN 'channel' THEN 1
                WHEN 'group' THEN 2
                WHEN 'bot' THEN 3
                ELSE 4
            END,
            COALESCE(category, ''),
            COALESCE(count, 0) DESC,
            title COLLATE NOCASE
        """
    ).fetchall()

    ads = load_ads(cur)
    conn.close()

    type_map = {}
    category_seen = {}

    for row in rows:
        entry_type = row["type"] or "channel"
        type_label = TYPE_LABELS.get(entry_type, entry_type)
        fine_category = normalize_export_category(row["category"], entry_type)
        top_category = get_top_category(fine_category)
        title = row["title"] or row["username"] or row["url"] or "未命名"
        url = row["url"] or f"https://t.me/{row['username']}"
        count = row["count"] or 0
        desc = row["clean_desc"] or row["description"] or ""

        item = {
            "title": title,
            "url": url,
            "countStr": f"{count:,}",
            "desc": desc,
            "id": make_id(row["username"], url, title),
            "fineCategory": fine_category,
        }

        type_map.setdefault(type_label, {})
        type_map[type_label].setdefault(top_category, [])
        type_map[type_label][top_category].append(item)
        category_seen[top_category] = split_category(top_category)

    categories = [category_seen[name] for name in sorted(category_seen.keys(), key=top_category_sort_key)]

    types = []
    for type_label in ["频道", "群组", "机器人"]:
        if type_label not in type_map:
            continue
        categories_for_type = []
        for category in sorted(type_map[type_label].keys(), key=top_category_sort_key):
            items = type_map[type_label][category]
            if items:
                categories_for_type.append({
                    "fullName": category,
                    "items": items,
                })
        if categories_for_type:
            types.append({
                "name": type_label,
                "categories": categories_for_type,
            })

    data = {
        "categories": categories,
        "types": types,
        "ads": ads,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    sitemap_urls = [f"<url><loc>{xml_escape.escape(SITE_URL)}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>"]
    seen_ids = set()
    for type_block in types:
        for category_block in type_block["categories"]:
            for item in category_block["items"]:
                if not item["id"] or item["id"] in seen_ids:
                    continue
                seen_ids.add(item["id"])
                loc = f"{SITE_URL}/p/{item['id']}"
                sitemap_urls.append(
                    f"<url><loc>{xml_escape.escape(loc)}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>"
                )

    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    sitemap += "\n".join(sitemap_urls)
    sitemap += "\n</urlset>\n"

    SITEMAP_FILE.write_text(sitemap, encoding="utf-8")
    ROBOTS_FILE.write_text(
        f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n",
        encoding="utf-8",
    )

    print(f"✅ Generated data.json from SQLite: {OUT_FILE}")
    print(f"✅ Categories: {len(categories)}")
    print(f"✅ Types: {len(types)}")
    print(f"✅ Items: {sum(len(c['items']) for t in types for c in t['categories'])}")
    print(f"✅ Ads: {len(ads['items'])}")


if __name__ == "__main__":
    main()
