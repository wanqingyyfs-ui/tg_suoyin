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

from search_entries import DB_PATH, TYPE_CHOICES, TYPE_LABELS, search_entries


ROOT_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT_DIR / ".env"

DEFAULT_LIMIT = 15
MAX_MESSAGE_LENGTH = 3900
BOT_AD_POSITION = "bot_search_inline"
TITLE_MAX_CHARS = 20
AD_TITLE_MAX_CHARS = 30

QUERY_CACHE: dict[str, dict[str, Any]] = {}


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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


def truncate_text(value: str, max_chars: int) -> str:
    value = " ".join((value or "").split())
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "..."


def safe_error_text(error: Exception) -> str:
    text = str(error)
    marker = "/bot"
    if marker in text:
        text = text.split(marker, 1)[0] + "/bot<已隐藏>"
    return text


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
        try:
            response = self.session.post(url, json=payload or {}, timeout=self.timeout)
        except requests.RequestException as exc:
            raise TelegramApiError(f"Telegram 请求失败：{method}：{safe_error_text(exc)}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise TelegramApiError(f"Telegram 返回内容不是 JSON：{method}：HTTP {response.status_code}") from exc

        if not response.ok or not data.get("ok"):
            description = data.get("description") or f"HTTP {response.status_code}"
            raise TelegramApiError(f"Telegram API 报错：{method}：{description}")

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
        try:
            self.request("editMessageText", payload)
        except TelegramApiError as exc:
            if "message is not modified" in str(exc).lower():
                return
            raise

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
    sort: str = "relevance"


def load_bot_ads(position: str = BOT_AD_POSITION) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, title, description, url, image_url, sort_order, position
            FROM ads
            WHERE enabled = 1 AND COALESCE(url, '') != ''
            ORDER BY sort_order ASC, id ASC
            """
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()

    return [
        {
            "id": row["id"],
            "title": row["title"] or "广告",
            "description": row["description"] or "",
            "url": row["url"] or "",
            "imageUrl": row["image_url"] or "",
            "position": row["position"] or position,
            "sortOrder": row["sort_order"] or 0,
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
            "sort": request.sort,
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
        "sort": request.sort,
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
    sort = "relevance"
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
        if part == "--sort" and idx + 1 < len(parts):
            candidate = parts[idx + 1].strip().lower()
            if candidate in ("relevance", "latest"):
                sort = candidate
            idx += 2
            continue
        keyword_parts.append(part)
        idx += 1

    return SearchRequest(
        keyword=" ".join(keyword_parts).strip(),
        entry_type=entry_type,
        category=category,
        sort=sort,
    )


def search_for_request(request: SearchRequest) -> dict[str, Any]:
    return search_entries(
        keyword=request.keyword,
        entry_type=request.entry_type,
        category=request.category,
        limit=request.limit,
        page=request.page,
        sort=request.sort,
    )


def type_icon(entry_type: str) -> str:
    if entry_type == "channel":
        return "📢"
    if entry_type == "group":
        return "👥"
    return "🤖"


def format_item(item: dict[str, Any]) -> str:
    title = truncate_text(item.get("title") or item.get("username") or "未命名", TITLE_MAX_CHARS)
    url = item.get("url") or ""
    icon = type_icon(item.get("type") or "")
    type_label = item.get("typeLabel") or TYPE_LABELS.get(item.get("type"), "资源")
    count = item.get("countStr") or "-"
    return f'{icon} <a href="{escape(url)}">{escape(title)}</a>  {escape(type_label)}｜{escape(count)}'


def format_ads() -> list[str]:
    medals = ["🥇", "🥈", "🥉"]
    lines: list[str] = []
    for idx, ad in enumerate(load_bot_ads(), start=1):
        medal = medals[idx - 1] if idx <= len(medals) else "🎖"
        title = truncate_text(ad.get("title") or "广告", AD_TITLE_MAX_CHARS)
        lines.append(f'{medal} <a href="{escape(ad.get("url"))}">{escape(title)}</a>')
    return lines


def prepend_ads(lines: list[str]) -> list[str]:
    ads = format_ads()
    if not ads:
        return lines
    return [*ads, "", *lines]


def build_keyboard(request: SearchRequest, result: dict[str, Any]) -> dict[str, Any]:
    group_request = SearchRequest(keyword=request.keyword, entry_type="group", category=request.category, limit=request.limit)
    channel_request = SearchRequest(keyword=request.keyword, entry_type="channel", category=request.category, limit=request.limit)
    bot_request = SearchRequest(keyword=request.keyword, entry_type="bot", category=request.category, limit=request.limit)
    latest_request = SearchRequest(keyword=request.keyword, entry_type=None, category=request.category, limit=request.limit, sort="latest")

    first_row = [
        {"text": "👥 群组", "callback_data": f"s:{make_query_token(group_request)}:1"},
        {"text": "📢 频道", "callback_data": f"s:{make_query_token(channel_request)}:1"},
        {"text": "🤖 机器人", "callback_data": f"s:{make_query_token(bot_request)}:1"},
    ]

    second_row: list[dict[str, str]] = [
        {"text": "🆕 最新", "callback_data": f"s:{make_query_token(latest_request)}:1"},
    ]

    if request.page > 1:
        prev_request = SearchRequest(
            keyword=request.keyword,
            entry_type=request.entry_type,
            category=request.category,
            limit=request.limit,
            sort=request.sort,
        )
        second_row.append({"text": "⬅️ 上一页", "callback_data": f"s:{make_query_token(prev_request)}:{request.page - 1}"})

    if result["hasMore"]:
        next_request = SearchRequest(
            keyword=request.keyword,
            entry_type=request.entry_type,
            category=request.category,
            limit=request.limit,
            sort=request.sort,
        )
        second_row.append({"text": "下一页 ➡️", "callback_data": f"s:{make_query_token(next_request)}:{request.page + 1}"})

    return {"inline_keyboard": [first_row, second_row]}


def build_result_message(request: SearchRequest) -> tuple[str, dict[str, Any] | None]:
    result = search_for_request(request)
    query_title = request.keyword or "全部"

    header = [f"🔎 <b>{escape(query_title)}</b>"]
    filters = []
    if request.entry_type:
        filters.append(TYPE_LABELS.get(request.entry_type, request.entry_type))
    if request.sort == "latest":
        filters.append("最新")
    if request.category:
        filters.append(request.category)

    if filters:
        header.append("筛选：" + escape(" / ".join(filters)))
    header.append(f"共 {result['total']} 条结果")

    body: list[str] = []
    body.extend(prepend_ads(header))
    body.append("")

    items = result["items"]
    if not items:
        body.append("没有找到匹配结果。换个关键词试试。")
    else:
        for item in items:
            body.append(format_item(item))

    body.append("")
    body.append(f"👇 点击按钮筛选资源类型【第 {result['page']} 页】")

    return "\n".join(body), build_keyboard(request, result)


def handle_message(client: TelegramClient, message: dict[str, Any]) -> None:
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    message_id = message.get("message_id")

    if not chat_id or not text:
        return

    if text.startswith("/start") or text.startswith("/help"):
        help_text = (
            "你好，我是 TG 索引搜索机器人。\n\n"
            "直接发送关键词即可搜索 Telegram 中文频道、群组和机器人。\n\n"
            "示例：\n"
            "金边美食\n"
            "AI 科技\n"
            "东南亚柬埔寨新闻\n\n"
            "高级用法：\n"
            "/search 影视 --type channel\n"
            "/search AI --type group\n"
            "/search 工具 --sort latest\n\n"
            "按钮说明：群组、频道、机器人用于按类型筛选；最新按更新时间排序。"
        )
        client.send_message(chat_id, "\n".join(prepend_ads([help_text])), reply_to_message_id=message_id)
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
        client.send_message(chat_id, "\n".join(prepend_ads(["分页状态已失效，请重新发送关键词搜索。"])) )
        return

    request = SearchRequest(
        keyword=cached["keyword"],
        entry_type=cached.get("entry_type"),
        category=cached.get("category"),
        limit=cached.get("limit") or DEFAULT_LIMIT,
        sort=cached.get("sort") or "relevance",
        page=page,
    )
    reply_text, reply_markup = build_result_message(request)
    client.edit_message(chat_id, message_id, reply_text, reply_markup=reply_markup)


def run_polling(client: TelegramClient, polling_timeout: int) -> None:
    offset = None
    print("✅ 机器人已启动。按 Ctrl+C 停止。")
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
            print("\n已停止机器人。")
            return
        except Exception as exc:
            print(f"❌ 机器人运行异常：{safe_error_text(exc)}", file=sys.stderr)
            time.sleep(3)


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="TG 索引 Telegram 搜索机器人")
    parser.add_argument("--token", default=os.environ.get("TELEGRAM_BOT_TOKEN"), help="Telegram Bot Token，也可以写入 .env")
    parser.add_argument("--timeout", type=int, default=env_int("BOT_REQUEST_TIMEOUT", 30), help="HTTP 请求超时秒数")
    parser.add_argument("--polling-timeout", type=int, default=env_int("BOT_POLLING_TIMEOUT", 25), help="getUpdates 长轮询秒数")
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("❌ 缺少 TELEGRAM_BOT_TOKEN。请在后台 Bot 配置页保存 Token，或写入 .env，或使用 --token 传入。")

    client = TelegramClient(args.token, timeout=args.timeout)
    me = client.request("getMe")
    print(f"✅ 已登录机器人：@{me.get('username') or me.get('first_name')}")
    run_polling(client, polling_timeout=args.polling_timeout)


if __name__ == "__main__":
    main()
