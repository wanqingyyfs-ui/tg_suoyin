#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"

TYPE_CHOICES = ("channel", "group", "bot")
TYPE_LABELS = {
    "channel": "频道",
    "group": "群组",
    "bot": "机器人",
}


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"数据库不存在：{DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def normalize_type(entry_type: str | None) -> str | None:
    if not entry_type:
        return None
    entry_type = entry_type.strip().lower()
    return entry_type if entry_type in TYPE_CHOICES else None


def to_count_str(value: Any) -> str:
    try:
        count = int(value or 0)
    except (TypeError, ValueError):
        count = 0
    return f"{count:,}"


def row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    entry_type = row["type"] or "channel"
    desc = row["clean_desc"] or row["description"] or ""
    title = row["clean_title"] or row["title"] or row["username"] or row["url"] or "未命名"
    return {
        "id": row["id"],
        "title": title,
        "username": row["username"] or "",
        "url": row["url"] or "",
        "type": entry_type,
        "typeLabel": TYPE_LABELS.get(entry_type, entry_type or "未知"),
        "count": row["count"] or 0,
        "countStr": to_count_str(row["count"]),
        "desc": desc,
        "description": row["description"] or "",
        "clean_desc": row["clean_desc"] or "",
        "category": row["category"] or "",
        "keep": int(row["keep"] or 0),
        "valid": int(row["valid"] or 0),
        "private": int(row["private"] or 0),
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
    }


def search_entries(
    keyword: str = "",
    entry_type: str | None = None,
    category: str | None = None,
    limit: int = 20,
    page: int = 1,
    sort: str = "relevance",
) -> dict[str, Any]:
    """搜索公开可见的 TG 索引条目。

    返回统一字典结构，供命令行、后台管理页和 Telegram Bot 共用。
    """
    keyword = (keyword or "").strip()
    entry_type = normalize_type(entry_type)
    category = (category or "").strip() or None
    sort = (sort or "relevance").strip().lower()
    safe_limit = max(1, min(int(limit or 20), 100))
    safe_page = max(1, int(page or 1))
    offset = (safe_page - 1) * safe_limit

    where = ["keep = 1", "valid = 1", "private = 0"]
    params: list[Any] = []

    if keyword:
        q = f"%{keyword}%"
        where.append(
            "(title LIKE ? OR clean_title LIKE ? OR description LIKE ? OR clean_desc LIKE ? "
            "OR username LIKE ? OR category LIKE ? OR url LIKE ?)"
        )
        params.extend([q, q, q, q, q, q, q])

    if entry_type:
        where.append("type = ?")
        params.append(entry_type)

    if category:
        where.append("category = ?")
        params.append(category)

    where_sql = " AND ".join(where)

    if sort == "latest":
        order_sql = """
            datetime(COALESCE(updated_at, created_at, '1970-01-01')) DESC,
            id DESC
        """
    else:
        order_sql = """
            COALESCE(count, 0) DESC,
            title COLLATE NOCASE,
            id DESC
        """

    conn = connect_db()
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS total FROM entries WHERE {where_sql}",
            params,
        ).fetchone()["total"]

        rows = conn.execute(
            f"""
            SELECT
                id, title, clean_title, username, url, type, count,
                clean_desc, description, category,
                keep, valid, private, created_at, updated_at
            FROM entries
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            [*params, safe_limit, offset],
        ).fetchall()
    finally:
        conn.close()

    items = [row_to_item(row) for row in rows]
    return {
        "keyword": keyword,
        "type": entry_type,
        "category": category,
        "sort": sort,
        "page": safe_page,
        "limit": safe_limit,
        "total": int(total or 0),
        "hasMore": offset + len(items) < int(total or 0),
        "items": items,
    }


def format_human(result: dict[str, Any]) -> str:
    items = result.get("items", [])
    if not items:
        return "未找到匹配结果"

    lines = [
        f"搜索关键词：{result.get('keyword') or '全部'}",
        f"结果数量：{result.get('total', 0)} 条，当前第 {result.get('page', 1)} 页",
        "",
    ]
    for idx, item in enumerate(items, 1):
        desc = item.get("desc") or ""
        if len(desc) > 80:
            desc = desc[:77] + "..."
        lines.append(
            f"{idx}. [{item.get('typeLabel')}] {item.get('title') or '-'}\n"
            f"   @{item.get('username') or '-'}｜{item.get('category') or '-'}｜{item.get('countStr') or '0'}\n"
            f"   {item.get('url') or '-'}\n"
            f"   {desc}"
        )
    return "\n\n".join(lines)


def format_markdown(result: dict[str, Any]) -> str:
    items = result.get("items", [])
    if not items:
        return "未找到匹配结果"

    lines = []
    for item in items:
        title = item.get("title") or item.get("username") or item.get("url") or "未命名"
        lines.append(
            f"- [{title}]({item.get('url')})｜{item.get('typeLabel') or '-'}｜"
            f"{item.get('category') or '-'}｜{item.get('countStr') or '0'}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="搜索 TG 索引数据库")
    parser.add_argument("keyword", nargs="?", default="", help="搜索关键词，不填则列出全部可见资源")
    parser.add_argument("--type", choices=TYPE_CHOICES, default=None, help="资源类型：channel/group/bot")
    parser.add_argument("--category", default=None, help="分类名，例如：💻 数码科技")
    parser.add_argument("--limit", type=int, default=20, help="每页数量，最大 100")
    parser.add_argument("--page", type=int, default=1, help="页码")
    parser.add_argument("--sort", choices=("relevance", "latest"), default="relevance", help="排序方式")
    parser.add_argument("--format", choices=("human", "json", "markdown"), default="human", help="输出格式")
    args = parser.parse_args()

    result = search_entries(
        keyword=args.keyword,
        entry_type=args.type,
        category=args.category,
        limit=args.limit,
        page=args.page,
        sort=args.sort,
    )

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.format == "markdown":
        print(format_markdown(result))
    else:
        print(format_human(result))


if __name__ == "__main__":
    main()
