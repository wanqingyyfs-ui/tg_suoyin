#!/usr/bin/env python3
"""Prepare database schema for Bot API message anchor indexing."""
from __future__ import annotations

from message_indexer import open_db_with_schema


def main() -> None:
    conn = open_db_with_schema()
    try:
        stats = {
            "message_index": conn.execute("SELECT COUNT(*) AS c FROM message_index").fetchone()["c"],
            "listening_entries": conn.execute("SELECT COUNT(*) AS c FROM entries WHERE listen_enabled=1").fetchone()["c"],
        }
    finally:
        conn.close()
    print("✅ 消息索引数据库结构已准备完成")
    print(f"   message_index: {stats['message_index']} 条")
    print(f"   已开启监听资源: {stats['listening_entries']} 条")


if __name__ == "__main__":
    main()
