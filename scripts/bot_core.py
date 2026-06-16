#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot_api_client import ALLOWED_UPDATES, BotApiClient, get_bot_token, load_env_file, retry_sleep
from message_indexer import index_message_if_enabled, open_db_with_schema, query_to_tokens
from search_entries import search_entries

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8899
DEFAULT_SUMMARY_INTERVAL_SECONDS = 300
MAX_REPLY_CHARS = 3900
RESULT_DESC_CHARS = 20
MAX_STORED_MESSAGE_TEXT_CHARS = 1000
ENTRY_EMOJI = {"channel": "📢", "group": "👥", "bot": "🤖"}
MEDIA_EMOJI = {
    "document": "📚",
    "audio": "🎧",
    "voice": "🎧",
    "video": "🎬",
    "video_note": "🎬",
    "animation": "🎬",
    "photo": "📸",
    "text": "📃",
}


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


def e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def compact_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def short_text(value: str | None, limit: int = RESULT_DESC_CHARS) -> str:
    text = compact_text(value)
    if not text:
        return "暂无简介"
    return text if len(text) <= limit else text[:limit] + "…"


def extract_message_text(message: dict[str, Any]) -> str:
    return compact_text(message.get("text") or message.get("caption") or "")


def message_media_type(message: dict[str, Any]) -> str:
    if message.get("document"):
        return "document"
    if message.get("audio"):
        return "audio"
    if message.get("voice"):
        return "voice"
    if message.get("video"):
        return "video"
    if message.get("video_note"):
        return "video_note"
    if message.get("animation"):
        return "animation"
    if message.get("photo"):
        return "photo"
    return "text"


def media_fallback_title(message: dict[str, Any]) -> str:
    kind = message_media_type(message)
    if kind == "document":
        doc = message.get("document") or {}
        return compact_text(doc.get("file_name") or "文件消息")
    if kind == "audio":
        audio = message.get("audio") or {}
        return compact_text(audio.get("title") or audio.get("file_name") or "音频消息")
    if kind == "voice":
        return "语音消息"
    if kind in {"video", "video_note", "animation"}:
        return "视频消息"
    if kind == "photo":
        return "图片消息"
    return "文本消息"


def ensure_message_extra_columns(conn) -> None:
    cols = {str(row["name"]) for row in conn.execute("PRAGMA table_info(message_index)").fetchall()}
    changed = False
    if "text_preview" not in cols:
        conn.execute("ALTER TABLE message_index ADD COLUMN text_preview TEXT")
        changed = True
    if "media_type" not in cols:
        conn.execute("ALTER TABLE message_index ADD COLUMN media_type TEXT")
        changed = True
    if "media_emoji" not in cols:
        conn.execute("ALTER TABLE message_index ADD COLUMN media_emoji TEXT")
        changed = True
    if changed:
        conn.commit()


def save_message_extra_fields(conn, message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if chat_id is None or message_id is None:
        return
    ensure_message_extra_columns(conn)
    text = extract_message_text(message) or media_fallback_title(message)
    kind = message_media_type(message)
    emoji = MEDIA_EMOJI.get(kind, "📃")
    conn.execute(
        """
        UPDATE message_index
        SET text_preview=?, media_type=?, media_emoji=?, updated_at=datetime('now')
        WHERE chat_id=? AND message_id=?
        """,
        (text[:MAX_STORED_MESSAGE_TEXT_CHARS], kind, emoji, int(chat_id), int(message_id)),
    )
    conn.commit()


def index_message_with_text(conn, message: dict[str, Any]) -> bool:
    indexed = index_message_if_enabled(conn, message)
    if indexed:
        save_message_extra_fields(conn, message)
    return indexed


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
    value = compact_text(text)
    if not value:
        return ""
    if value.startswith("/search"):
        return value.split(maxsplit=1)[1].strip() if " " in value else ""
    if value.startswith("/s "):
        return value[3:].strip()
    if value.startswith("/"):
        return ""
    return value


def search_message_results(keyword: str, limit: int = 8) -> list[dict[str, Any]]:
    tokens = query_to_tokens(keyword)
    if not tokens:
        return []
    conn = open_db_with_schema()
    try:
        ensure_message_extra_columns(conn)
        clauses = ["lower(mi.keywords) LIKE ?" for _ in tokens]
        params = [f"%{token.lower()}%" for token in tokens]
        rows = conn.execute(
            f"""
            SELECT mi.*
            FROM message_index mi
            WHERE {' OR '.join(clauses)}
            ORDER BY datetime(COALESCE(mi.message_date, mi.updated_at, mi.created_at)) DESC, mi.id DESC
            LIMIT ?
            """,
            [*params, max(1, min(int(limit or 8), 30))],
        ).fetchall()
    finally:
        conn.close()
    results: list[dict[str, Any]] = []
    for row in rows:
        media_type = row["media_type"] or "text"
        desc = row["text_preview"] or {
            "document": "文件消息",
            "audio": "音频消息",
            "voice": "语音消息",
            "video": "视频消息",
            "video_note": "视频消息",
            "animation": "视频消息",
            "photo": "图片消息",
            "text": "文本消息",
        }.get(media_type, "消息")
        results.append({"kind": "message", "emoji": row["media_emoji"] or MEDIA_EMOJI.get(media_type, "📃"), "title": desc, "url": row["link"], "desc": desc})
    return results


def search_entry_results(keyword: str, limit: int = 6) -> list[dict[str, Any]]:
    result = search_entries(keyword=keyword, limit=limit)
    rows: list[dict[str, Any]] = []
    for item in result.get("items", []):
        entry_type = item.get("type") or ""
        title = item.get("title") or item.get("username") or item.get("url") or "未命名"
        desc = item.get("desc") or item.get("clean_desc") or item.get("description") or title
        rows.append({"kind": "entry", "emoji": ENTRY_EMOJI.get(entry_type, "🔗"), "title": title, "url": item.get("url") or "", "desc": desc})
    return rows


def format_search_reply(keyword: str) -> str:
    results = search_entry_results(keyword, limit=6) + search_message_results(keyword, limit=8)
    if not results:
        return "未找到匹配结果。"
    lines: list[str] = [f"🔎 搜索：{e(keyword)}"]
    for index, item in enumerate(results, 1):
        emoji = item.get("emoji") or "🔗"
        text = short_text(item.get("desc") or item.get("title"), RESULT_DESC_CHARS)
        url = item.get("url") or ""
        display = f"<a href=\"{e(url)}\">{e(text)}</a>" if url else e(text)
        lines.append(f"{index}. {emoji} {display}")
    text = "\n".join(lines).strip()
    if len(text) > MAX_REPLY_CHARS:
        text = text[: MAX_REPLY_CHARS - 20] + "\n……结果过多，已截断。"
    return text


def build_customer_reply(message: dict[str, Any]) -> str | None:
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
        client.send_message(chat_id, format_search_reply(keyword) if keyword else "请输入搜索关键词，例如：/search AI", parse_mode="HTML")
        return "private_search"
    reply = build_customer_reply(message)
    if reply:
        client.send_message(chat_id, reply, parse_mode="HTML")
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
        return "indexed" if index_message_with_text(conn, message) else "ignored"
    finally:
        conn.close()


def apply_result_to_stats(stats: BotStats, result: str) -> None:
    if result == "indexed": stats.indexed += 1
    elif result == "private_search": stats.private_searches += 1
    elif result == "user_reply": stats.user_replies += 1
    else: stats.ignored += 1


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
                    apply_result_to_stats(stats, process_update(update, bot))
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
    def log_message(self, fmt: str, *args: Any) -> None: return
    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/tg-webhook": self.send_json(404, {"ok": False, "error": "not found"}); return
        expected_secret = getattr(self.server, "secret_token", "")
        if expected_secret and self.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != expected_secret:
            self.send_json(403, {"ok": False, "error": "bad secret"}); return
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)); stats = getattr(self.server, "bot_stats", BotStats())
        try:
            update = json.loads(raw.decode("utf-8")); stats.updates += 1; apply_result_to_stats(stats, process_update(update, getattr(self.server, "bot_client")))
        except Exception as exc:
            stats.errors += 1; print(f"⚠️ Webhook 处理失败：{exc}", file=sys.stderr)
        interval = safe_summary_interval(getattr(self.server, "summary_interval", DEFAULT_SUMMARY_INTERVAL_SECONDS)); print_summary(stats, interval); self.server.bot_stats = stats; self.send_json(200, {"ok": True})
    def do_GET(self) -> None:
        self.send_json(200, {"ok": True}) if urllib.parse.urlparse(self.path).path == "/healthz" else self.send_json(404, {"ok": False, "error": "not found"})


def run_webhook_server(host: str, port: int, secret: str = "", summary_interval: int | None = None) -> None:
    load_env_file(); server = ThreadingHTTPServer((host, int(port)), WebhookHandler); server.secret_token = secret; server.bot_client = BotApiClient(get_bot_token()); server.bot_stats = BotStats(); server.summary_interval = safe_summary_interval(summary_interval or load_summary_interval())
    print(f"✅ 统一 bot.py Webhook 服务已启动：http://{host}:{port}/tg-webhook")
    print(f"✅ 一个 Bot 进程处理监听索引 + 私聊搜索回复 + 客户回复入口。终端每 {server.summary_interval} 秒汇总。")
    try: server.serve_forever()
    except KeyboardInterrupt:
        print_summary(server.bot_stats, server.summary_interval, force=True); print("\n已停止 Webhook 服务。")


def main() -> None:
    load_env_file(); parser = argparse.ArgumentParser(description="TG 索引统一 Bot 主程序"); sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("poll", help="本地 long polling 运行统一 Bot"); p.add_argument("--keep-webhook", action="store_true"); p.add_argument("--summary-interval", type=int, default=None)
    p = sub.add_parser("webhook-server", help="启动统一 Bot webhook HTTP 服务"); p.add_argument("--host", default=os.environ.get("BOT_WEBHOOK_HOST", DEFAULT_HOST)); p.add_argument("--port", type=int, default=int(os.environ.get("BOT_WEBHOOK_PORT", DEFAULT_PORT))); p.add_argument("--secret", default=os.environ.get("BOT_WEBHOOK_SECRET", "")); p.add_argument("--summary-interval", type=int, default=None)
    p = sub.add_parser("set-webhook", help="向 Telegram 设置 webhook URL"); p.add_argument("url"); p.add_argument("--secret", default=os.environ.get("BOT_WEBHOOK_SECRET", "")); p.add_argument("--drop-pending-updates", action="store_true")
    p = sub.add_parser("delete-webhook", help="删除 Telegram webhook，切回 polling"); p.add_argument("--drop-pending-updates", action="store_true")
    sub.add_parser("webhook-info", help="查看当前 webhook 状态")
    args = parser.parse_args(); bot = BotApiClient(get_bot_token())
    if args.command == "poll": run_polling(drop_webhook=not args.keep_webhook, summary_interval=args.summary_interval)
    elif args.command == "webhook-server": run_webhook_server(args.host, args.port, args.secret, args.summary_interval)
    elif args.command == "set-webhook": print("✅ webhook 已设置" if bot.set_webhook(args.url, secret_token=args.secret, drop_pending_updates=args.drop_pending_updates) else "❌ webhook 设置失败")
    elif args.command == "delete-webhook": print("✅ webhook 已删除" if bot.delete_webhook(drop_pending_updates=args.drop_pending_updates) else "❌ webhook 删除失败")
    elif args.command == "webhook-info": print(json.dumps(bot.get_webhook_info(), ensure_ascii=False, indent=2))


if __name__ == "__main__": main()
