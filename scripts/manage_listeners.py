#!/usr/bin/env python3
"""Manage Bot API message listeners from CLI.

This is the safe operational companion for the admin UI: list resources, enable
or disable Bot API message listening, and inspect indexed message anchors.
"""
from __future__ import annotations

import argparse
import sqlite3
from typing import Any

from bot_api_client import BotApiClient, BotApiError, check_bot_can_listen, get_bot_token, load_env_file
from message_indexer import (
    clear_message_index,
    delete_message_index_row,
    init_message_index_schema,
    list_listening_entries,
    list_message_index_rows,
    message_index_stats,
    open_db_with_schema,
    search_message_index,
)


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def cmd_init(_args: argparse.Namespace) -> None:
    conn = open_db_with_schema()
    try:
        stats = message_index_stats(conn)
    finally:
        conn.close()
    print("✅ 消息监听和消息索引结构已准备完成")
    for key, value in stats.items():
        print(f"{key}: {value}")


def cmd_list(_args: argparse.Namespace) -> None:
    conn = open_db_with_schema()
    try:
        rows = list_listening_entries(conn)
    finally:
        conn.close()
    print(f"共 {len(rows)} 个频道/群组资源")
    for row in rows:
        status = row["listen_status"] or "off"
        enabled = "ON" if row["listen_enabled"] else "OFF"
        print(f"{row['id']:>5} [{enabled}/{status}] {row['title'] or row['username'] or row['url']}")
        print(f"      type={row['type']} username={row['username'] or '-'} chat_id={row['telegram_id'] or '-'} messages={row['message_count']}")
        if row["listen_error"]:
            print(f"      error={row['listen_error']}")


def get_entry(conn: sqlite3.Connection, entry_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    if not row:
        raise SystemExit(f"❌ 未找到资源 id={entry_id}")
    return row


def cmd_enable(args: argparse.Namespace) -> None:
    load_env_file()
    conn = open_db_with_schema()
    try:
        row = get_entry(conn, args.id)
        if row["type"] not in ("channel", "group"):
            raise SystemExit("❌ 只有频道和群组支持监听")
        result = check_bot_can_listen(row_dict(row), BotApiClient(get_bot_token()))
        if not result.ok:
            conn.execute(
                "UPDATE entries SET listen_enabled=0, listen_status='error', listen_error=?, listen_checked_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
                (result.message, args.id),
            )
            conn.commit()
            raise SystemExit("❌ " + result.message)
        conn.execute(
            """
            UPDATE entries SET
                listen_enabled=1,
                listen_status='active',
                listen_error=NULL,
                listen_checked_at=datetime('now'),
                telegram_id=COALESCE(?, telegram_id),
                username=COALESCE(NULLIF(?, ''), username),
                updated_at=datetime('now')
            WHERE id=?
            """,
            (result.chat_id, result.chat_username, args.id),
        )
        conn.commit()
    except BotApiError as exc:
        conn.execute(
            "UPDATE entries SET listen_enabled=0, listen_status='error', listen_error=?, listen_checked_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
            (str(exc), args.id),
        )
        conn.commit()
        raise SystemExit(f"❌ 该群组/频道无法启动监听功能，请检查 bot 权限。详情：{exc}")
    finally:
        conn.close()
    print(f"✅ 已开启监听 id={args.id}")


def cmd_disable(args: argparse.Namespace) -> None:
    conn = open_db_with_schema()
    try:
        get_entry(conn, args.id)
        conn.execute(
            "UPDATE entries SET listen_enabled=0, listen_status='off', listen_error=NULL, listen_checked_at=datetime('now'), updated_at=datetime('now') WHERE id=?",
            (args.id,),
        )
        conn.commit()
    finally:
        conn.close()
    print(f"✅ 已关闭监听 id={args.id}")


def cmd_search(args: argparse.Namespace) -> None:
    conn = open_db_with_schema()
    try:
        rows = search_message_index(conn, args.keyword, args.limit)
    finally:
        conn.close()
    if not rows:
        print("未找到消息锚点")
        return
    for index, item in enumerate(rows, 1):
        print(f"{index}. {item['anchor_text']}")
        print(f"   {item['link']}")


def cmd_messages(args: argparse.Namespace) -> None:
    conn = open_db_with_schema()
    try:
        rows = list_message_index_rows(conn, args.keyword or "", args.entry_id, args.limit)
    finally:
        conn.close()
    print(f"共 {len(rows)} 条消息索引")
    for row in rows:
        print(f"{row['id']:>5} entry={row['entry_id']} msg={row['message_id']} {row['chat_title'] or row['entry_title'] or ''}")
        print(f"      {row['link']}")
        print(f"      keywords={' '.join((row['keywords'] or '').split()[:20])}")


def cmd_delete(args: argparse.Namespace) -> None:
    conn = open_db_with_schema()
    try:
        delete_message_index_row(conn, args.id)
    finally:
        conn.close()
    print(f"✅ 已删除消息索引 id={args.id}")


def cmd_clear(args: argparse.Namespace) -> None:
    conn = open_db_with_schema()
    try:
        deleted = clear_message_index(conn, args.entry_id)
    finally:
        conn.close()
    print(f"✅ 已删除 {deleted} 条消息索引")


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="管理 Bot API 消息监听和消息锚点索引")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="初始化消息索引结构")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("list", help="列出频道/群组监听状态")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("enable", help="开启某个资源的监听")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_enable)

    p = sub.add_parser("disable", help="关闭某个资源的监听")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_disable)

    p = sub.add_parser("search", help="搜索消息锚点")
    p.add_argument("keyword")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("messages", help="列出消息索引")
    p.add_argument("--keyword", default="")
    p.add_argument("--entry-id", type=int, default=None)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_messages)

    p = sub.add_parser("delete", help="删除单条消息索引")
    p.add_argument("id", type=int)
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("clear", help="清空消息索引")
    p.add_argument("--entry-id", type=int, default=None)
    p.set_defaults(func=cmd_clear)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
