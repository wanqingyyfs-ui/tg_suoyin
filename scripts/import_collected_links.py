#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
TYPE_CHOICES = {"channel", "group", "bot"}
REJECTED_FIRST_SEGMENTS = {
    "+",
    "joinchat",
    "c",
    "share",
    "addstickers",
    "setlanguage",
    "proxy",
    "iv",
    "addemoji",
    "addlist",
    "login",
    "bg",
}


def clean_raw_link(value: str) -> str:
    value = (value or "").strip()
    value = value.strip(" \t\r\n<>[](){}'\"“”‘’，。；;、")
    value = value.replace("telegram.me/", "t.me/")
    if value.startswith("@"):
        return value
    if value.startswith("t.me/"):
        value = "https://" + value
    if value.startswith("http://"):
        value = "https://" + value.removeprefix("http://")
    return value


def normalize_tg_url(raw: str) -> tuple[str | None, str | None, str | None]:
    value = clean_raw_link(raw)
    if not value:
        return None, None, "空链接"

    if value.startswith("@"):
        username = value[1:].strip()
        if USERNAME_RE.match(username):
            return f"https://t.me/{username}", username, None
        return None, None, "无效 @username"

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host not in {"t.me", "www.t.me", "telegram.me", "www.telegram.me"}:
        return None, None, "非 Telegram 链接"

    parts = [p for p in parsed.path.strip("/").split("/") if p]
    if not parts:
        return None, None, "缺少 username"

    username = parts[1] if parts[0] == "s" and len(parts) >= 2 else parts[0]
    first_lower = username.lower()

    if username.startswith("+"):
        return None, None, "私密邀请链接"
    if first_lower in REJECTED_FIRST_SEGMENTS:
        return None, None, f"不支持的 Telegram 链接类型: {username}"
    if not USERNAME_RE.match(username):
        return None, None, "无效 username"

    return f"https://t.me/{username}", username, None


def normalize_type_hint(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().lower()
    aliases = {
        "频道": "channel",
        "channel": "channel",
        "群组": "group",
        "群": "group",
        "group": "group",
        "supergroup": "group",
        "机器人": "bot",
        "bot": "bot",
    }
    result = aliases.get(v)
    return result if result in TYPE_CHOICES else None


def init_links_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS links (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            url             TEXT NOT NULL UNIQUE,
            username        TEXT,
            name            TEXT,
            type_hint       TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """
    )
    conn.commit()


def read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            value = line.strip()
            if not value:
                continue
            try:
                item = json.loads(value)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"JSONL 第 {line_no} 行解析失败：{exc}") from exc
            if not isinstance(item, dict):
                raise SystemExit(f"JSONL 第 {line_no} 行不是对象")
            yield item


def read_json(path: Path) -> Iterable[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "items" in data:
        data = data["items"]
    if not isinstance(data, list):
        raise SystemExit("JSON 文件必须是数组，或者包含 items 数组")
    for item in data:
        if isinstance(item, dict):
            yield item


def read_csv(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        yield from csv.DictReader(f)


def read_items(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        yield from read_jsonl(path)
    elif suffix == ".json":
        yield from read_json(path)
    elif suffix == ".csv":
        yield from read_csv(path)
    else:
        raise SystemExit("只支持 .jsonl / .json / .csv")


def infer_url(item: dict[str, Any]) -> str:
    return str(
        item.get("url")
        or item.get("link")
        or item.get("telegram_url")
        or item.get("tg_url")
        or item.get("username")
        or ""
    )


def import_items(conn: sqlite3.Connection, items: Iterable[dict[str, Any]], dry_run: bool = False) -> dict[str, int]:
    now = datetime.now().isoformat()
    stats = {"inserted": 0, "updated": 0, "skipped": 0}

    for item in items:
        raw_url = infer_url(item)
        url, username, error = normalize_tg_url(raw_url)
        if error:
            stats["skipped"] += 1
            continue

        name = str(item.get("name") or item.get("title") or username or "").strip()
        type_hint = normalize_type_hint(item.get("type_hint") or item.get("type"))

        existing = conn.execute("SELECT id FROM links WHERE url=?", (url,)).fetchone()
        if existing:
            stats["updated"] += 1
            if not dry_run:
                conn.execute(
                    """
                    UPDATE links SET
                        username=?,
                        name=COALESCE(NULLIF(?, ''), name),
                        type_hint=COALESCE(?, type_hint),
                        updated_at=?
                    WHERE url=?
                    """,
                    (username, name, type_hint, now, url),
                )
        else:
            stats["inserted"] += 1
            if not dry_run:
                conn.execute(
                    """
                    INSERT INTO links (url, username, name, type_hint, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (url, username, name, type_hint, now, now),
                )

    if not dry_run:
        conn.commit()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 tg_suoyin_collector 采集结果到 links 表")
    parser.add_argument("--file", required=True, help="采集器导出的 .jsonl / .json / .csv 文件")
    parser.add_argument("--db", default=str(DB_PATH), help="tg_suoyin SQLite 数据库路径，默认 data/rectg.db")
    parser.add_argument("--dry-run", action="store_true", help="只检查，不写入数据库")
    args = parser.parse_args()

    input_path = Path(args.file)
    if not input_path.exists():
        raise SystemExit(f"导入文件不存在：{input_path}")

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        init_links_table(conn)
        stats = import_items(conn, read_items(input_path), dry_run=args.dry_run)
        total = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    finally:
        conn.close()

    mode = "DRY RUN" if args.dry_run else "DONE"
    print(f"{mode}")
    print(f"文件：{input_path}")
    print(f"数据库：{db_path}")
    print(f"新增：{stats['inserted']}")
    print(f"更新：{stats['updated']}")
    print(f"跳过：{stats['skipped']}")
    print(f"links 表总数：{total}")


if __name__ == "__main__":
    main()
