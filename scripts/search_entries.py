#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"

TYPE_CHOICES = ("channel", "group", "bot")
SORT_CHOICES = ("relevance", "latest")
DEFAULT_LIMIT = 20
MAX_LIMIT = 100

TEXT_FIELDS = (
    "title",
    "clean_title",
    "description",
    "clean_desc",
    "username",
    "category",
)

ASCII_RE = re.compile(r"^[A-Za-z0-9_+.#-]+$")
ASCII_TOKEN_RE = re.compile(r"[A-Za-z0-9_+.#-]+")
CJK_RE = re.compile(r"[\u4e00-\u9fff]+")


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 数据库不存在: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def normalize_limit(value: int) -> int:
    return max(1, min(value, MAX_LIMIT))


def normalize_page(value: int) -> int:
    return max(1, value)


def count_str(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value:,}"


def shorten(text: str, max_len: int = 120) -> str:
    text = " ".join((text or "").split())
    if len(text) <= max_len:
        return text
    return text[:max_len].rstrip() + "..."


def is_short_ascii_keyword(keyword: str) -> bool:
    keyword = keyword.strip()
    return bool(keyword) and len(keyword) <= 2 and bool(ASCII_RE.fullmatch(keyword))


def ascii_boundary_match(text: str, keyword: str) -> bool:
    """Match short English keywords as standalone terms.

    This prevents `AI` from matching `Daily`, `lihaiba`, or `sspai`, while still
    matching `AI`, `AI_News_CN`, `AI & FSD`, and Chinese/English mixed titles
    that start with `AI`.
    """
    if not text:
        return False

    query = re.escape(keyword)
    pattern = re.compile(rf"(?<![A-Za-z0-9]){query}(?![A-Za-z0-9])", re.IGNORECASE)
    return bool(pattern.search(text))


def contains_match(text: str, keyword: str) -> bool:
    return keyword.casefold() in (text or "").casefold()


def field_match(text: str, keyword: str) -> bool:
    if not keyword:
        return True

    if is_short_ascii_keyword(keyword):
        return ascii_boundary_match(text, keyword)

    return contains_match(text, keyword)


def unique_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def cjk_ngrams(value: str) -> list[str]:
    parts: list[str] = []
    for chunk in CJK_RE.findall(value):
        if len(chunk) <= 2:
            parts.append(chunk)
            continue
        for size in (2, 3):
            if len(chunk) >= size:
                parts.extend(chunk[idx:idx + size] for idx in range(0, len(chunk) - size + 1))
    return parts


def split_keyword(keyword: str) -> list[str]:
    keyword = " ".join((keyword or "").strip().split())
    if not keyword:
        return []

    explicit_parts = re.split(r"[\s,，、/|]+", keyword)
    parts: list[str] = []

    for part in explicit_parts:
        part = part.strip()
        if not part:
            continue

        ascii_tokens = ASCII_TOKEN_RE.findall(part)
        cjk_tokens = cjk_ngrams(part)

        if ascii_tokens or cjk_tokens:
            parts.extend(ascii_tokens)
            parts.extend(cjk_tokens)
        else:
            parts.append(part)

    return unique_keep_order(parts)


def row_text(row: sqlite3.Row, fields: tuple[str, ...] = TEXT_FIELDS) -> str:
    return " ".join(str(row[field] or "") for field in fields)


def match_count(row: sqlite3.Row, tokens: list[str]) -> int:
    text = row_text(row)
    return sum(1 for token in tokens if field_match(text, token))


def calc_score(row: sqlite3.Row, keyword: str, tokens: list[str] | None = None) -> int:
    keyword = keyword.strip()
    if not keyword:
        return 0

    tokens = tokens if tokens is not None else split_keyword(keyword)
    username = row["username"] or ""
    title = row["title"] or ""
    clean_title = row["clean_title"] or ""
    description = row["description"] or ""
    clean_desc = row["clean_desc"] or ""
    category = row["category"] or ""

    score = 0
    keyword_cf = keyword.casefold()

    if username.casefold() == keyword_cf:
        score += 160
    if field_match(title, keyword):
        score += 140
    if field_match(clean_title, keyword):
        score += 140
    if field_match(username, keyword):
        score += 110
    if field_match(category, keyword):
        score += 70
    if field_match(description, keyword):
        score += 55
    if field_match(clean_desc, keyword):
        score += 55

    matched_tokens = 0
    for token in tokens:
        token_hit = False
        if username.casefold() == token.casefold():
            score += 80
            token_hit = True
        if field_match(title, token):
            score += 55
            token_hit = True
        if field_match(clean_title, token):
            score += 55
            token_hit = True
        if field_match(username, token):
            score += 45
            token_hit = True
        if field_match(category, token):
            score += 30
            token_hit = True
        if field_match(description, token):
            score += 18
            token_hit = True
        if field_match(clean_desc, token):
            score += 18
            token_hit = True
        if token_hit:
            matched_tokens += 1

    if tokens:
        score += matched_tokens * 120
        if matched_tokens == len(tokens):
            score += 500

    return score


def row_to_item(row: sqlite3.Row, score: int) -> dict[str, Any]:
    title = row["title"] or row["clean_title"] or row["username"] or row["url"] or "未命名"
    desc = row["clean_desc"] or row["description"] or ""
    url = row["url"] or f"https://t.me/{row['username']}"

    return {
        "id": row["id"],
        "title": title,
        "username": row["username"] or "",
        "url": url,
        "type": row["type"] or "",
        "count": row["count"],
        "countStr": count_str(row["count"]),
        "category": row["category"] or "",
        "desc": desc,
        "score": score,
        "createdAt": row["created_at"] or "",
        "updatedAt": row["updated_at"] or "",
    }


def build_filter_sql(entry_type: str | None, category: str | None) -> tuple[str, list[Any]]:
    where_parts = [
        "keep = 1",
        "valid = 1",
        "private = 0",
    ]
    params: list[Any] = []

    if entry_type:
        where_parts.append("type = ?")
        params.append(entry_type)

    if category:
        where_parts.append("category = ?")
        params.append(category.strip())

    return "WHERE " + " AND ".join(where_parts), params


def load_candidate_rows(entry_type: str | None, category: str | None) -> list[sqlite3.Row]:
    where_sql, params = build_filter_sql(entry_type, category)
    conn = connect_db()
    rows = conn.execute(
        f"""
        SELECT
            id,
            title,
            clean_title,
            username,
            url,
            type,
            count,
            description,
            clean_desc,
            category,
            created_at,
            updated_at
        FROM entries
        {where_sql}
        """,
        params,
    ).fetchall()
    conn.close()
    return rows


def search_entries(
    keyword: str,
    entry_type: str | None = None,
    category: str | None = None,
    limit: int = DEFAULT_LIMIT,
    page: int = 1,
    sort: str = "relevance",
) -> dict[str, Any]:
    keyword = (keyword or "").strip()
    limit = normalize_limit(limit)
    page = normalize_page(page)
    offset = (page - 1) * limit
    sort = sort if sort in SORT_CHOICES else "relevance"

    rows = load_candidate_rows(entry_type, category)
    tokens = split_keyword(keyword)
    matched_items: list[dict[str, Any]] = []

    for row in rows:
        score = calc_score(row, keyword, tokens)
        if keyword and score <= 0:
            continue
        matched_items.append(row_to_item(row, score))

    if sort == "latest":
        matched_items.sort(
            key=lambda item: (
                item["createdAt"] or "",
                item["score"] or 0,
                item["count"] or 0,
                item["title"].casefold(),
            ),
            reverse=True,
        )
    else:
        matched_items.sort(
            key=lambda item: (
                -(item["score"] or 0),
                -(item["count"] or 0),
                item["title"].casefold(),
            )
        )

    total = len(matched_items)
    page_items = matched_items[offset:offset + limit]

    return {
        "query": keyword,
        "filters": {
            "type": entry_type,
            "category": category,
            "sort": sort,
            "tokens": tokens,
        },
        "page": page,
        "limit": limit,
        "total": total,
        "hasMore": offset + len(page_items) < total,
        "items": page_items,
    }


def print_text_result(result: dict[str, Any]) -> None:
    query = result["query"] or "全部"
    filters = result["filters"]

    print("=" * 60)
    print(" 搜索 entries")
    print("=" * 60)
    print(f"关键词: {query}")
    print(f"type: {filters['type'] or '-'}")
    print(f"category: {filters['category'] or '-'}")
    print(f"sort: {filters.get('sort') or '-'}")
    print(f"tokens: {', '.join(filters.get('tokens') or []) or '-'}")
    print(f"page: {result['page']}")
    print(f"limit: {result['limit']}")
    print(f"total: {result['total']}")
    print("")

    items = result["items"]
    if not items:
        print("❌ 没有匹配结果")
        return

    start = (result["page"] - 1) * result["limit"]

    for idx, item in enumerate(items, start=1):
        print(f"{start + idx:03d}. [{item['type'] or '-'}] {item['title']}")
        print(f"    分类: {item['category'] or '-'}")
        print(f"    人数: {item['countStr']}")
        print(f"    添加: {item.get('createdAt') or '-'}")
        print(f"    分数: {item['score']}")
        print(f"    链接: {item['url']}")

        if item["desc"]:
            print(f"    简介: {shorten(item['desc'])}")

        print("")

    if result["hasMore"]:
        print(f"还有更多结果，可继续查看第 {result['page'] + 1} 页。")


def main() -> None:
    parser = argparse.ArgumentParser(description="从 SQLite entries 表搜索 Telegram 频道/群组/机器人")
    parser.add_argument("keyword", nargs="?", default="", help="搜索关键词")
    parser.add_argument("--type", choices=TYPE_CHOICES, default=None, help="筛选类型: channel/group/bot")
    parser.add_argument("--category", default=None, help="筛选分类，必须与数据库中的 category 完全一致")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"每页数量，最大 {MAX_LIMIT}")
    parser.add_argument("--page", type=int, default=1, help="页码，从 1 开始")
    parser.add_argument("--sort", choices=SORT_CHOICES, default="relevance", help="排序方式")
    parser.add_argument("--json", action="store_true", help="输出 JSON，方便后续 Telegram Bot 复用")

    args = parser.parse_args()

    result = search_entries(
        keyword=args.keyword,
        entry_type=args.type,
        category=args.category,
        limit=args.limit,
        page=args.page,
        sort=args.sort,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_text_result(result)


if __name__ == "__main__":
    main()
