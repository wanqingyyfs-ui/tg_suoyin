from pathlib import Path
import json
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "rectg.db"
OUT_DIR = ROOT / "web" / "public"
OUT_FILE = OUT_DIR / "data.json"
SITEMAP_FILE = OUT_DIR / "sitemap.xml"
ROBOTS_FILE = OUT_DIR / "robots.txt"

TYPE_LABELS = {
    "channel": "频道",
    "group": "群组",
    "bot": "机器人",
}

DEFAULT_CATEGORY = {
    "channel": "🆕 新发现频道",
    "group": "🌐 综合其他",
    "bot": "🤖 机器人",
}

SEO_KEYWORDS = {
    "新闻快讯": "吃瓜播报 一手资讯 热点追踪 国际新闻",
    "加密货币": "区块链资讯 Web3 新闻 市场动态",
    "影视剧集": "影视资讯 剧集推荐 观影讨论",
}

CATEGORY_ORDER = [
    "🆕 新发现频道",
    "📰 新闻快讯",
    "💻 数码科技",
    "👨‍💻 开发运维",
    "🔒 信息安全",
    "🧰 软件工具",
    "☁️ 网盘资源",
    "🎬 影视剧集",
    "🎵 音乐音频",
    "🎐 动漫次元",
    "🎮 游戏娱乐",
    "✈️ 科学上网",
    "🪙 加密货币",
    "📚 学习阅读",
    "🎨 创意设计",
    "📡 社媒搬运",
    "🏀 体育运动",
    "👗 生活消费",
    "🌍 地区社群",
    "💬 闲聊交友",
    "🗂️ 综合导航",
    "🌐 综合其他",
    "🤖 机器人",
]


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


def category_sort_key(category):
    if category in CATEGORY_ORDER:
        return CATEGORY_ORDER.index(category)
    return len(CATEGORY_ORDER)


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
        category = row["category"] or DEFAULT_CATEGORY.get(entry_type, "🌐 综合其他")
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
        }

        type_map.setdefault(type_label, {})
        type_map[type_label].setdefault(category, [])
        type_map[type_label][category].append(item)
        category_seen[category] = split_category(category)

    categories = [
        category_seen[name]
        for name in sorted(category_seen.keys(), key=category_sort_key)
    ]

    types = []
    for type_label in ["频道", "群组", "机器人"]:
        if type_label not in type_map:
            continue
        categories_for_type = []
        for category in sorted(type_map[type_label].keys(), key=category_sort_key):
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

    sitemap_urls = ["<url><loc>https://www.rectg.com/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>"]
    for type_block in types:
        for category_block in type_block["categories"]:
            for item in category_block["items"]:
                sitemap_urls.append(
                    f"<url><loc>https://www.rectg.com/p/{item['id']}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>"
                )

    sitemap = '<?xml version="1.0" encoding="UTF-8"?>\n'
    sitemap += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    sitemap += "\n".join(sitemap_urls)
    sitemap += "\n</urlset>\n"

    SITEMAP_FILE.write_text(sitemap, encoding="utf-8")
    ROBOTS_FILE.write_text(
        "User-agent: *\nAllow: /\nSitemap: https://www.rectg.com/sitemap.xml\n",
        encoding="utf-8",
    )

    print(f"✅ Generated data.json from SQLite: {OUT_FILE}")
    print(f"✅ Categories: {len(categories)}")
    print(f"✅ Types: {len(types)}")
    print(f"✅ Items: {sum(len(c['items']) for t in types for c in t['categories'])}")
    print(f"✅ Ads: {len(ads['items'])}")


if __name__ == "__main__":
    main()
