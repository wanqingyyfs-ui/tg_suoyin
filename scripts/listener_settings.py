#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"
DEFAULT_INTERVAL = 300


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_settings(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS listener_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO listener_settings (key, value, updated_at) VALUES ('terminal_summary_interval_seconds', ?, datetime('now'))", (str(DEFAULT_INTERVAL),))
    conn.commit()


def get_interval(conn: sqlite3.Connection) -> int:
    ensure_settings(conn)
    row = conn.execute("SELECT value FROM listener_settings WHERE key='terminal_summary_interval_seconds'").fetchone()
    try:
        value = int(row["value"] if row else DEFAULT_INTERVAL)
    except (TypeError, ValueError):
        value = DEFAULT_INTERVAL
    return max(30, min(value, 86400))


def set_interval(conn: sqlite3.Connection, seconds: int) -> int:
    ensure_settings(conn)
    value = max(30, min(int(seconds), 86400))
    conn.execute(
        "INSERT INTO listener_settings (key, value, updated_at) VALUES ('terminal_summary_interval_seconds', ?, datetime('now')) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (str(value),),
    )
    conn.commit()
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description="设置 Bot 监听终端汇总打印间隔")
    parser.add_argument("seconds", nargs="?", type=int, help="间隔秒数，最小30，最大86400。默认300秒。")
    args = parser.parse_args()
    conn = connect_db()
    try:
        if args.seconds is not None:
            value = set_interval(conn, args.seconds)
            print(f"✅ 终端汇总间隔已设置为 {value} 秒")
        else:
            print(f"当前终端汇总间隔：{get_interval(conn)} 秒")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
