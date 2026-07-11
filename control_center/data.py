from __future__ import annotations

import sys
from datetime import datetime
from typing import Any, Iterable

from .runtime import ROOT_DIR, connect_db, ensure_database_schema, selected_placeholders, table_columns


def _dict_rows(rows: Iterable[Any]) -> list[dict[str, Any]]:
    return [{key: row[key] for key in row.keys()} for row in rows]


def _scripts_path() -> None:
    scripts = ROOT_DIR / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))


def dashboard_stats() -> dict[str, int]:
    ensure_database_schema()
    conn = connect_db(readonly=True)
    try:
        result: dict[str, int] = {}
        for table in ("links", "entries", "ads", "message_index"):
            try:
                result[table] = int(conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])
            except Exception:
                result[table] = 0
        result["visible_entries"] = int(
            conn.execute("SELECT COUNT(*) AS c FROM entries WHERE keep=1 AND valid=1 AND private=0").fetchone()["c"]
        )
        result["active_listening"] = int(
            conn.execute("SELECT COUNT(*) AS c FROM entries WHERE listen_enabled=1 AND listen_status='active'").fetchone()["c"]
        )
        return result
    finally:
        conn.close()


def list_resources(keyword: str = "", limit: int = 3000) -> list[dict[str, Any]]:
    ensure_database_schema()
    conn = connect_db(readonly=True)
    try:
        q = keyword.strip()
        where = ""
        params: list[Any] = []
        if q:
            like = f"%{q}%"
            where = (
                "WHERE e.title LIKE ? OR e.clean_title LIKE ? OR e.clean_desc LIKE ? "
                "OR e.username LIKE ? OR e.category LIKE ? OR e.url LIKE ?"
            )
            params = [like] * 6
        rows = conn.execute(
            f"""
            SELECT e.id,e.title,e.clean_title,e.username,e.url,e.type,e.count,e.category,
                   e.keep,e.valid,e.private,e.telegram_id,e.listen_enabled,e.listen_status,
                   e.listen_error,e.listen_checked_at,e.last_indexed_message_id,e.updated_at,
                   COUNT(mi.id) AS message_count
            FROM entries e
            LEFT JOIN message_index mi ON mi.entry_id=e.id
            {where}
            GROUP BY e.id
            ORDER BY e.id DESC
            LIMIT ?
            """,
            [*params, max(1, min(int(limit), 10000))],
        ).fetchall()
        return _dict_rows(rows)
    finally:
        conn.close()


def update_resource(entry_id: int, values: dict[str, Any]) -> None:
    allowed = {"title", "category", "type", "keep", "valid", "private"}
    payload = {key: values[key] for key in allowed if key in values}
    if not payload:
        return
    if payload.get("type") not in (None, "channel", "group", "bot"):
        raise ValueError("资源类型必须是 channel、group 或 bot")
    assignments = ", ".join(f"{key}=?" for key in payload)
    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            f"UPDATE entries SET {assignments}, updated_at=datetime('now') WHERE id=?",
            [*payload.values(), int(entry_id)],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def batch_update_resources(entry_ids: Iterable[int], field: str, value: Any) -> int:
    if field not in {"category", "keep", "valid", "private", "listen_enabled"}:
        raise ValueError("不允许批量修改该字段")
    placeholders, params = selected_placeholders(int(x) for x in entry_ids)
    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            f"UPDATE entries SET {field}=?, updated_at=datetime('now') WHERE id IN ({placeholders})",
            [value, *params],
        )
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_resources(entry_ids: Iterable[int], *, delete_links: bool = True) -> int:
    placeholders, params = selected_placeholders(int(x) for x in entry_ids)
    conn = connect_db()
    try:
        rows = conn.execute(
            f"SELECT id,url,username FROM entries WHERE id IN ({placeholders})",
            params,
        ).fetchall()
        if not rows:
            return 0
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(f"DELETE FROM message_index WHERE entry_id IN ({placeholders})", params)
        cur = conn.execute(f"DELETE FROM entries WHERE id IN ({placeholders})", params)
        if delete_links:
            urls = [str(row["url"] or "") for row in rows if row["url"]]
            usernames = [str(row["username"] or "") for row in rows if row["username"]]
            if urls:
                marks, vals = selected_placeholders(urls)
                conn.execute(f"DELETE FROM links WHERE url IN ({marks})", vals)
            if usernames:
                marks, vals = selected_placeholders(usernames)
                conn.execute(f"DELETE FROM links WHERE username IN ({marks})", vals)
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_listeners(entry_ids: Iterable[int], enabled: bool) -> dict[str, Any]:
    _scripts_path()
    from admin_dashboard import disable_listener, enable_listener  # type: ignore

    succeeded: list[int] = []
    failed: list[str] = []
    for entry_id in [int(x) for x in entry_ids]:
        try:
            if enabled:
                enable_listener(entry_id)
            else:
                disable_listener(entry_id)
            succeeded.append(entry_id)
        except Exception as exc:
            failed.append(f"#{entry_id}: {exc}")
    return {"succeeded": succeeded, "failed": failed}


def scan_and_add_resources(raw_targets: str) -> dict[str, Any]:
    _scripts_path()
    from admin_dashboard import save_scanned_entry, scan_telegram_batch  # type: ignore

    results = scan_telegram_batch(raw_targets)
    saved: list[int] = []
    failed: list[str] = []
    for result in results:
        if result.error:
            failed.append(f"{result.url}: {result.error}")
            continue
        try:
            saved.append(
                int(
                    save_scanned_entry(
                        {
                            "username": result.username,
                            "url": result.url,
                            "title": result.title,
                            "description": result.description,
                            "type": result.entry_type,
                            "count": "" if result.count is None else str(result.count),
                            "category": "🧭 综合导航",
                            "keep": "1",
                            "valid": str(result.valid),
                            "private": str(result.private),
                        }
                    )
                )
            )
        except Exception as exc:
            failed.append(f"{result.url}: {exc}")
    return {"saved": saved, "failed": failed, "scanned": len(results)}


def list_messages(keyword: str = "", entry_id: int | None = None, limit: int = 3000) -> list[dict[str, Any]]:
    ensure_database_schema()
    conn = connect_db(readonly=True)
    try:
        columns = table_columns(conn, "message_index")
        optional = {
            name: (f"mi.{name}" if name in columns else f"'' AS {name}")
            for name in ("text_preview", "media_type", "media_emoji", "media_meta", "index_source")
        }
        where: list[str] = []
        params: list[Any] = []
        q = keyword.strip()
        if q:
            like = f"%{q}%"
            clauses = ["mi.keywords LIKE ?", "mi.chat_title LIKE ?", "mi.chat_username LIKE ?"]
            params.extend([like, like, like])
            if "text_preview" in columns:
                clauses.append("mi.text_preview LIKE ?")
                params.append(like)
            where.append("(" + " OR ".join(clauses) + ")")
        if entry_id:
            where.append("mi.entry_id=?")
            params.append(int(entry_id))
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        rows = conn.execute(
            f"""
            SELECT mi.id,mi.entry_id,mi.chat_id,mi.message_id,mi.chat_username,mi.chat_title,
                   mi.chat_type,mi.message_date,mi.link,mi.keywords,mi.created_at,mi.updated_at,
                   {optional['text_preview']},{optional['media_type']},{optional['media_emoji']},
                   {optional['media_meta']},{optional['index_source']},
                   e.title AS entry_title,e.url AS entry_url
            FROM message_index mi
            LEFT JOIN entries e ON e.id=mi.entry_id
            {where_sql}
            ORDER BY datetime(COALESCE(mi.message_date,mi.updated_at,mi.created_at)) DESC,mi.id DESC
            LIMIT ?
            """,
            [*params, max(1, min(int(limit), 10000))],
        ).fetchall()
        return _dict_rows(rows)
    finally:
        conn.close()


def delete_messages(message_ids: Iterable[int]) -> int:
    placeholders, params = selected_placeholders(int(x) for x in message_ids)
    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(f"DELETE FROM message_index WHERE id IN ({placeholders})", params)
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def clear_messages_for_entries(entry_ids: Iterable[int]) -> int:
    placeholders, params = selected_placeholders(int(x) for x in entry_ids)
    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(f"DELETE FROM message_index WHERE entry_id IN ({placeholders})", params)
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_ads() -> list[dict[str, Any]]:
    ensure_database_schema()
    conn = connect_db(readonly=True)
    try:
        return _dict_rows(conn.execute("SELECT * FROM ads ORDER BY sort_order ASC,id ASC").fetchall())
    finally:
        conn.close()


def save_ad(values: dict[str, Any], ad_id: int | None = None) -> int:
    title = str(values.get("title") or "").strip()[:30]
    url = str(values.get("url") or "").strip()
    if not title or not url:
        raise ValueError("广告标题和链接不能为空")
    now = datetime.now().isoformat(timespec="seconds")
    payload = (
        str(values.get("position") or "bot_search_inline").strip(),
        title,
        str(values.get("description") or "").strip(),
        url,
        str(values.get("image_url") or "").strip() or None,
        int(values.get("sort_order") or 0),
        int(bool(values.get("enabled", 1))),
    )
    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if ad_id:
            conn.execute(
                "UPDATE ads SET position=?,title=?,description=?,url=?,image_url=?,sort_order=?,enabled=?,updated_at=? WHERE id=?",
                [*payload, now, int(ad_id)],
            )
            result = int(ad_id)
        else:
            cur = conn.execute(
                "INSERT INTO ads(position,title,description,url,image_url,sort_order,enabled,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                [*payload, now, now],
            )
            result = int(cur.lastrowid)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_ads(ad_ids: Iterable[int]) -> int:
    placeholders, params = selected_placeholders(int(x) for x in ad_ids)
    conn = connect_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(f"DELETE FROM ads WHERE id IN ({placeholders})", params)
        conn.commit()
        return int(cur.rowcount or 0)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
