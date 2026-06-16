#!/usr/bin/env python3
"""TG 索引统一 Bot 主程序。

以后机器人相关开发统一改这个文件：
1. 监听已开启的频道/群组并建立消息索引；
2. 私聊里回复用户搜索结果；
3. 客户回复逻辑也从这里接入；
4. 全程只使用同一个 TELEGRAM_BOT_TOKEN 和 Telegram Bot API。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bot_api_client import ALLOWED_UPDATES, BotApiClient, get_bot_token, load_env_file, retry_sleep
from message_indexer import index_message_if_enabled, open_db_with_schema, search_message_index
from search_entries import TYPE_LABELS, search_entries

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8899
DEFAULT_SUMMARY_INTERVAL_SECONDS = 300
MAX_REPLY_CHARS = 3900


@dataclass
class BotStats:
    window_started_at: float = field(default_factory=time.time)
    updates: int = 0
    indexed: int = 0
    user_replies: int = 0
    private_searches: int = 0
    ignored: int = 0
    errors: int = 0

    def reset(self) -> None:
        self.window_started_at = time.time()
        self.updates = 0
        self.indexed = 0
        self.user_replies = 0
        self.private_searches = 0
        self.ignored = 0
        self.errors = 0


def safe_summary_interval(value: int | str | None = None) -> int:
    try:
        seconds = int(value or os.environ.get("BOT_SUMMARY_INTERVAL_SECONDS") or DEFAULT_SUMMARY_INTERVAL_SECONDS)
    except (TypeError, ValueError):
        seconds = DEFAULT_SUMMARY_INTERVAL_SECONDS
    return max(30, min(seconds, 86400))


def load_summary_interval() -> int:
    try:
        conn = open_db_with_schema()
        try:
            row = conn.execute("SELECT value FROM listener_settings WHERE key='terminal_summary_interval_seconds'").fetchone()
            return safe_summary_interval(row["value"] if row else None)
        finally:
            conn.close()
    except Exception:
        return safe_summary_interval(None)


def print_summary(stats: BotStats, interval_seconds: int, force: bool = False) -> None:
    elapsed = int(time.time() - stats.window_started_at)
    if not force and elapsed < interval_seconds:
        return
    print(
        "📊 Bot 汇总："
        f"最近 {max(elapsed, 0)} 秒，收到更新 {stats.updates} 条，"
        f"收录消息 {stats.indexed} 条，私聊搜索 {stats.private_searches} 次，"
        f"客户回复 {stats.user_replies} 次，忽略 {stats.ignored} 条，错误 {stats.errors} 次。"
    )
    stats.reset()


def get_update_message(update: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
        value = update.get(key)
        if isinstance(value, dict):
            return key, value
    return "", None


def normalize_query(text: str) -> str:
    value = " ".join((text or "").split()).strip()
    if not value:
        return ""
    if value.startswith("/search"):
        return value.split(maxsplit=1)[1].strip() if " " in value else ""
    if value.startswith("/s "):
        return value[3:].strip()
    if value.startswith("/"):
        return ""
    return value


def format_search_reply(keyword: str) -> str:
    entry_result = search_entries(keyword=keyword, limit=6)
    conn = open_db_with_schema()
    try:
        message_hits = search_message_index(conn, keyword, limit=8)
    finally:
        conn.close()

    lines: list[str] = [f"搜索：{keyword}"]
    entries = entry_result.get("items", [])
    if entries:
        lines.append("\n频道 / 群组：")
        for index, item in enumerate(entries, 1):
            title = item.get("title") or item.get("username") or "未命名"
            type_label = item.get("typeLabel") or TYPE_LABELS.get(item.get("type"), item.get("type") or "资源")
            url = item.get("url") or ""
            lines.append(f"{index}. [{type_label}] {title}\n{url}")

    if message_hits:
        lines.append("\n消息锚点：")
        for index, hit in enumerate(message_hits, 1):
            anchor = hit.get("anchor_text") or "相关消息"
            link = hit.get("link") or ""
            lines.append(f"{index}. {anchor}\n{link}")

    if not entries and not message_hits:
        return "未找到匹配结果。"

    text = "\n".join(lines)
    if len(text) > MAX_REPLY_CHARS:
        text = text[: MAX_REPLY_CHARS - 20] + "\n……结果过多，已截断。"
    return text


def build_customer_reply(message: dict[str, Any]) -> str | None:
    """客户回复逻辑入口。

    以后客户自动回复、关键词回复、广告回复、人工客服转接，统一从这里开发。
    当前默认策略：私聊普通文本直接作为搜索关键词回复；如果要接入其它客户回复逻辑，
    不要再开第二个 Bot 进程，直接改这个函数。
    """
    text = str(message.get("text") or "").strip()
    keyword = normalize_query(text)
    if keyword:
        return format_search_reply(keyword)
    return None


def handle_private_message(client: BotApiClient, message: dict[str, Any]) -> str:
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return "not_private"
    chat_id = chat.get("id")
    if not chat_id:
        return "ignored"

    text = str(message.get("text") or "").strip()
    if text.startswith("/start") or text.startswith("/help"):
        client.send_message(chat_id, "发送关键词即可搜索频道/群组和已监听到的消息锚点。\n也可以使用：/search 关键词")
        return "user_reply"

    if text.startswith("/search") or text.startswith("/s "):
        keyword = normalize_query(text)
        client.send_message(chat_id, format_search_reply(keyword) if keyword else "请输入搜索关键词，例如：/search AI")
        return "private_search"

    reply = build_customer_reply(message)
    if reply:
        client.send_message(chat_id, reply)
        return "user_reply"
    return "ignored"


def process_update(update: dict[str, Any], client: BotApiClient | None = None) -> str:
    bot = client or BotApiClient()
    _kind, message = get_update_message(update)
    if not message:
        return "ignored"

    private_result = handle_private_message(bot, message)
    if private_result != "not_private":
        return private_result

    conn = open_db_with_schema()
    try:
        return "indexed" if index_message_if_enabled(conn, message) else "ignored"
    finally:
        conn.close()


def apply_result_to_stats(stats: BotStats, result: str) -> None:
    if result == "indexed":
        stats.indexed += 1
    elif result == "private_search":
        stats.private_searches += 1
    elif result == "user_reply":
        stats.user_replies += 1
    else:
        stats.ignored += 1


def run_polling(drop_webhook: bool = True, summary_interval: int | None = None) -> None:
    load_env_file()
    bot = BotApiClient(get_bot_token())
    if drop_webhook:
        bot.delete_webhook(drop_pending_updates=False)
    stats = BotStats()
    interval = safe_summary_interval(summary_interval or load_summary_interval())
    print("✅ TG 索引统一 bot.py 已启动。按 Ctrl+C 停止。")
    print("✅ 使用同一个 TELEGRAM_BOT_TOKEN 同时处理：监听索引 + 私聊搜索回复 + 客户回复入口。")
    print("✅ allowed_updates:", ", ".join(ALLOWED_UPDATES))
    print(f"✅ 一个 Bot 进程同时监听所有已开启的频道/群组。终端每 {interval} 秒打印一次汇总。")
    offset: int | None = None
    last_interval_reload = time.time()
    while True:
        try:
            updates = bot.get_updates(offset=offset, timeout=30)
            for update in updates:
                stats.updates += 1
                update_id = int(update.get("update_id") or 0)
                if update_id:
                    offset = update_id + 1
                try:
                    result = process_update(update, bot)
                    apply_result_to_stats(stats, result)
                except Exception as exc:
                    stats.errors += 1
                    print(f"⚠️ 处理 update_id={update_id} 失败：{exc}", file=sys.stderr)
            if time.time() - last_interval_reload >= 60:
                interval = safe_summary_interval(summary_interval or load_summary_interval())
                last_interval_reload = time.time()
            print_summary(stats, interval)
        except KeyboardInterrupt:
            print_summary(stats, interval, force=True)
            print("\n已停止 bot.py。")
            return
        except Exception as exc:
            stats.errors += 1
            print(f"⚠️ 轮询异常：{exc}", file=sys.stderr)
            print_summary(stats, interval)
            retry_sleep(5)


class WebhookHandler(BaseHTTPRequestHandler):
    server_version = "tg-suoyin-bot/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/tg-webhook":
            self.send_json(404, {"ok": False, "error": "not found"})
            return
        expected_secret = getattr(self.server, "secret_token", "")
        if expected_secret and self.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != expected_secret:
            self.send_json(403, {"ok": False, "error": "bad secret"})
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        stats = getattr(self.server, "bot_stats", BotStats())
        try:
            update = json.loads(raw.decode("utf-8"))
            stats.updates += 1
            result = process_update(update, getattr(self.server, "bot_client"))
            apply_result_to_stats(stats, result)
        except Exception as exc:
            stats.errors += 1
            print(f"⚠️ Webhook 处理失败：{exc}", file=sys.stderr)
        interval = safe_summary_interval(getattr(self.server, "summary_interval", DEFAULT_SUMMARY_INTERVAL_SECONDS))
        print_summary(stats, interval)
        self.server.bot_stats = stats
        self.send_json(200, {"ok": True})

    def do_GET(self) -> None:
        if urllib.parse.urlparse(self.path).path == "/healthz":
            self.send_json(200, {"ok": True})
        else:
            self.send_json(404, {"ok": False, "error": "not found"})


def run_webhook_server(host: str, port: int, secret: str = "", summary_interval: int | None = None) -> None:
    load_env_file()
    server = ThreadingHTTPServer((host, int(port)), WebhookHandler)
    server.secret_token = secret
    server.bot_client = BotApiClient(get_bot_token())
    server.bot_stats = BotStats()
    server.summary_interval = safe_summary_interval(summary_interval or load_summary_interval())
    print(f"✅ 统一 bot.py Webhook 服务已启动：http://{host}:{port}/tg-webhook")
    print(f"✅ 一个 Bot 进程处理监听索引 + 私聊搜索回复 + 客户回复入口。终端每 {server.summary_interval} 秒汇总。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print_summary(server.bot_stats, server.summary_interval, force=True)
        print("\n已停止 Webhook 服务。")


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="TG 索引统一 Bot 主程序")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("poll", help="本地 long polling 运行统一 Bot")
    p.add_argument("--keep-webhook", action="store_true", help="不主动删除 webhook。通常不要使用。")
    p.add_argument("--summary-interval", type=int, default=None, help="终端汇总打印间隔，秒。默认读取后台设置，初始为300秒。")

    p = sub.add_parser("webhook-server", help="启动统一 Bot webhook HTTP 服务")
    p.add_argument("--host", default=os.environ.get("BOT_WEBHOOK_HOST", DEFAULT_HOST))
    p.add_argument("--port", type=int, default=int(os.environ.get("BOT_WEBHOOK_PORT", DEFAULT_PORT)))
    p.add_argument("--secret", default=os.environ.get("BOT_WEBHOOK_SECRET", ""))
    p.add_argument("--summary-interval", type=int, default=None)

    p = sub.add_parser("set-webhook", help="向 Telegram 设置 webhook URL")
    p.add_argument("url", help="公网 HTTPS URL，例如 https://example.com/tg-webhook")
    p.add_argument("--secret", default=os.environ.get("BOT_WEBHOOK_SECRET", ""))
    p.add_argument("--drop-pending-updates", action="store_true")

    p = sub.add_parser("delete-webhook", help="删除 Telegram webhook，切回 polling")
    p.add_argument("--drop-pending-updates", action="store_true")

    sub.add_parser("webhook-info", help="查看当前 webhook 状态")

    args = parser.parse_args()
    bot = BotApiClient(get_bot_token())
    if args.command == "poll":
        run_polling(drop_webhook=not args.keep_webhook, summary_interval=args.summary_interval)
    elif args.command == "webhook-server":
        run_webhook_server(args.host, args.port, args.secret, args.summary_interval)
    elif args.command == "set-webhook":
        ok = bot.set_webhook(args.url, secret_token=args.secret, drop_pending_updates=args.drop_pending_updates)
        print("✅ webhook 已设置" if ok else "❌ webhook 设置失败")
    elif args.command == "delete-webhook":
        ok = bot.delete_webhook(drop_pending_updates=args.drop_pending_updates)
        print("✅ webhook 已删除" if ok else "❌ webhook 删除失败")
    elif args.command == "webhook-info":
        print(json.dumps(bot.get_webhook_info(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
