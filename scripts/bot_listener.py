#!/usr/bin/env python3
"""TG 索引 Bot API listener.

Commands:
  python scripts/bot_listener.py poll
  python scripts/bot_listener.py webhook-server --host 0.0.0.0 --port 8899 --secret xxx
  python scripts/bot_listener.py set-webhook https://example.com/tg-webhook --secret xxx
  python scripts/bot_listener.py delete-webhook
  python scripts/bot_listener.py webhook-info
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
from typing import Any

from bot_api_client import ALLOWED_UPDATES, BotApiClient, get_bot_token, load_env_file, retry_sleep
from message_indexer import index_message_if_enabled, open_db_with_schema, search_message_index
from search_entries import TYPE_LABELS, search_entries

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8899
MAX_REPLY_CHARS = 3900
DEFAULT_SUMMARY_INTERVAL_SECONDS = 300


@dataclass
class ListenerStats:
    window_started_at: float = field(default_factory=time.time)
    updates: int = 0
    indexed: int = 0
    private_searches: int = 0
    ignored: int = 0
    errors: int = 0

    def reset(self) -> None:
        self.window_started_at = time.time()
        self.updates = 0
        self.indexed = 0
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


def print_summary(stats: ListenerStats, interval_seconds: int, force: bool = False) -> None:
    now = time.time()
    elapsed = int(now - stats.window_started_at)
    if not force and elapsed < interval_seconds:
        return
    print(
        "📊 监听汇总："
        f"最近 {max(elapsed, 0)} 秒，收到更新 {stats.updates} 条，"
        f"收录消息 {stats.indexed} 条，私聊搜索 {stats.private_searches} 次，"
        f"忽略 {stats.ignored} 条，错误 {stats.errors} 次。"
    )
    stats.reset()


def is_message_update(update: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
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


def handle_private_search(client: BotApiClient, message: dict[str, Any]) -> bool:
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return False
    text = str(message.get("text") or "").strip()
    chat_id = chat.get("id")
    if not chat_id:
        return False

    if text.startswith("/start") or text.startswith("/help"):
        client.send_message(
            chat_id,
            "发送关键词即可搜索已收录频道/群组和已监听到的消息锚点。\n也可以使用：/search 关键词",
        )
        return True

    keyword = normalize_query(text)
    if not keyword:
        client.send_message(chat_id, "请输入搜索关键词，例如：/search AI")
        return True

    client.send_message(chat_id, format_search_reply(keyword))
    return True


def process_update(update: dict[str, Any], client: BotApiClient | None = None) -> str:
    bot = client or BotApiClient()
    _update_type, message = is_message_update(update)
    if not message:
        return "ignored"

    if handle_private_search(bot, message):
        return "private_search"

    conn = open_db_with_schema()
    try:
        return "indexed" if index_message_if_enabled(conn, message) else "ignored"
    finally:
        conn.close()


def run_polling(drop_webhook: bool = True, summary_interval: int | None = None) -> None:
    load_env_file()
    bot = BotApiClient(get_bot_token())
    if drop_webhook:
        bot.delete_webhook(drop_pending_updates=False)
    stats = ListenerStats()
    interval = safe_summary_interval(summary_interval or load_summary_interval())
    print("✅ Bot API long polling 已启动。按 Ctrl+C 停止。")
    print("✅ allowed_updates:", ", ".join(ALLOWED_UPDATES))
    print(f"✅ 监听模式：一个 Bot 进程同时监听所有已开启的频道/群组。终端每 {interval} 秒打印一次汇总。")
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
                    if result == "indexed":
                        stats.indexed += 1
                    elif result == "private_search":
                        stats.private_searches += 1
                    else:
                        stats.ignored += 1
                except Exception as exc:
                    stats.errors += 1
                    print(f"⚠️ 处理 update_id={update_id} 失败：{exc}", file=sys.stderr)
            if time.time() - last_interval_reload >= 60:
                interval = safe_summary_interval(summary_interval or load_summary_interval())
                last_interval_reload = time.time()
            print_summary(stats, interval)
        except KeyboardInterrupt:
            print_summary(stats, interval, force=True)
            print("\n已停止 Bot 监听。")
            return
        except Exception as exc:
            stats.errors += 1
            print(f"⚠️ 轮询异常：{exc}", file=sys.stderr)
            print_summary(stats, interval)
            retry_sleep(5)


class WebhookHandler(BaseHTTPRequestHandler):
    server_version = "tg-suoyin-bot-webhook/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/tg-webhook":
            self._send_json(404, {"ok": False, "error": "not found"})
            return
        expected_secret = getattr(self.server, "secret_token", "")
        if expected_secret:
            got_secret = self.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if got_secret != expected_secret:
                self._send_json(403, {"ok": False, "error": "bad secret"})
                return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length)
        stats = getattr(self.server, "listener_stats", ListenerStats())
        try:
            update = json.loads(raw.decode("utf-8"))
            stats.updates += 1
            result = process_update(update, getattr(self.server, "bot_client"))
            if result == "indexed":
                stats.indexed += 1
            elif result == "private_search":
                stats.private_searches += 1
            else:
                stats.ignored += 1
        except Exception as exc:
            stats.errors += 1
            print(f"⚠️ Webhook 处理失败：{exc}", file=sys.stderr)
        interval = safe_summary_interval(getattr(self.server, "summary_interval", DEFAULT_SUMMARY_INTERVAL_SECONDS))
        print_summary(stats, interval)
        self.server.listener_stats = stats
        self._send_json(200, {"ok": True})

    def do_GET(self) -> None:
        if urllib.parse.urlparse(self.path).path == "/healthz":
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"ok": False, "error": "not found"})


def run_webhook_server(host: str, port: int, secret: str = "", summary_interval: int | None = None) -> None:
    load_env_file()
    server = ThreadingHTTPServer((host, int(port)), WebhookHandler)
    server.secret_token = secret
    server.bot_client = BotApiClient(get_bot_token())
    server.listener_stats = ListenerStats()
    server.summary_interval = safe_summary_interval(summary_interval or load_summary_interval())
    print(f"✅ Bot Webhook 本地服务已启动：http://{host}:{port}/tg-webhook")
    print("✅ 健康检查：http://%s:%s/healthz" % (host, port))
    print(f"✅ 监听模式：一个 Bot 进程同时监听所有已开启的频道/群组。终端每 {server.summary_interval} 秒打印一次汇总。")
    if secret:
        print("✅ 已启用 Telegram Secret Token 校验。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print_summary(server.listener_stats, server.summary_interval, force=True)
        print("\n已停止 Webhook 服务。")


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="TG 索引 Bot API 监听服务")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("poll", help="本地 long polling 监听")
    p.add_argument("--keep-webhook", action="store_true", help="不主动删除 webhook。通常不要使用。")
    p.add_argument("--summary-interval", type=int, default=None, help="终端汇总打印间隔，秒。默认读取数据库设置，初始为300秒。")

    p = sub.add_parser("webhook-server", help="启动本地 webhook HTTP 服务")
    p.add_argument("--host", default=os.environ.get("BOT_WEBHOOK_HOST", DEFAULT_HOST))
    p.add_argument("--port", type=int, default=int(os.environ.get("BOT_WEBHOOK_PORT", DEFAULT_PORT)))
    p.add_argument("--secret", default=os.environ.get("BOT_WEBHOOK_SECRET", ""))
    p.add_argument("--summary-interval", type=int, default=None, help="终端汇总打印间隔，秒。默认读取数据库设置，初始为300秒。")

    p = sub.add_parser("set-webhook", help="向 Telegram 设置 webhook URL")
    p.add_argument("url", help="公网 HTTPS URL，例如 https://example.com/tg-webhook")
    p.add_argument("--secret", default=os.environ.get("BOT_WEBHOOK_SECRET", ""))
    p.add_argument("--drop-pending-updates", action="store_true")

    p = sub.add_parser("delete-webhook", help="删除 Telegram webhook，切回 getUpdates")
    p.add_argument("--drop-pending-updates", action="store_true")

    sub.add_parser("webhook-info", help="查看当前 webhook 状态")

    args = parser.parse_args()
    bot = BotApiClient(get_bot_token())

    if args.command == "poll":
        run_polling(drop_webhook=not args.keep_webhook, summary_interval=args.summary_interval)
    elif args.command == "webhook-server":
        run_webhook_server(args.host, args.port, args.secret, summary_interval=args.summary_interval)
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
