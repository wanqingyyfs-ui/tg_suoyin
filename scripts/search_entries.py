#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"数据库不存在: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def search_entries(keyword: str, entry_type: str | None, category: str | None, limit: int, page: int):
    q = f"%{keyword.strip()}%"
    where = [
        "keep = 1",
        "valid = 1",
        "private = 0",
        "(title LIKE ? OR clean_title LIKE ? OR description LIKE ? OR clean_desc LIKE ? OR username LIKE ? OR category LIKE ? OR url LIKE ?)",
    ]
    params = [q, q, q, q, q, q, q]

    if entry_type:
        where.append("type = ?")
        params.append(entry_type)

    if category:
        where.append("category = ?")
        params.append(category)

    safe_limit = max(1, min(limit, 100))
    safe_page = max(1, page)
    offset = (safe_page - 1) * safe_limit
    params.extend([safe_limit, offset])

    conn = connect_db()
    rows = conn.execute(
        f"""
        SELECT id, title, username, url, type, count, clean_desc, description, category
        FROM entries
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(count, 0) DESC, title COLLATE NOCASE
        LIMIT ? OFFSET ?
        """,
        params,
    ).fetchall()
    conn.close()
    return rows


def format_human(rows) -> str:
    if not rows:
        return "未找到匹配结果"
    lines = []
    for idx, row in enumerate(rows, 1):
        desc = row["clean_desc"] or row["description"] or ""
        if len(desc) > 80:
            desc = desc[:77] + "..."
        lines.append(
            f"{idx}. [{row['type']}] {row['title'] or row['username'] or '-'}\n"
            f"   @{row['username'] or '-'} | {row['category'] or '-'} | {row['count'] or 0}\n"
            f"   {row['url'] or '-'}\n"
            f"   {desc}"
        )
    return "\n\n".join(lines)


def format_markdown(rows) -> str:
    if not rows:
        return "未找到匹配结果"
    lines = []
    for row in rows:
        title = row["title"] or row["username"] or row["url"] or "未命名"
        lines.append(f"- [{title}]({row['url']})｜{row['category'] or '-'}｜{row['count'] or 0}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="搜索 TG 索引 entries")
    parser.add_argument("keyword")
    parser.add_argument("--type", choices=("channel", "group", "bot"), default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human")
    args = parser.parse_args()

    rows = search_entries(args.keyword, args.type, args.category, args.limit, args.page)

    if args.format == "json":
        print(json.dumps([dict(row) for row in rows], ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(format_markdown(rows))
    else:
        print(format_human(rows))


if __name__ == "__main__":
    main()
