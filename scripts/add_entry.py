#!/usr/bin/env python3
"""
手动添加 Telegram 频道/群组链接到 links 表。

用法:
    python scripts/add_entry.py https://t.me/username
    python scripts/add_entry.py username
    python scripts/add_entry.py @username --name "频道名称"
    python scripts/add_entry.py username --type channel
    python scripts/add_entry.py username --keep
    python scripts/add_entry.py username --crawl
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
TYPE_CHOICES = ("channel", "group", "bot")


def normalize_input(raw: str) -> tuple[str, str]:
    """
    将 Telegram 链接或 username 标准化为:
        username
        https://t.me/username
    """
    value = (raw or "").strip()

    if not value:
        raise ValueError("输入不能为空")

    if value.startswith("@"):
        value = value[1:].strip()

    if value.startswith("t.me/"):
        value = "https://" + value

    if value.startswith("telegram.me/"):
        value = "https://" + value

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urlparse(value)
        host = (parsed.netloc or "").lower()

        if host not in ("t.me", "www.t.me", "telegram.me", "www.telegram.me"):
            raise ValueError("只支持 t.me 或 telegram.me 链接")

        parts = [part for part in parsed.path.strip("/").split("/") if part]

        if not parts:
            raise ValueError("链接中没有 username")

        if parts[0] in ("joinchat", "+"):
            raise ValueError("暂不支持私密邀请链接，只支持公开 username")

        if parts[0] == "s":
            if len(parts) < 2:
                raise ValueError("/s/ 链接中没有 username")
            username = parts[1]
        elif parts[0].startswith("+"):
            raise ValueError("暂不支持私密邀请链接，只支持公开 username")
        else:
            username = parts[0]
    else:
        username = value

    username = username.strip().strip("/")

    if not USERNAME_RE.match(username):
        raise ValueError(
            "username 格式不合法。要求以英文字母开头，只包含字母、数字、下划线，长度 4-32 位"
        )

    url = f"https://t.me/{username}"
    return username, url


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 数据库不存在: {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def find_existing_link(conn: sqlite3.Connection, username: str, url: str):
    return conn.execute(
        """
        SELECT id, url, username, name, type_hint
        FROM links
        WHERE url = ? OR username = ?
        LIMIT 1
        """,
        (url, username),
    ).fetchone()


def find_entry(conn: sqlite3.Connection, username: str, url: str):
    return conn.execute(
        """
        SELECT id, title, username, url, type, count, valid, private, keep, filter_reason
        FROM entries
        WHERE url = ? OR username = ?
        LIMIT 1
        """,
        (url, username),
    ).fetchone()


def insert_link(
    conn: sqlite3.Connection,
    username: str,
    url: str,
    name: str | None,
    type_hint: str | None,
) -> bool:
    now = datetime.now().isoformat(timespec="seconds")

    conn.execute(
        """
        INSERT INTO links (
            url,
            username,
            name,
            type_hint,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            username,
            name or username,
            type_hint,
            now,
            now,
        ),
    )
    conn.commit()
    return True


def force_keep_entry(conn: sqlite3.Connection, entry_id: int) -> None:
    conn.execute(
        """
        UPDATE entries
        SET keep = 1,
            filter_reason = '',
            updated_at = ?
        WHERE id = ?
        """,
        (datetime.now().isoformat(timespec="seconds"), entry_id),
    )
    conn.commit()


def print_entry_status(entry) -> None:
    if not entry:
        print("ℹ️ entries 表暂未生成对应记录")
        return

    print("✅ entries 表已有对应记录")
    print(f"   标题: {entry['title'] or '-'}")
    print(f"   类型: {entry['type'] or '-'}")
    print(f"   人数: {entry['count'] if entry['count'] is not None else '-'}")
    print(f"   valid: {entry['valid']}")
    print(f"   private: {entry['private']}")
    print(f"   keep: {entry['keep']}")
    print(f"   filter_reason: {entry['filter_reason'] or '-'}")


def run_crawler() -> int:
    print("")
    print("🕷️ 开始执行爬虫:")
    print("   python scripts\\crawl.py --new --no-active")
    print("")

    result = subprocess.run(
        [sys.executable, "scripts/crawl.py", "--new", "--no-active"],
        cwd=str(ROOT_DIR),
    )
    return result.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="添加 Telegram 频道/群组到 links 表")
    parser.add_argument("target", help="Telegram 链接、@username 或 username")
    parser.add_argument("--name", default=None, help="显示名称，默认使用 username")
    parser.add_argument("--type", choices=TYPE_CHOICES, default=None, help="类型提示: channel/group/bot")
    parser.add_argument("--keep", action="store_true", help="如果 entries 已存在，则强制设置 keep=1")
    parser.add_argument("--crawl", action="store_true", help="添加后立即执行 crawl.py --new --no-active")
    args = parser.parse_args()

    try:
        username, url = normalize_input(args.target)
    except ValueError as e:
        raise SystemExit(f"❌ {e}")

    conn = connect_db()

    print("=" * 60)
    print("  添加 Telegram 频道/群组")
    print("=" * 60)
    print(f"username: {username}")
    print(f"url:      {url}")
    print(f"name:     {args.name or username}")
    print(f"type:     {args.type or '-'}")
    print("")

    existing = find_existing_link(conn, username, url)

    if existing:
        print("ℹ️ links 表已存在，跳过插入")
        print(f"   id: {existing['id']}")
        print(f"   url: {existing['url']}")
        print(f"   username: {existing['username'] or '-'}")
        print(f"   name: {existing['name'] or '-'}")
        print(f"   type_hint: {existing['type_hint'] or '-'}")
    else:
        insert_link(conn, username, url, args.name, args.type)
        print("✅ 已写入 links 表")

    entry = find_entry(conn, username, url)
    print("")
    print_entry_status(entry)

    if args.keep:
        if entry:
            force_keep_entry(conn, entry["id"])
            print("")
            print("✅ 已设置 entries.keep = 1")
            entry = find_entry(conn, username, url)
            print_entry_status(entry)
        else:
            print("")
            print("⚠️ 还没有 entries 记录，暂时不能设置 keep=1。请先抓取。")

    conn.close()

    if args.crawl:
        code = run_crawler()
        if code != 0:
            raise SystemExit(code)

        conn = connect_db()
        entry = find_entry(conn, username, url)
        conn.close()

        print("")
        print("📌 抓取后检查:")
        print_entry_status(entry)

    print("")
    print("下一步命令:")
    print("  python scripts\\crawl.py --new --no-active")
    print("  python scripts\\categorize.py")
    print("  python scripts\\export_frontend_data.py")
    print("  npm run build")


if __name__ == "__main__":
    main()
