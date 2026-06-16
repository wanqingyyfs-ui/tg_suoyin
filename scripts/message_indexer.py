#!/usr/bin/env python3
"""Bot API message anchor indexing for TG 索引.

This module intentionally does not persist full message bodies. It stores only
message location data plus a compact keyword bag generated from received text.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"

LISTEN_STATUS_OFF = "off"
LISTEN_STATUS_ACTIVE = "active"
LISTEN_STATUS_ERROR = "error"
LISTEN_STATUS_PAUSED = "paused"

SEARCH_RESULT_LIMIT = 10
MAX_KEYWORDS_PER_MESSAGE = 240
MAX_KEYWORD_CHARS = 6000

LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9_+#.\-/]{2,64}")
CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]{2,80}")


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def utc_datetime_text(timestamp: int | None) -> str:
    if not timestamp:
        return now_text()
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat(timespec="seconds")


def connect_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    if not db_path.exists():
        raise SystemExit(f"❌ 数据库不存在：{db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    try:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}
    except sqlite3.OperationalError:
        return set()


def _add_column(conn: sqlite3.Connection, table_name: str, column_sql: str) -> None:
    column_name = column_sql.split()[0]
    if column_name not in _table_columns(conn, table_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}")


def init_message_index_schema(conn: sqlite3.Connection) -> None:
    """Create message-index tables and add listener fields to entries."""
    _add_column(conn, "entries", "listen_enabled INTEGER DEFAULT 0")
    _add_column(conn, "entries", "listen_status TEXT DEFAULT 'off'")
    _add_column(conn, "entries", "listen_error TEXT")
    _add_column(conn, "entries", "listen_checked_at TEXT")
    _add_column(conn, "entries", "last_indexed_message_id INTEGER")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS message_index (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id INTEGER NOT NULL,
            chat_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL,
            chat_username TEXT,
            chat_title TEXT,
            chat_type TEXT,
            message_date TEXT,
            link TEXT NOT NULL,
            keywords TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(chat_id, message_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_message_index_entry_id ON message_index(entry_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_message_index_chat_msg ON message_index(chat_id, message_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_message_index_updated ON message_index(updated_at)")
    conn.commit()


def open_db_with_schema(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = connect_db(db_path)
    init_message_index_schema(conn)
    return conn


def compact_text(value: str | None) -> str:
    return " ".join((value or "").split()).strip()


def extract_index_keywords(text: str | None) -> str:
    """Build a compact keyword bag without storing the original message body."""
    source = compact_text(text)
    if not source:
        return ""

    keywords: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        token = value.strip().lower()
        if len(token) < 2 or token in seen:
            return
        if len(keywords) >= MAX_KEYWORDS_PER_MESSAGE:
            return
        seen.add(token)
        keywords.append(token)

    for token in LATIN_TOKEN_RE.findall(source):
        add(token)

    for run in CJK_RUN_RE.findall(source):
        max_n = min(6, len(run))
        for n in range(2, max_n + 1):
            for i in range(0, len(run) - n + 1):
                add(run[i : i + n])
                if len(keywords) >= MAX_KEYWORDS_PER_MESSAGE:
                    break
            if len(keywords) >= MAX_KEYWORDS_PER_MESSAGE:
                break

    result = " ".join(keywords)
    return result[:MAX_KEYWORD_CHARS]


def query_to_tokens(keyword: str) -> list[str]:
    value = compact_text(keyword).lower()
    if not value:
        return []
    tokens: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        token = token.strip().lower()
        if len(token) >= 2 and token not in seen:
            seen.add(token)
            tokens.append(token)

    for token in LATIN_TOKEN_RE.findall(value):
        add(token)

    cjk = "".join(CJK_RUN_RE.findall(value))
    if cjk:
        add(cjk)
        max_n = min(6, len(cjk))
        for n in range(max_n, 1, -1):
            for i in range(0, len(cjk) - n + 1):
                add(cjk[i : i + n])

    if not tokens and len(value) >= 2:
        add(value)
    return tokens[:30]


def make_message_link(chat_id: int | str, message_id: int, username: str | None = None) -> str:
    clean_username = (username or "").strip().lstrip("@")
    if clean_username:
        return f"https://t.me/{clean_username}/{int(message_id)}"
    chat_text = str(chat_id)
    if chat_text.startswith("-100") and len(chat_text) > 4:
        return f"https://t.me/c/{chat_text[4:]}/{int(message_id)}"
    return ""


def find_listening_entry(conn: sqlite3.Connection, chat: dict[str, Any]) -> sqlite3.Row | None:
    init_message_index_schema(conn)
    chat_id = chat.get("id")
    username = compact_text(chat.get("username"))
    if chat_id is not None:
        row = conn.execute(
            """
            SELECT * FROM entries
            WHERE listen_enabled = 1
              AND listen_status = 'active'
              AND telegram_id = ?
            LIMIT 1
            """,
            (int(chat_id),),
        ).fetchone()
        if row:
            return row
    if username:
        return conn.execute(
            """
            SELECT * FROM entries
            WHERE listen_enabled = 1
              AND listen_status = 'active'
              AND lower(username) = lower(?)
            LIMIT 1
            """,
            (username,),
        ).fetchone()
    return None


def extract_message_text(message: dict[str, Any]) -> str:
    return compact_text(message.get("text") or message.get("caption") or "")


def index_message_if_enabled(conn: sqlite3.Connection, message: dict[str, Any]) -> bool:
    """Index one Bot API Message if its chat is enabled in entries."""
    chat = message.get("chat") or {}
    if not chat:
        return False
    entry = find_listening_entry(conn, chat)
    if not entry:
        return False

    text = extract_message_text(message)
    keywords = extract_index_keywords(text)
    if not keywords:
        return False

    chat_id = int(chat["id"])
    message_id = int(message.get("message_id") or 0)
    if message_id <= 0:
        return False

    username = compact_text(chat.get("username")) or compact_text(entry["username"] if "username" in entry.keys() else "")
    link = make_message_link(chat_id, message_id, username)
    if not link:
        return False

    chat_title = compact_text(chat.get("title") or entry["title"] if "title" in entry.keys() else "")
    chat_type = compact_text(chat.get("type") or entry["type"] if "type" in entry.keys() else "")
    message_date = utc_datetime_text(message.get("date"))
    now = now_text()

    conn.execute(
        """
        INSERT INTO message_index (
            entry_id, chat_id, message_id, chat_username, chat_title, chat_type,
            message_date, link, keywords, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chat_id, message_id) DO UPDATE SET
            entry_id=excluded.entry_id,
            chat_username=excluded.chat_username,
            chat_title=excluded.chat_title,
            chat_type=excluded.chat_type,
            message_date=excluded.message_date,
            link=excluded.link,
            keywords=excluded.keywords,
            updated_at=excluded.updated_at
        """,
        (
            int(entry["id"]),
            chat_id,
            message_id,
            username,
            chat_title,
            chat_type,
            message_date,
            link,
            keywords,
            now,
            now,
        ),
    )
    conn.execute(
        "UPDATE entries SET last_indexed_message_id=?, updated_at=datetime('now') WHERE id=?",
        (message_id, int(entry["id"])),
    )
    conn.commit()
    return True


def search_message_index(conn: sqlite3.Connection, keyword: str, limit: int = SEARCH_RESULT_LIMIT) -> list[dict[str, Any]]:
    init_message_index_schema(conn)
    tokens = query_to_tokens(keyword)
    if not tokens:
        return []
    safe_limit = max(1, min(int(limit or SEARCH_RESULT_LIMIT), 50))
    clauses = ["lower(keywords) LIKE ?" for _ in tokens]
    params = [f"%{token.lower()}%" for token in tokens]
    rows = conn.execute(
        f"""
        SELECT mi.*, e.title AS entry_title, e.username AS entry_username, e.url AS entry_url, e.type AS entry_type
        FROM message_index mi
        LEFT JOIN entries e ON e.id = mi.entry_id
        WHERE {' OR '.join(clauses)}
        ORDER BY datetime(COALESCE(mi.message_date, mi.updated_at, mi.created_at)) DESC, mi.id DESC
        LIMIT ?
        """,
        [*params, safe_limit],
    ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        matched = [token for token in tokens if token.lower() in (row["keywords"] or "").lower()]
        title = row["chat_title"] or row["entry_title"] or row["chat_username"] or "Telegram 消息"
        anchor = f"{title} · 消息 #{row['message_id']}"
        if matched:
            anchor += " · 命中：" + "、".join(matched[:5])
        results.append(
            {
                "id": row["id"],
                "entry_id": row["entry_id"],
                "chat_title": title,
                "chat_username": row["chat_username"] or row["entry_username"] or "",
                "chat_type": row["chat_type"] or row["entry_type"] or "",
                "message_id": row["message_id"],
                "message_date": row["message_date"] or "",
                "link": row["link"],
                "matched_keywords": matched,
                "anchor_text": anchor,
            }
        )
    return results


def message_index_stats(conn: sqlite3.Connection) -> dict[str, int]:
    init_message_index_schema(conn)
    stats: dict[str, int] = {}
    stats["message_index"] = int(conn.execute("SELECT COUNT(*) AS c FROM message_index").fetchone()["c"])
    stats["listening_entries"] = int(conn.execute("SELECT COUNT(*) AS c FROM entries WHERE listen_enabled=1").fetchone()["c"])
    stats["active_listening"] = int(conn.execute("SELECT COUNT(*) AS c FROM entries WHERE listen_enabled=1 AND listen_status='active'").fetchone()["c"])
    stats["listen_errors"] = int(conn.execute("SELECT COUNT(*) AS c FROM entries WHERE listen_status='error'").fetchone()["c"])
    return stats


def list_message_index_rows(conn: sqlite3.Connection, keyword: str = "", entry_id: int | None = None, limit: int = 100) -> list[sqlite3.Row]:
    init_message_index_schema(conn)
    safe_limit = max(1, min(int(limit or 100), 500))
    where: list[str] = []
    params: list[Any] = []
    tokens = query_to_tokens(keyword)
    if tokens:
        where.append("(" + " OR ".join("lower(mi.keywords) LIKE ?" for _ in tokens) + ")")
        params.extend([f"%{token}%" for token in tokens])
    if entry_id:
        where.append("mi.entry_id = ?")
        params.append(int(entry_id))
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    return conn.execute(
        f"""
        SELECT mi.*, e.title AS entry_title, e.url AS entry_url, e.type AS entry_type
        FROM message_index mi
        LEFT JOIN entries e ON e.id = mi.entry_id
        {where_sql}
        ORDER BY datetime(COALESCE(mi.message_date, mi.updated_at, mi.created_at)) DESC, mi.id DESC
        LIMIT ?
        """,
        [*params, safe_limit],
    ).fetchall()


def list_listening_entries(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    init_message_index_schema(conn)
    return conn.execute(
        """
        SELECT e.id, e.title, e.username, e.url, e.type, e.telegram_id,
               e.listen_enabled, e.listen_status, e.listen_error, e.listen_checked_at,
               e.last_indexed_message_id,
               COUNT(mi.id) AS message_count,
               MAX(mi.message_date) AS last_message_date
        FROM entries e
        LEFT JOIN message_index mi ON mi.entry_id = e.id
        WHERE e.type IN ('channel', 'group')
        GROUP BY e.id
        ORDER BY e.listen_enabled DESC, e.listen_status ASC, e.title COLLATE NOCASE
        """
    ).fetchall()


def delete_message_index_row(conn: sqlite3.Connection, row_id: int) -> None:
    init_message_index_schema(conn)
    conn.execute("DELETE FROM message_index WHERE id=?", (int(row_id),))
    conn.commit()


def clear_message_index(conn: sqlite3.Connection, entry_id: int | None = None) -> int:
    init_message_index_schema(conn)
    if entry_id:
        cur = conn.execute("DELETE FROM message_index WHERE entry_id=?", (int(entry_id),))
    else:
        cur = conn.execute("DELETE FROM message_index")
    conn.commit()
    return int(cur.rowcount or 0)
