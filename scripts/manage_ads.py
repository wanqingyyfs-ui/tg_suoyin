#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 数据库不存在: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


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


def get_ad(conn: sqlite3.Connection, ad_id: int):
    return conn.execute("SELECT * FROM ads WHERE id = ?", (ad_id,)).fetchone()


def print_ad(row) -> None:
    print(f"id:          {row['id']}")
    print(f"position:    {row['position']}")
    print(f"title:       {row['title']}")
    print(f"description: {row['description'] or '-'}")
    print(f"url:         {row['url']}")
    print(f"image_url:   {row['image_url'] or '-'}")
    print(f"sort_order:  {row['sort_order']}")
    print(f"enabled:     {row['enabled']}")
    print(f"created_at:  {row['created_at']}")
    print(f"updated_at:  {row['updated_at']}")


def cmd_init(_args) -> None:
    conn = connect_db()
    init_ads_table(conn)
    conn.close()
    print("✅ ads 表已准备完成")


def cmd_add(args) -> None:
    conn = connect_db()
    init_ads_table(conn)
    now = now_text()
    cur = conn.execute(
        """
        INSERT INTO ads (
            position, title, description, url, image_url,
            sort_order, enabled, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            args.position.strip(),
            args.title.strip(),
            args.description,
            args.url.strip(),
            args.image_url,
            args.sort_order,
            0 if args.disabled else 1,
            now,
            now,
        ),
    )
    conn.commit()
    row = get_ad(conn, cur.lastrowid)
    conn.close()
    print("✅ 广告已新增")
    print_ad(row)


def cmd_list(args) -> None:
    conn = connect_db()
    init_ads_table(conn)
    where, params = [], []
    if not args.all:
        where.append("enabled = 1")
    if args.position:
        where.append("position = ?")
        params.append(args.position)
    where_sql = "WHERE " + " AND ".join(where) if where else ""

    rows = conn.execute(
        f"""
        SELECT * FROM ads
        {where_sql}
        ORDER BY position COLLATE NOCASE, sort_order ASC, id ASC
        """,
        params,
    ).fetchall()
    conn.close()

    print(f"共 {len(rows)} 条广告")
    for idx, row in enumerate(rows, 1):
        print(f"{idx:03d}. [{row['position']}] {row['title']} id={row['id']} enabled={row['enabled']} sort={row['sort_order']}")
        print(f"     url: {row['url']}")
        if row["description"]:
            print(f"     desc: {row['description']}")
        if row["image_url"]:
            print(f"     image: {row['image_url']}")


def cmd_update(args) -> None:
    conn = connect_db()
    init_ads_table(conn)
    row = get_ad(conn, args.id)
    if not row:
        conn.close()
        raise SystemExit("❌ 未找到广告")

    updates, params = [], []
    for field, value in (
        ("position", args.position),
        ("title", args.title),
        ("description", args.description),
        ("url", args.url),
        ("image_url", args.image_url),
        ("sort_order", args.sort_order),
        ("enabled", args.enabled),
    ):
        if value is not None:
            updates.append(f"{field} = ?")
            params.append(value)

    if not updates:
        conn.close()
        raise SystemExit("❌ 没有提供任何要修改的字段")

    updates.append("updated_at = ?")
    params.append(now_text())
    params.append(args.id)

    conn.execute(f"UPDATE ads SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    row = get_ad(conn, args.id)
    conn.close()
    print("✅ 广告已更新")
    print_ad(row)


def cmd_enable_disable(args, enabled: int) -> None:
    conn = connect_db()
    init_ads_table(conn)
    if not get_ad(conn, args.id):
        conn.close()
        raise SystemExit("❌ 未找到广告")
    conn.execute(
        "UPDATE ads SET enabled = ?, updated_at = ? WHERE id = ?",
        (enabled, now_text(), args.id),
    )
    conn.commit()
    row = get_ad(conn, args.id)
    conn.close()
    print("✅ 广告状态已更新")
    print_ad(row)


def cmd_enable(args) -> None:
    cmd_enable_disable(args, 1)


def cmd_disable(args) -> None:
    cmd_enable_disable(args, 0)


def cmd_delete(args) -> None:
    if not args.yes:
        raise SystemExit("❌ 删除广告需要加 --yes")
    conn = connect_db()
    init_ads_table(conn)
    if not get_ad(conn, args.id):
        conn.close()
        raise SystemExit("❌ 未找到广告")
    conn.execute("DELETE FROM ads WHERE id = ?", (args.id,))
    conn.commit()
    conn.close()
    print(f"✅ 已删除广告 id={args.id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="管理 ads 广告位表")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("add")
    p.add_argument("position")
    p.add_argument("title")
    p.add_argument("--url", required=True)
    p.add_argument("--description", default=None)
    p.add_argument("--image-url", default=None)
    p.add_argument("--sort-order", type=int, default=0)
    p.add_argument("--disabled", action="store_true")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list")
    p.add_argument("--all", action="store_true")
    p.add_argument("--position", default=None)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("update")
    p.add_argument("id", type=int)
    p.add_argument("--position", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--description", default=None)
    p.add_argument("--url", default=None)
    p.add_argument("--image-url", default=None)
    p.add_argument("--sort-order", type=int, default=None)
    p.add_argument("--enabled", type=int, choices=(0, 1), default=None)
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("enable")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_enable)

    p = sub.add_parser("disable")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_disable)

    p = sub.add_parser("delete")
    p.add_argument("id", type=int)
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
