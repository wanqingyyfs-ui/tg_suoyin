#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import shlex
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from search_entries import DB_PATH, TYPE_CHOICES, search_entries


ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"
DEFAULT_LIMIT = 5
MAX_MESSAGE_LENGTH = 3900
BOT_AD_POSITION = "bot_search_inline"

QUERY_CACHE: dict[str, dict[str, Any]] = {}


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def env_int(name: str, default: int) -> int:
    raw_value = os.environ.get(name)
    if not raw_value:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


def escape(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


class TelegramApiError(RuntimeError):
    pass


class TelegramClient:
    def __init__(self, token: str, timeout: int = 30):
        self.token = token
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.session = requests.Session()

    def request(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}/{method}"
        response = self.session.post(url, json=payload or {}, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise TelegramApiError(data.get("description") or f"Telegram API error: {method}")
        return data.get("result")

    def get_updates(self, offset: int | None, timeout: int) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout,
            "limit": 50,
            "allowed_updates": ["message", "callback_query"],
        }
        if offset is not None:
            payload["offset"] = offset
        return self.request("getUpdates", payload) or []

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        reply_to_message_id: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:MAX_MESSAGE_LENGTH],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        self.request("sendMessage", payload)

    def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text[:MAX_MESSAGE_LENGTH],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self.request("editMessageText", payload)

    def answer_callback_query(self, callback_query_id: str, text: str = "") -> None:
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self.request("answerCallbackQuery", payload)


@dataclass
class SearchRequest:
    keyword: str
    entry_type: str | None = None
    category: str | None = None
    page: int = 1
    limit: int = DEFAULT_LIMIT


def load_bot_ads(position: str = BOT_AD_POSITION) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT title, description, url, image_url, sort_order
            FROM ads
            WHERE enabled = 1 AND position = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (position,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    return [
        {
            "title": row["title"] or "广告",
            "description": row["description"] or "",
            "url": row["url"] or "",
            "imageUrl": row["image_url"] or "",
        }
        for row in rows
        if row["url"]
    ]


def make_query_token(request: SearchRequest) -> str:
    raw = json.dumps(
        {
            "keyword": request.keyword,
            "type": request.entry_type,
            "category": request.category,
            "limit": request.limit,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    token = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    QUERY_CACHE[token] = {
        "keyword": request.keyword,
        "entry_type": request.entry_type,
        "category": request.category,
        "limit": request.limit,
    }
    return token


def parse_search_text(text: str) -> SearchRequest:
    text = (text or "").strip()
    if text.startswith("/search"):
        text = text[len("/search"):].strip()

    if not text:
        return SearchRequest(keyword="")

    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()

    entry_type = None
    category = None
    keyword_parts: list[str] = []
    idx = 0

    while idx < len(parts):
        part = parts[idx]
        if part == "--type" and idx + 1 < len(parts):
            candidate = parts[idx + 1].strip().lower()
            if candidate in TYPE_CHOICES:
                entry_type = candidate
            idx += 2
            continue
        if part == "--category" and idx + 1 < len(parts):
            category = parts[idx + 1].strip()
            idx += 2
            continue
        keyword_parts.append(part)
        idx += 1

    return SearchRequest(
        keyword=" ".join(keyword_parts).strip(),
        entry_type=entry_type,
        category=category,
    )


def format_item(index: int, item: dict[str, Any]) -> str:
    desc = " ".join((item.get("desc") or "").split())
    if len(desc) > 80:
        desc = desc[:80].rstrip() + "..."

    lines = [
        f"<b>{index}. {escape(item.get('title'))}</b>",
        f"{escape(item.get('type') or '-')} · {escape(item.get('category') or '-')} · 👥 {escape(item.get('countStr') or '-')}",
    ]
    if desc:
        lines.append(escape(desc))
    lines.append(f"<a href=\"{escape(item.get('url'))}\">打开 Telegram</a>")
    return "\n".join(lines)


def format_ad(ad: dict[str, Any]) -> str:
    lines = [f"<b>广告 · {escape(ad.get('title'))}</b>"]
    if ad.get("description"):
        desc = " ".join(str(ad.get("description") or "").split())
        if len(desc) > 80:
            desc = desc[:80].rstrip() + "..."
        lines.append(escape(desc))
    lines.append(f"<a href=\"{escape(ad.get('url'))}\">查看</a>")
    return "\n".join(lines)


def build_result_message(request: SearchRequest) -> tuple[str, dict[str, Any] | None]:
    result = search_entries(
        keyword=request.keyword,
        entry_type=request.entry_type,
        category=request.category,
        limit=request.limit,
        page=request.page,
    )

    query_title = request.keyword or "全部"
    header = [
        f"🔎 <b>{escape(query_title)}</b>",
        f"共 {result['total']} 条结果 · 第 {result['page']} 页",
    ]

    filters = []
    if request.entry_type:
        filters.append(f"type={request.entry_type}")
    if request.category:
        filters.append(f"category={request.category}")
    if filters:
        header.append("筛选：" + escape("，".join(filters)))

    items = result["items"]
    if not items:
        return "\n".join(header + ["", "没有找到匹配结果。换个关键词试试。"]), None

    start_index = (request.page - 1) * request.limit
    ads = load_bot_ads()
    ad = ads[(request.page - 1) % len(ads)] if ads else None

    body: list[str] = []
    for idx, item in enumerate(items, start=1):
        body.append(format_item(start_index + idx, item))
        if ad and idx == min(3, len(items)):
            body.append(format_ad(ad))

    token = make_query_token(request)
    buttons: list[dict[str, str]] = []
    if request.page > 1:
        buttons.append({"text": "上一页", "callback_data": f"s:{token}:{request.page - 1}"})
    if result["hasMore"]:
        buttons.append({"text": "下一页", "callback_data": f"s:{token}:{request.page + 1}"})

    reply_markup = {"inline_keyboard": [buttons]} if buttons else None
    footer = ["", "用法：关键词 --type channel --category \"💻 数码科技\""]
    return "\n\n".join(["\n".join(header), *body, "\n".join(footer)]), reply_markup


def handle_message(client: TelegramClient, message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    message_id = message.get("message_id")

    if not chat_id or not text:
        return

    if text.startswith("/start") or text.startswith("/help"):
        help_text = (
            "你好，我是 rectg 搜索 Bot。\n\n"
            "直接发送关键词即可搜索 Telegram 中文频道/群组。\n\n"
            "示例：\n"
            "科技\n"
            "AI --type channel\n"
            "影视 --category \"🎬 影视剧集\"\n\n"
            "支持参数：--type channel/group/bot，--category 分类名。"
        )
        client.send_message(chat_id, help_text, reply_to_message_id=message_id)
        return

    request = parse_search_text(text)
    reply_text, reply_markup = build_result_message(request)
    client.send_message(chat_id, reply_text, reply_markup=reply_markup, reply_to_message_id=message_id)


def handle_callback_query(client: TelegramClient, callback_query: dict[str, Any]) -> None:
    callback_id = callback_query.get("id")
    data = callback_query.get("data") or ""
    message = callback_query.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    message_id = message.get("message_id")

    if callback_id:
        client.answer_callback_query(callback_id)

    if not data.startswith("s:") or not chat_id or not message_id:
        return

    try:
        _, token, page_text = data.split(":", 2)
        page = int(page_text)
    except ValueError:
        return

    cached = QUERY_CACHE.get(token)
    if not cached:
        client.send_message(chat_id, "分页状态已失效，请重新发送关键词搜索。")
        return

    request = SearchRequest(
        keyword=cached["keyword"],
        entry_type=cached.get("entry_type"),
        category=cached.get("category"),
        limit=cached.get("limit") or DEFAULT_LIMIT,
        page=page,
    )
    reply_text, reply_markup = build_result_message(request)
    client.edit_message(chat_id, message_id, reply_text, reply_markup=reply_markup)


def run_polling(client: TelegramClient, polling_timeout: int) -> None:
    offset = None
    print("✅ Bot started. Press Ctrl+C to stop.")
    while True:
        try:
            updates = client.get_updates(offset=offset, timeout=polling_timeout)
            for update in updates:
                offset = update["update_id"] + 1
                if "message" in update:
                    handle_message(client, update["message"])
                elif "callback_query" in update:
                    handle_callback_query(client, update["callback_query"])
        except KeyboardInterrupt:
            print("\n已停止 Bot")
            return
        except Exception as exc:
            print(f"❌ Bot loop error: {exc}", file=sys.stderr)
            time.sleep(3)


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="rectg Telegram 搜索 Bot")
    parser.add_argument("--token", default=os.environ.get("TELEGRAM_BOT_TOKEN"), help="Telegram Bot Token，也可写入 .env")
    parser.add_argument("--timeout", type=int, default=env_int("BOT_REQUEST_TIMEOUT", 30), help="HTTP 请求超时秒数")
    parser.add_argument("--polling-timeout", type=int, default=env_int("BOT_POLLING_TIMEOUT", 25), help="getUpdates 长轮询秒数")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("❌ 缺少 TELEGRAM_BOT_TOKEN。请复制 .env.example 为 .env 后填写 Token。")

    client = TelegramClient(args.token, timeout=args.timeout)
    me = client.request("getMe")
    print(f"✅ Logged in as @{me.get('username') or me.get('first_name')}")
    run_polling(client, polling_timeout=args.polling_timeout)


if __name__ == "__main__":
    main()
