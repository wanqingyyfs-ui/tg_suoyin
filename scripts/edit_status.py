#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"


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


def cmd_get(args) -> None:
    conn = connect_db()
    row = get_entry(conn, args.target)
    conn.close()
    print_entry(row)


def cmd_set(args) -> None:
    if args.reason and args.clear_reason:
        raise SystemExit("❌ --reason 和 --clear-reason 不能同时使用")

    updates, params = [], []
    for field, value in (("keep", args.keep), ("valid", args.valid), ("private", args.private)):
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    if args.reason is not None:
        updates.append("filter_reason = ?")
        params.append(args.reason)

    if args.clear_reason:
        updates.append("filter_reason = ?")
        params.append("")

    if not updates:
        raise SystemExit("❌ 没有提供任何要修改的字段")

    conn = connect_db()
    row = get_entry(conn, args.target)
    if not row:
        conn.close()
        raise SystemExit("❌ 未找到对应 entries 记录")

    updates.append("updated_at = ?")
    params.append(datetime.now().isoformat(timespec="seconds"))
    params.append(row["id"])

    conn.execute(f"UPDATE entries SET {', '.join(updates)} WHERE id = ?", params)
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

    print("✅ 状态已更新")
    print_entry(updated)


def cmd_list(args) -> None:
    conn = connect_db()
    where_parts, params = [], []
    if args.kept:
        where_parts.append("keep = 1")
    if args.filtered:
        where_parts.append("keep = 0")
    if args.private:
        where_parts.append("private = 1")
    if args.invalid:
        where_parts.append("valid = 0")
    if args.reason_like:
        where_parts.append("filter_reason LIKE ?")
        params.append(f"%{args.reason_like}%")
    if args.type:
        where_parts.append("type = ?")
        params.append(args.type)
    where = "WHERE " + " AND ".join(where_parts) if where_parts else ""
    params.append(max(args.limit, 1))

    rows = conn.execute(
        f"""
        SELECT title, username, url, type, count, category,
               valid, private, keep, filter_reason, updated_at
        FROM entries
        {where}
        ORDER BY updated_at DESC, id DESC
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
        print(f"     status:   keep={row['keep']} valid={row['valid']} private={row['private']}")
        if row["filter_reason"]:
            print(f"     reason:   {row['filter_reason']}")
        print("")


def main() -> None:
    parser = argparse.ArgumentParser(description="管理 entries 表 keep / valid / private 状态")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("get")
    p.add_argument("target")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("set")
    p.add_argument("target")
    p.add_argument("--keep", type=int, choices=(0, 1), default=None)
    p.add_argument("--valid", type=int, choices=(0, 1), default=None)
    p.add_argument("--private", type=int, choices=(0, 1), default=None)
    p.add_argument("--reason", default=None)
    p.add_argument("--clear-reason", action="store_true")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("list")
    p.add_argument("--kept", action="store_true")
    p.add_argument("--filtered", action="store_true")
    p.add_argument("--private", action="store_true")
    p.add_argument("--invalid", action="store_true")
    p.add_argument("--reason-like", default=None)
    p.add_argument("--type", choices=("channel", "group", "bot"), default=None)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
