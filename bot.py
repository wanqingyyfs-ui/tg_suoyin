#!/usr/bin/env python3
"""TG 索引统一 Bot 入口与 Telegram 搜索交互层。

底层监听、消息索引、Webhook 和命令行功能保留在 bot_core.py；本文件负责
搜索结果相关度、结果总数、按钮筛选和分页。机器人只保留以下六个按钮：
全部、群频、消息、最新、上一页、下一页。
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import bot_core as core
from bot_core import *  # noqa: F401,F403 - 保持原 bot.py 对外接口兼容

RESULTS_PER_PAGE = 14
MAX_SEARCH_CANDIDATES = 5000
QUERY_CACHE_TTL_SECONDS = 86400
QUERY_CACHE_MAX_ITEMS = 2048

MODE_ALL = "all"
MODE_GROUP_CHANNEL = "group_channel"
MODE_MESSAGES = "messages"
SORT_RELEVANCE = "relevance"
SORT_LATEST = "latest"
MODE_CODES = {MODE_ALL: "a", MODE_GROUP_CHANNEL: "g", MODE_MESSAGES: "m"}
CODE_MODES = {value: key for key, value in MODE_CODES.items()}
SORT_CODES = {SORT_RELEVANCE: "r", SORT_LATEST: "l"}
CODE_SORTS = {value: key for key, value in SORT_CODES.items()}
QUERY_CACHE: dict[str, tuple[str, float]] = {}


@dataclass(frozen=True)
class SearchState:
    keyword: str
    mode: str = MODE_ALL
    sort: str = SORT_RELEVANCE
    page: int = 1


@dataclass
class SearchResponse:
    text: str
    reply_markup: dict[str, Any]
    total: int
    page: int
    total_pages: int
    has_more: bool


def _datetime_score(value: Any) -> float:
    text = core.compact_text(str(value or ""))
    if not text:
        return 0.0
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OSError, OverflowError):
        return 0.0


def _relevance_terms(keyword: str) -> list[str]:
    full = core.compact_text(keyword).lower()
    values = [full, *sorted(core.query_to_tokens(keyword), key=lambda item: (-len(item), item))]
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = core.compact_text(value).lower()
        if len(token) < 2 or token in seen:
            continue
        seen.add(token)
        result.append(token)
        if len(result) >= 12:
            break
    return result


def _relevance_score(keyword: str, primary: str = "", secondary: str = "", keyword_bag: str = "") -> int:
    query = core.compact_text(keyword).lower()
    primary_text = core.compact_text(primary).lower()
    secondary_text = core.compact_text(secondary).lower()
    bag_text = core.compact_text(keyword_bag).lower()
    if not query:
        return 0

    score = 0
    if primary_text == query:
        score += 1200
    elif query in primary_text:
        score += 900
    if secondary_text == query:
        score += 800
    elif query in secondary_text:
        score += 650
    if query in bag_text:
        score += 550

    terms = _relevance_terms(keyword)
    matched = 0
    weighted = 0
    for term in terms:
        if term in primary_text or term in secondary_text or term in bag_text:
            matched += 1
            weighted += min(len(term), 8) * 12
    score += min(weighted, 360)
    if terms and matched == len(terms):
        score += 180
    elif matched:
        score += int(120 * matched / len(terms))
    return score


def _entry_type_candidates(
    keyword: str,
    entry_type: str | None,
    sort: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    safe_limit = max(1, min(int(limit), MAX_SEARCH_CANDIDATES))
    batch_size = min(100, safe_limit)
    page = 1
    items: list[dict[str, Any]] = []
    total = 0
    while len(items) < safe_limit:
        result = core.search_entries(
            keyword=keyword,
            entry_type=entry_type,
            limit=batch_size,
            page=page,
            sort="latest" if sort == SORT_LATEST else "relevance",
        )
        if page == 1:
            total = int(result.get("total") or 0)
        batch = result.get("items", [])
        if not batch:
            break
        items.extend(batch)
        if not result.get("hasMore"):
            break
        page += 1
    return items[:safe_limit], total


def _entry_candidates(keyword: str, mode: str, sort: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    entry_types: tuple[str | None, ...] = ("group", "channel") if mode == MODE_GROUP_CHANNEL else (None,)
    candidates: list[dict[str, Any]] = []
    total = 0
    for entry_type in entry_types:
        items, item_total = _entry_type_candidates(keyword, entry_type, sort, limit)
        total += item_total
        for item in items:
            item_type = item.get("type") or ""
            title = item.get("title") or item.get("username") or item.get("url") or "未命名"
            desc = item.get("desc") or item.get("clean_desc") or item.get("description") or title
            primary = " ".join(filter(None, [title, item.get("username") or ""]))
            secondary = " ".join(filter(None, [desc, item.get("category") or "", item.get("url") or ""]))
            score = _relevance_score(keyword, primary, secondary)
            score += max(0, min(int(item.get("score") or 0), 500))
            candidates.append(
                {
                    "emoji": core.ENTRY_EMOJI.get(item_type, "🔗"),
                    "media_meta": "",
                    "url": item.get("url") or "",
                    "desc": desc,
                    "score": score,
                    "timestamp": _datetime_score(item.get("updated_at") or item.get("created_at")),
                    "stable_id": int(item.get("id") or 0),
                }
            )
    return candidates, total


def _message_candidates(keyword: str, sort: str, limit: int) -> tuple[list[dict[str, Any]], int]:
    tokens = core.query_to_tokens(keyword)
    if not tokens:
        return [], 0
    safe_limit = max(1, min(int(limit), MAX_SEARCH_CANDIDATES))
    query_limit = min(
        MAX_SEARCH_CANDIDATES,
        max(safe_limit, RESULTS_PER_PAGE) * (4 if sort == SORT_RELEVANCE else 1),
    )
    conn = core.open_db_with_schema()
    try:
        core.ensure_message_extra_columns(conn)
        clauses = ["lower(mi.keywords) LIKE ?" for _ in tokens]
        params = [f"%{token.lower()}%" for token in tokens]
        where_sql = " OR ".join(clauses)
        total = int(
            conn.execute(
                f"SELECT COUNT(*) AS c FROM message_index mi WHERE {where_sql}",
                params,
            ).fetchone()["c"]
        )
        rows = conn.execute(
            f"""
            SELECT mi.*
            FROM message_index mi
            WHERE {where_sql}
            ORDER BY datetime(COALESCE(mi.message_date, mi.updated_at, mi.created_at)) DESC, mi.id DESC
            LIMIT ?
            """,
            [*params, query_limit],
        ).fetchall()
    finally:
        conn.close()

    results: list[dict[str, Any]] = []
    for row in rows:
        media_type = row["media_type"] or "text"
        desc = row["text_preview"] or core.MEDIA_FALLBACK_TEXT.get(media_type, "消息")
        results.append(
            {
                "emoji": row["media_emoji"] or core.MEDIA_EMOJI.get(media_type, "📃"),
                "media_meta": row["media_meta"] or "",
                "url": row["link"],
                "desc": desc,
                "score": _relevance_score(keyword, secondary=desc, keyword_bag=row["keywords"] or ""),
                "timestamp": _datetime_score(row["message_date"] or row["updated_at"] or row["created_at"]),
                "stable_id": int(row["id"] or 0),
            }
        )
    return results, total


def _cleanup_query_cache() -> None:
    now = time.time()
    for token, (_keyword, updated_at) in list(QUERY_CACHE.items()):
        if now - updated_at > QUERY_CACHE_TTL_SECONDS:
            QUERY_CACHE.pop(token, None)
    if len(QUERY_CACHE) <= QUERY_CACHE_MAX_ITEMS:
        return
    overflow = len(QUERY_CACHE) - QUERY_CACHE_MAX_ITEMS
    for token, _value in sorted(QUERY_CACHE.items(), key=lambda item: item[1][1])[:overflow]:
        QUERY_CACHE.pop(token, None)


def _cache_query(keyword: str) -> str:
    _cleanup_query_cache()
    normalized = core.compact_text(keyword)
    token = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:20]
    QUERY_CACHE[token] = (normalized, time.time())
    return token


def _cached_query(token: str) -> str:
    _cleanup_query_cache()
    cached = QUERY_CACHE.get(token)
    if not cached:
        return ""
    keyword, _updated_at = cached
    QUERY_CACHE[token] = (keyword, time.time())
    return keyword


def _callback_data(token: str, action: str, mode: str, sort: str, page: int) -> str:
    return f"q:{token}:{action}:{MODE_CODES.get(mode, 'a')}:{SORT_CODES.get(sort, 'r')}:{max(1, int(page))}"


def _keyboard(state: SearchState) -> dict[str, Any]:
    token = _cache_query(state.keyword)
    return {
        "inline_keyboard": [
            [
                {"text": "全部", "callback_data": _callback_data(token, "set", MODE_ALL, SORT_RELEVANCE, 1)},
                {"text": "群频", "callback_data": _callback_data(token, "set", MODE_GROUP_CHANNEL, SORT_RELEVANCE, 1)},
                {"text": "消息", "callback_data": _callback_data(token, "set", MODE_MESSAGES, SORT_RELEVANCE, 1)},
                {"text": "最新", "callback_data": _callback_data(token, "set", state.mode, SORT_LATEST, 1)},
            ],
            [
                {"text": "上一页", "callback_data": _callback_data(token, "prev", state.mode, state.sort, max(1, state.page - 1))},
                {"text": "下一页", "callback_data": _callback_data(token, "next", state.mode, state.sort, state.page + 1)},
            ],
        ]
    }


def build_search_response(
    keyword: str,
    mode: str = MODE_ALL,
    sort: str = SORT_RELEVANCE,
    page: int = 1,
) -> SearchResponse:
    keyword = core.compact_text(keyword)
    mode = mode if mode in MODE_CODES else MODE_ALL
    sort = sort if sort in SORT_CODES else SORT_RELEVANCE
    requested_page = max(1, int(page or 1))
    fetch_limit = min(MAX_SEARCH_CANDIDATES, requested_page * RESULTS_PER_PAGE + RESULTS_PER_PAGE)

    entries: list[dict[str, Any]] = []
    entry_total = 0
    if mode in {MODE_ALL, MODE_GROUP_CHANNEL}:
        entries, entry_total = _entry_candidates(keyword, mode, sort, fetch_limit)

    messages: list[dict[str, Any]] = []
    message_total = 0
    if mode in {MODE_ALL, MODE_MESSAGES}:
        messages, message_total = _message_candidates(keyword, sort, fetch_limit)

    total = entry_total + message_total
    total_pages = max(1, (total + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    safe_page = min(requested_page, total_pages)
    results = entries + messages
    key = (
        (lambda item: (item["timestamp"], item["score"], item["stable_id"]))
        if sort == SORT_LATEST
        else (lambda item: (item["score"], item["timestamp"], item["stable_id"]))
    )
    results.sort(key=key, reverse=True)

    start = (safe_page - 1) * RESULTS_PER_PAGE
    page_results = results[start : start + RESULTS_PER_PAGE]
    state = SearchState(keyword=keyword, mode=mode, sort=sort, page=safe_page)
    lines = [f"🔎 搜索：{core.e(keyword)}，总计{total} 条相关结果"]
    if total <= 0:
        lines.append("未找到匹配结果。")
    else:
        ads = core.load_bot_ads()
        if ads:
            for rank, ad in enumerate(ads, 1):
                lines.append(core.format_ad_line(ad, rank))
            lines.append("")
        for number, item in enumerate(page_results, start=start + 1):
            prefix = f"{item.get('emoji') or '🔗'}{item.get('media_meta') or ''}"
            anchor = core.short_text(item.get("desc"), core.RESULT_DESC_CHARS)
            url = item.get("url") or ""
            display = f'<a href="{core.e(url)}">{core.e(anchor)}</a>' if url else core.e(anchor)
            lines.append(f"{number}. {prefix} {display}")

    text = "\n".join(lines).strip()
    return SearchResponse(
        text=text,
        reply_markup=_keyboard(state),
        total=total,
        page=safe_page,
        total_pages=total_pages,
        has_more=safe_page < total_pages,
    )


def format_search_reply(keyword: str) -> str:
    return build_search_response(keyword).text


def _parse_callback(data: str) -> tuple[str, str, str, str, int] | None:
    parts = (data or "").split(":")
    if len(parts) != 6 or parts[0] != "q":
        return None
    _prefix, token, action, mode_code, sort_code, page_text = parts
    mode = CODE_MODES.get(mode_code)
    sort = CODE_SORTS.get(sort_code)
    if action not in {"set", "prev", "next"} or not mode or not sort:
        return None
    try:
        page = max(1, int(page_text))
    except (TypeError, ValueError):
        return None
    return token, action, mode, sort, page


def handle_callback_query(client: core.BotApiClient, callback_query: dict[str, Any]) -> str:
    callback_id = str(callback_query.get("id") or "")
    parsed = _parse_callback(str(callback_query.get("data") or ""))
    message = callback_query.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    message_id = message.get("message_id")
    if not parsed or not callback_id or not chat_id or not message_id:
        if callback_id:
            client.answer_callback_query(callback_id, "按钮状态无效，请重新发送关键词搜索。")
        return "ignored"

    token, action, mode, sort, page = parsed
    keyword = _cached_query(token)
    if not keyword:
        client.answer_callback_query(callback_id, "分页状态已失效，请重新发送关键词搜索。")
        return "user_reply"

    response = build_search_response(keyword, mode=mode, sort=sort, page=page)
    if action == "prev" and page <= 1:
        client.answer_callback_query(callback_id, "已经是第一页。")
        return "user_reply"
    if action == "next" and response.page < page:
        client.answer_callback_query(callback_id, "已经是最后一页。")
        return "user_reply"

    client.answer_callback_query(callback_id)
    client.edit_message(
        chat_id,
        int(message_id),
        response.text,
        parse_mode="HTML",
        reply_markup=response.reply_markup,
    )
    return "user_reply"


def _send_search(
    client: core.BotApiClient,
    chat_id: int | str,
    keyword: str,
    reply_to_message_id: int | None = None,
) -> None:
    response = build_search_response(keyword)
    client.send_message(
        chat_id,
        response.text,
        parse_mode="HTML",
        reply_to_message_id=reply_to_message_id,
        reply_markup=response.reply_markup,
    )


def handle_private_message(client: core.BotApiClient, message: dict[str, Any]) -> str:
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return "not_private"
    chat_id = chat.get("id")
    if not chat_id:
        return "ignored"
    text = str(message.get("text") or "").strip()
    if text.startswith("/start") or text.startswith("/help"):
        client.send_message(
            chat_id,
            "发送关键词即可搜索频道/群组和已监听到的消息锚点。\n"
            "也可以使用：/search 关键词\n"
            "结果下方可使用：全部、群频、消息、最新、上一页、下一页。",
        )
        return "user_reply"
    keyword = core.normalize_query(text)
    if keyword:
        _send_search(client, chat_id, keyword)
        return "private_search" if text.startswith("/search") or text.startswith("/s ") else "user_reply"
    if text.startswith("/search") or text.startswith("/s "):
        client.send_message(chat_id, "请输入搜索关键词，例如：/search AI", parse_mode="HTML")
        return "private_search"
    return "ignored"


def handle_group_message(client: core.BotApiClient, message: dict[str, Any]) -> str:
    chat = message.get("chat") or {}
    if chat.get("type") not in {"group", "supergroup"}:
        return "not_group"
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    if not chat_id:
        return "ignored"
    keyword = core.group_mention_query(client, message)
    if not keyword:
        return "not_group"
    _send_search(client, chat_id, keyword, int(message_id) if message_id else None)
    return "group_search"


def build_customer_reply(message: dict[str, Any]) -> str | None:
    keyword = core.normalize_query(str(message.get("text") or ""))
    return format_search_reply(keyword) if keyword else None


def process_update(update: dict[str, Any], client: core.BotApiClient | None = None) -> str:
    bot = client or core.BotApiClient()
    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        return handle_callback_query(bot, callback_query)
    _kind, message = core.get_update_message(update)
    if not message:
        return "ignored"
    private_result = handle_private_message(bot, message)
    if private_result != "not_private":
        return private_result
    group_result = handle_group_message(bot, message)
    if group_result != "not_group":
        return group_result
    conn = core.open_db_with_schema()
    try:
        return "indexed" if core.index_message_with_text(conn, message) else "ignored"
    finally:
        conn.close()


# 让底层 polling、webhook 和外部导入都使用同一套增强后的处理逻辑。
core.format_search_reply = format_search_reply
core.build_customer_reply = build_customer_reply
core.handle_private_message = handle_private_message
core.handle_group_message = handle_group_message
core.process_update = process_update

run_polling = core.run_polling
run_webhook_server = core.run_webhook_server
main = core.main


if __name__ == "__main__":
    main()
