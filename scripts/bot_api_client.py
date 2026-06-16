#!/usr/bin/env python3
"""Small Telegram Bot API client used by TG 索引.

Only Bot API is used here. No Telegram user-account API is involved.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_TIMEOUT = 20
ALLOWED_UPDATES = ["message", "edited_message", "channel_post", "edited_channel_post"]


class BotApiError(RuntimeError):
    pass


@dataclass
class ListenCheckResult:
    ok: bool
    status: str
    message: str
    chat_id: int | None = None
    chat_username: str = ""
    chat_title: str = ""
    chat_type: str = ""


def load_env_file(path: Path = ROOT_DIR / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def get_bot_token(required: bool = True) -> str:
    load_env_file()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN") or ""
    token = token.strip()
    if required and not token:
        raise BotApiError("请先在 .env 设置 TELEGRAM_BOT_TOKEN=你的BotToken")
    return token


class BotApiClient:
    def __init__(self, token: str | None = None, timeout: int = DEFAULT_TIMEOUT):
        self.token = token or get_bot_token(required=True)
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.session = requests.Session()
        self._me: dict[str, Any] | None = None

    def call(self, method: str, payload: dict[str, Any] | None = None, timeout: int | None = None) -> Any:
        url = f"{self.base_url}/{method}"
        try:
            response = self.session.post(url, json=payload or {}, timeout=timeout or self.timeout)
        except requests.RequestException as exc:
            raise BotApiError(f"Bot API 请求失败：{exc}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise BotApiError(f"Bot API 返回非 JSON：HTTP {response.status_code}") from exc
        if not data.get("ok"):
            description = data.get("description") or f"HTTP {response.status_code}"
            raise BotApiError(str(description))
        return data.get("result")

    def get_me(self) -> dict[str, Any]:
        if self._me is None:
            self._me = self.call("getMe")
        return self._me

    def get_chat(self, chat_id: int | str) -> dict[str, Any]:
        return self.call("getChat", {"chat_id": chat_id})

    def get_chat_member(self, chat_id: int | str, user_id: int) -> dict[str, Any]:
        return self.call("getChatMember", {"chat_id": chat_id, "user_id": user_id})

    def send_message(
        self,
        chat_id: int | str,
        text: str,
        disable_web_page_preview: bool = True,
        parse_mode: str | None = None,
    ) -> Any:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_web_page_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return self.call("sendMessage", payload)

    def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {"timeout": timeout, "allowed_updates": ALLOWED_UPDATES}
        if offset is not None:
            payload["offset"] = offset
        return self.call("getUpdates", payload, timeout=timeout + 10)

    def delete_webhook(self, drop_pending_updates: bool = False) -> bool:
        return bool(self.call("deleteWebhook", {"drop_pending_updates": drop_pending_updates}))

    def set_webhook(self, url: str, secret_token: str = "", drop_pending_updates: bool = False) -> bool:
        payload: dict[str, Any] = {
            "url": url,
            "allowed_updates": ALLOWED_UPDATES,
            "drop_pending_updates": drop_pending_updates,
        }
        if secret_token:
            payload["secret_token"] = secret_token
        return bool(self.call("setWebhook", payload))

    def get_webhook_info(self) -> dict[str, Any]:
        return self.call("getWebhookInfo")


def resolve_chat_ref(entry: dict[str, Any]) -> int | str:
    telegram_id = entry.get("telegram_id")
    if telegram_id:
        return int(telegram_id)
    username = (entry.get("username") or "").strip().lstrip("@")
    if username:
        return f"@{username}"
    raise BotApiError("这个资源缺少 telegram_id 或 username，无法用 Bot API 检查权限")


def check_bot_can_listen(entry: dict[str, Any], client: BotApiClient | None = None) -> ListenCheckResult:
    """Strict listener check: the bot must be administrator/creator.

    This avoids privacy-mode surprises in groups and keeps behavior predictable.
    """
    bot = client or BotApiClient()
    chat_ref = resolve_chat_ref(entry)
    try:
        chat = bot.get_chat(chat_ref)
        me = bot.get_me()
        member = bot.get_chat_member(chat.get("id", chat_ref), int(me["id"]))
    except BotApiError as exc:
        return ListenCheckResult(ok=False, status="error", message=f"该群组/频道无法启动监听功能，请检查 bot 权限。详情：{exc}")

    status = str(member.get("status") or "")
    chat_type = str(chat.get("type") or entry.get("type") or "")
    if status not in {"administrator", "creator"}:
        return ListenCheckResult(
            ok=False,
            status="error",
            message="该群组/频道无法启动监听功能，请检查 bot 权限。要求 bot 是该群组/频道管理员。",
            chat_id=chat.get("id"),
            chat_username=chat.get("username") or "",
            chat_title=chat.get("title") or chat.get("username") or "",
            chat_type=chat_type,
        )

    return ListenCheckResult(
        ok=True,
        status="active",
        message="监听已开启。",
        chat_id=chat.get("id"),
        chat_username=chat.get("username") or "",
        chat_title=chat.get("title") or chat.get("username") or "",
        chat_type=chat_type,
    )


def retry_sleep(seconds: int) -> None:
    time.sleep(max(1, int(seconds)))
