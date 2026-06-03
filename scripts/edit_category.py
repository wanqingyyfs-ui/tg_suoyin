#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"

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


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 数据库不存在: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def normalize_target(raw: str) -> tuple[str | None, str | None]:
    value = (raw or "").strip()
    if not value:
        return None, None
    if value.startswith("@"):
        value = value[1:].strip()
    if value.startswith("t.me/"):
        value = "https://" + value
    if value.startswith("telegram.me/"):
        value = "https://" + value
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if not parts:
            return None, value
        username = parts[1] if parts[0] == "s" and len(parts) >= 2 else parts[0]
        return username, f"https://t.me/{username}"
    return value, f"https://t.me/{value}"


def get_entry(conn: sqlite3.Connection, target: str):
    username, url = normalize_target(target)
    return conn.execute(
        """
        SELECT id, title, username, url, type, count, category,
               valid, private, keep, filter_reason, updated_at
        FROM entries
        WHERE username = ? OR url = ?
        LIMIT 1
        """,
        (username, url),
    ).fetchone()


def print_entry(row) -> None:
    if not row:
        print("❌ 未找到对应 entries 记录")
        return
    print(f"id:            {row['id']}")
    print(f"title:         {row['title'] or '-'}")
    print(f"username:      {row['username'] or '-'}")
    print(f"url:           {row['url'] or '-'}")
    print(f"type:          {row['type'] or '-'}")
    print(f"count:         {row['count'] if row['count'] is not None else '-'}")
    print(f"category:      {row['category'] or '-'}")
    print(f"valid:         {row['valid']}")
    print(f"private:       {row['private']}")
    print(f"keep:          {row['keep']}")
    print(f"filter_reason: {row['filter_reason'] or '-'}")
    print(f"updated_at:    {row['updated_at'] or '-'}")


def category_sort_key(category: str | None) -> tuple[int, str]:
    value = (category or "").strip()
    if value in CATEGORY_ORDER:
        return CATEGORY_ORDER.index(value), value
    if not value:
        return len(CATEGORY_ORDER), ""
    return len(CATEGORY_ORDER) + 1, value


def cmd_categories(_args) -> None:
    for idx, category in enumerate(CATEGORY_ORDER, start=1):
        print(f"{idx:02d}. {category}")


def cmd_stats(args) -> None:
    conn = connect_db()
    where = "" if args.all else "WHERE keep = 1 AND valid = 1 AND private = 0"
    rows = conn.execute(
        f"""
        SELECT COALESCE(NULLIF(TRIM(category), ''), '未分类') AS category,
               COALESCE(type, 'unknown') AS type,
               COUNT(*) AS cnt
        FROM entries
        {where}
        GROUP BY category, type
        ORDER BY category COLLATE NOCASE, type COLLATE NOCASE
        """
    ).fetchall()
    conn.close()

    grouped = {}
    for row in rows:
        grouped.setdefault(row["category"], {})
        grouped[row["category"]][row["type"]] = row["cnt"]

    print("=" * 60)
    print("  分类统计")
    print("=" * 60)
    print(f"统计范围: {'全部 entries' if args.all else '可展示 entries'}")
    print(f"总数: {sum(sum(v.values()) for v in grouped.values())}")
    print("")
    for category in sorted(grouped.keys(), key=category_sort_key):
        types = grouped[category]
        detail = " / ".join(f"{k}:{v}" for k, v in sorted(types.items()))
        print(f"{category}: {sum(types.values())} ({detail})")


def cmd_get(args) -> None:
    conn = connect_db()
    row = get_entry(conn, args.target)
    conn.close()
    print_entry(row)


def cmd_set(args) -> None:
    category = args.category.strip()
    if not category:
        raise SystemExit("❌ category 不能为空")
    if not args.allow_new and category not in CATEGORY_ORDER:
        print("❌ 分类不在内置列表中。可用分类：")
        for item in CATEGORY_ORDER:
            print("  " + item)
        print("")
        print("确实要用新分类时，加 --allow-new")
        raise SystemExit(1)

    conn = connect_db()
    row = get_entry(conn, args.target)
    if not row:
        conn.close()
        raise SystemExit("❌ 未找到对应 entries 记录")

    before = row["category"] or ""
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        "UPDATE entries SET category = ?, updated_at = ? WHERE id = ?",
        (category, now, row["id"]),
    )
    conn.commit()
    updated = conn.execute(
        """
        SELECT id, title, username, url, type, count, category,
               valid, private, keep, filter_reason, updated_at
        FROM entries WHERE id = ?
        """,
        (row["id"],),
    ).fetchone()
    conn.close()

    print("✅ 分类已更新")
    print(f"before: {before or '-'}")
    print(f"after:  {category}")
    print("")
    print_entry(updated)


def cmd_list(args) -> None:
    conn = connect_db()
    where_parts, params = [], []
    if not args.all:
        where_parts += ["keep = 1", "valid = 1", "private = 0"]
    if args.uncategorized:
        where_parts.append("(category IS NULL OR TRIM(category) = '' OR category = '🌐 综合其他')")
    elif args.category:
        where_parts.append("category = ?")
        params.append(args.category)
    if args.type:
        where_parts.append("type = ?")
        params.append(args.type)
    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    params.append(max(args.limit, 1))
    rows = conn.execute(
        f"""
        SELECT title, username, url, type, count, category,
               keep, valid, private, filter_reason
        FROM entries
        {where}
        ORDER BY COALESCE(category, '') COLLATE NOCASE,
                 COALESCE(count, 0) DESC,
                 title COLLATE NOCASE
        LIMIT ?
        """,
        params,
    ).fetchall()
    conn.close()

    print(f"共显示 {len(rows)} 条")
    for idx, row in enumerate(rows, 1):
        print(f"{idx:03d}. [{row['type'] or '-'}] {row['title'] or row['username'] or row['url'] or '-'}")
        print(f"     username: {row['username'] or '-'}")
        print(f"     category: {row['category'] or '-'}")
        print(f"     count:    {row['count'] if row['count'] is not None else '-'}")
        print(f"     status:   keep={row['keep']} valid={row['valid']} private={row['private']}")
        if row["filter_reason"]:
            print(f"     reason:   {row['filter_reason']}")
        print("")


def main() -> None:
    parser = argparse.ArgumentParser(description="编辑 entries 表中的 category 字段")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("categories", help="列出内置分类")
    p.set_defaults(func=cmd_categories)

    p = sub.add_parser("stats", help="查看分类统计")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("get", help="查看单个 username / URL 的分类")
    p.add_argument("target")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("set", help="修改单个 username / URL 的分类")
    p.add_argument("target")
    p.add_argument("category")
    p.add_argument("--allow-new", action="store_true")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("list", help="列出 entries")
    p.add_argument("--category", default=None)
    p.add_argument("--uncategorized", action="store_true")
    p.add_argument("--type", choices=("channel", "group", "bot"), default=None)
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
