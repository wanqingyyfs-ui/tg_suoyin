#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import re
import sqlite3
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from search_entries import DB_PATH, search_entries


ROOT_DIR = Path(__file__).resolve().parent.parent
EXPORT_SCRIPT = ROOT_DIR / "scripts" / "export_frontend_data.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_AD_POSITION = "bot_search_inline"
REQUEST_TIMEOUT = 20

USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
COUNT_RE = re.compile(r"([\d\s,\u00a0]+)\s*(subscribers?|members?)", re.IGNORECASE)
TYPE_CHOICES = ("channel", "group", "bot")

DEFAULT_CATEGORIES = [
    "🆕 新发现频道",
    "📰 新闻快讯",
    "💻 数码科技",
    "👨‍💻 开发运维",
    "🔒 信息安全",
    "🧰 软件工具",
    "☁️ 网盘资源",
    "🎬 影视剧集",
    "🎵 音乐音频",
    "🎐 动漫次元",
    "🎮 游戏娱乐",
    "✈️ 科学上网",
    "🪙 加密货币",
    "📚 学习阅读",
    "🎨 创意设计",
    "📡 社媒搬运",
    "🏀 体育运动",
    "👗 生活消费",
    "🌍 地区社群",
    "💬 闲聊交友",
    "🗂️ 综合导航",
    "🌐 综合其他",
    "🤖 机器人",
]


@dataclass
class ScanResult:
    username: str
    url: str
    title: str
    description: str
    entry_type: str
    count: int | None
    private: int
    valid: int
    error: str = ""


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def load_env_file(path: Path = ROOT_DIR / ".env") -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def h(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 数据库不存在: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def normalize_input(raw: str) -> tuple[str, str]:
    value = (raw or "").strip()
    if not value:
        raise ValueError("链接不能为空")

    if value.startswith("@"):
        value = value[1:].strip()
    if value.startswith("t.me/"):
        value = "https://" + value
    if value.startswith("telegram.me/"):
        value = "https://" + value

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value)
        host = (parsed.netloc or "").lower()
        if host not in ("t.me", "www.t.me", "telegram.me", "www.telegram.me"):
            raise ValueError("只支持 t.me 或 telegram.me 链接")

        parts = [part for part in parsed.path.strip("/").split("/") if part]
        if not parts:
            raise ValueError("链接中没有 username")
        if parts[0] in ("joinchat", "+") or parts[0].startswith("+"):
            raise ValueError("暂不支持私密邀请链接，只支持公开 username")
        if parts[0] == "s":
            if len(parts) < 2:
                raise ValueError("/s/ 链接中没有 username")
            username = parts[1]
        else:
            username = parts[0]
    else:
        username = value

    username = username.strip().strip("/")
    if not USERNAME_RE.match(username):
        raise ValueError("username 格式不合法。要求以英文字母开头，只包含字母、数字、下划线，长度 4-32 位")

    return username, f"https://t.me/{username}"


def parse_count(extra_text: str) -> int | None:
    text = (extra_text or "").replace("\u00a0", " ")
    match = COUNT_RE.search(text)
    if not match:
        return None
    digits = re.sub(r"\D", "", match.group(1))
    if not digits:
        return None
    return int(digits)


def infer_type(username: str, extra_text: str, page_text: str) -> str:
    extra = (extra_text or "").casefold()
    page = (page_text or "").casefold()
    if username.casefold().endswith("bot") or " bot" in extra or "telegram bot" in page:
        return "bot"
    if "member" in extra:
        return "group"
    if "subscriber" in extra:
        return "channel"
    return "channel"


def clean_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def scan_telegram_public_page(raw_target: str) -> ScanResult:
    username, url = normalize_input(raw_target)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }

    try:
        response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        return ScanResult(
            username=username,
            url=url,
            title=username,
            description="",
            entry_type="channel",
            count=None,
            private=1,
            valid=0,
            error=f"抓取失败：{exc}",
        )

    soup = BeautifulSoup(response.text, "html.parser")
    title_el = soup.select_one(".tgme_page_title span") or soup.select_one(".tgme_page_title")
    desc_el = soup.select_one(".tgme_page_description")
    extra_el = soup.select_one(".tgme_page_extra")

    og_title = soup.find("meta", attrs={"property": "og:title"})
    og_desc = soup.find("meta", attrs={"property": "og:description"})

    title = clean_text(title_el.get_text(" ", strip=True) if title_el else "")
    if not title and og_title and og_title.get("content"):
        title = clean_text(str(og_title.get("content")))

    description = clean_text(desc_el.get_text(" ", strip=True) if desc_el else "")
    if not description and og_desc and og_desc.get("content"):
        description = clean_text(str(og_desc.get("content")))

    extra_text = clean_text(extra_el.get_text(" ", strip=True) if extra_el else "")
    page_text = clean_text(soup.get_text(" ", strip=True))
    count = parse_count(extra_text)
    entry_type = infer_type(username, extra_text, page_text)

    if not title:
        title = username

    private = 0 if title and (description or extra_text or count is not None) else 1
    valid = 1 if title and not private else 0

    return ScanResult(
        username=username,
        url=url,
        title=title,
        description=description,
        entry_type=entry_type,
        count=count,
        private=private,
        valid=valid,
        error="",
    )



def parse_batch_targets(raw_text: str) -> list[str]:
    targets: list[str] = []
    seen: set[str] = set()

    for raw_line in (raw_text or "").splitlines():
        value = raw_line.strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        targets.append(value)

    return targets


def scan_telegram_batch(raw_text: str) -> list[ScanResult]:
    targets = parse_batch_targets(raw_text)
    if not targets:
        raise ValueError("请至少输入一个 Telegram 公开链接，每行一个")

    results: list[ScanResult] = []
    for target in targets:
        try:
            results.append(scan_telegram_public_page(target))
        except Exception as exc:
            raw_value = target.strip() or "未知链接"
            results.append(
                ScanResult(
                    username=raw_value,
                    url=raw_value,
                    title=raw_value,
                    description="",
                    entry_type="channel",
                    count=None,
                    private=1,
                    valid=0,
                    error=str(exc),
                )
            )

    return results


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_categories_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            sort_order  INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
    conn.commit()


def init_ads_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ads (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            position        TEXT NOT NULL,
            title           TEXT NOT NULL,
            description     TEXT,
            url             TEXT NOT NULL,
            image_url       TEXT,
            sort_order      INTEGER DEFAULT 0,
            enabled         INTEGER DEFAULT 1,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """
    )
    conn.commit()


def db_stats() -> dict[str, int]:
    conn = connect_db()
    stats = {}
    for name in ("links", "entries", "ads"):
        try:
            stats[name] = conn.execute(f"SELECT COUNT(*) AS c FROM {name}").fetchone()["c"]
        except sqlite3.OperationalError:
            stats[name] = 0
    stats["visible_entries"] = conn.execute(
        "SELECT COUNT(*) AS c FROM entries WHERE keep = 1 AND valid = 1 AND private = 0"
    ).fetchone()["c"]
    conn.close()
    return stats


def run_export() -> str:
    completed = subprocess.run(
        [sys.executable, str(EXPORT_SCRIPT)],
        cwd=str(ROOT_DIR),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return (completed.stdout or "") + (completed.stderr or "")


def list_categories() -> list[str]:
    conn = connect_db()
    init_categories_table(conn)
    names = set(DEFAULT_CATEGORIES)

    for row in conn.execute(
        "SELECT DISTINCT category FROM entries WHERE category IS NOT NULL AND TRIM(category) <> ''"
    ).fetchall():
        names.add(row["category"])

    for row in conn.execute("SELECT name FROM categories ORDER BY sort_order ASC, name COLLATE NOCASE").fetchall():
        names.add(row["name"])

    conn.close()
    return sorted(names)


def ensure_category(conn: sqlite3.Connection, name: str) -> None:
    name = (name or "").strip()
    if not name:
        return
    init_categories_table(conn)
    now = now_text()
    conn.execute(
        """
        INSERT OR IGNORE INTO categories (name, sort_order, created_at, updated_at)
        VALUES (?, 0, ?, ?)
        """,
        (name, now, now),
    )


def save_scanned_entry(data: dict[str, str]) -> int:
    username, url = normalize_input(data.get("url") or data.get("username") or "")
    title = clean_text(data.get("title") or username)
    description = clean_text(data.get("description") or "")
    entry_type = data.get("type") if data.get("type") in TYPE_CHOICES else "channel"
    category = clean_text(data.get("category") or "")
    keep = int(data.get("keep", "1"))
    valid = int(data.get("valid", "1"))
    private = int(data.get("private", "0"))

    try:
        count = int(data.get("count") or "")
    except ValueError:
        count = None

    conn = connect_db()
    ensure_category(conn, category)
    now = now_text()

    conn.execute(
        """
        INSERT INTO links (url, username, name, type_hint, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(url) DO UPDATE SET
            username = excluded.username,
            name = excluded.name,
            type_hint = excluded.type_hint,
            updated_at = excluded.updated_at
        """,
        (url, username, title, entry_type, now, now),
    )

    existing = conn.execute(
        "SELECT id, created_at FROM entries WHERE url = ? OR username = ? LIMIT 1",
        (url, username),
    ).fetchone()

    payload = {
        "telegram_id": None,
        "username": username,
        "url": url,
        "type": entry_type,
        "title": title,
        "description": description,
        "clean_title": title,
        "clean_desc": description,
        "category": category or None,
        "avatar": None,
        "count": count,
        "last_active": None,
        "valid": valid,
        "private": private,
        "keep": keep,
        "filter_reason": "",
        "updated_at": now,
    }

    if existing:
        payload["id"] = existing["id"]
        conn.execute(
            """
            UPDATE entries SET
                username = :username,
                url = :url,
                type = :type,
                title = :title,
                description = :description,
                clean_title = :clean_title,
                clean_desc = :clean_desc,
                category = :category,
                count = :count,
                valid = :valid,
                private = :private,
                keep = :keep,
                filter_reason = :filter_reason,
                updated_at = :updated_at
            WHERE id = :id
            """,
            payload,
        )
        entry_id = int(existing["id"])
    else:
        payload["created_at"] = now
        conn.execute(
            """
            INSERT INTO entries (
                telegram_id, username, url, type,
                title, description, clean_title, clean_desc, category, avatar,
                count, last_active, valid, private, keep, filter_reason,
                created_at, updated_at
            ) VALUES (
                :telegram_id, :username, :url, :type,
                :title, :description, :clean_title, :clean_desc, :category, :avatar,
                :count, :last_active, :valid, :private, :keep, :filter_reason,
                :created_at, :updated_at
            )
            """,
            payload,
        )
        entry_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

    conn.commit()
    conn.close()
    return entry_id



def save_scanned_entries(data: dict[str, str]) -> list[int]:
    try:
        total = int(data.get("batch_total") or "0")
    except ValueError:
        total = 0

    if total <= 0:
        return [save_scanned_entry(data)]

    saved_ids: list[int] = []
    for idx in range(total):
        item = {
            "username": data.get(f"username_{idx}", ""),
            "url": data.get(f"url_{idx}", ""),
            "title": data.get(f"title_{idx}", ""),
            "description": data.get(f"description_{idx}", ""),
            "type": data.get(f"type_{idx}", "channel"),
            "count": data.get(f"count_{idx}", ""),
            "category": data.get(f"category_{idx}", ""),
            "keep": data.get(f"keep_{idx}", "1"),
            "valid": data.get(f"valid_{idx}", "1"),
            "private": data.get(f"private_{idx}", "0"),
        }
        if not (item["url"] or item["username"]):
            continue
        saved_ids.append(save_scanned_entry(item))

    return saved_ids


def save_entry(data: dict[str, str]) -> None:
    conn = connect_db()
    category = clean_text(data.get("category") or "")
    ensure_category(conn, category)
    conn.execute(
        """
        UPDATE entries
        SET title = ?, category = ?, keep = ?, valid = ?, private = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            clean_text(data.get("title") or ""),
            category or None,
            int(data.get("keep", "0")),
            int(data.get("valid", "0")),
            int(data.get("private", "0")),
            int(data["id"]),
        ),
    )
    conn.commit()
    conn.close()


def delete_entry(entry_id: int) -> None:
    conn = connect_db()
    row = conn.execute(
        "SELECT id, username, url FROM entries WHERE id = ?",
        (entry_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise ValueError("未找到要删除的频道/群组")

    conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
    conn.execute(
        "DELETE FROM links WHERE url = ? OR username = ?",
        (row["url"], row["username"]),
    )
    conn.commit()
    conn.close()


def category_stats() -> list[dict[str, Any]]:
    conn = connect_db()
    init_categories_table(conn)
    names = list_categories()
    rows = []
    for name in names:
        count = conn.execute("SELECT COUNT(*) AS c FROM entries WHERE category = ?", (name,)).fetchone()["c"]
        rows.append({"name": name, "count": count})
    conn.close()
    return rows


def add_category(name: str) -> None:
    conn = connect_db()
    ensure_category(conn, name)
    conn.commit()
    conn.close()


def rename_category(old_name: str, new_name: str) -> None:
    old_name = clean_text(old_name)
    new_name = clean_text(new_name)
    if not old_name or not new_name:
        raise ValueError("分类名不能为空")
    conn = connect_db()
    init_categories_table(conn)
    now = now_text()
    conn.execute("UPDATE entries SET category = ?, updated_at = ? WHERE category = ?", (new_name, now, old_name))
    conn.execute("DELETE FROM categories WHERE name = ?", (old_name,))
    conn.execute(
        "INSERT OR IGNORE INTO categories (name, sort_order, created_at, updated_at) VALUES (?, 0, ?, ?)",
        (new_name, now, now),
    )
    conn.commit()
    conn.close()


def delete_category(name: str) -> None:
    name = clean_text(name)
    if not name:
        raise ValueError("分类名不能为空")
    conn = connect_db()
    init_categories_table(conn)
    now = now_text()
    conn.execute("UPDATE entries SET category = NULL, updated_at = ? WHERE category = ?", (now, name))
    conn.execute("DELETE FROM categories WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def add_ad(title: str, url: str, description: str, enabled: int, sort_order: int) -> None:
    conn = connect_db()
    init_ads_table(conn)
    now = now_text()
    conn.execute(
        """
        INSERT INTO ads (position, title, description, url, image_url, sort_order, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (DEFAULT_AD_POSITION, clean_text(title)[:30], clean_text(description), clean_text(url), sort_order, enabled, now, now),
    )
    conn.commit()
    conn.close()


def update_ad(data: dict[str, str]) -> None:
    conn = connect_db()
    init_ads_table(conn)
    conn.execute(
        """
        UPDATE ads
        SET title = ?, description = ?, url = ?, sort_order = ?, enabled = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (
            clean_text(data.get("title") or "")[:30],
            clean_text(data.get("description") or ""),
            clean_text(data.get("url") or ""),
            int(data.get("sort_order") or 0),
            int(data.get("enabled", "0")),
            int(data["id"]),
        ),
    )
    conn.commit()
    conn.close()


def delete_ad(ad_id: int) -> None:
    conn = connect_db()
    init_ads_table(conn)
    conn.execute("DELETE FROM ads WHERE id = ?", (ad_id,))
    conn.commit()
    conn.close()


def list_ads() -> list[sqlite3.Row]:
    conn = connect_db()
    init_ads_table(conn)
    rows = conn.execute(
        "SELECT * FROM ads ORDER BY sort_order ASC, id ASC LIMIT 200"
    ).fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class AdminHandler(BaseHTTPRequestHandler):
    server_version = "rectg-admin/0.3"

    def is_authorized(self) -> bool:
        token = getattr(self.server, "admin_token", "")
        if not token:
            return True
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if query.get("token", [""])[0] == token:
            return True
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {token}"

    def auth_suffix(self) -> str:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        token = query.get("token", [""])[0]
        return "?token=" + urllib.parse.quote(token) if token else ""

    def with_auth(self, path: str) -> str:
        suffix = self.auth_suffix()
        if not suffix:
            return path
        joiner = "&" if "?" in path else "?"
        return path + joiner + suffix.lstrip("?")

    def redirect(self, path: str) -> None:
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def send_html(self, body: str, status: int = 200) -> None:
        if not self.is_authorized():
            body = self.layout("未授权", "<div class='panel'>需要 ADMIN_TOKEN。请在 URL 后追加 ?token=你的Token。</div>")
            status = 403
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def parse_post(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        data = urllib.parse.parse_qs(raw)
        return {key: values[0] for key, values in data.items()}

    def layout(self, title: str, content: str) -> str:
        auth_suffix = self.auth_suffix()
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{h(title)} - 万青宝库管理台</title>
<style>
:root{{--bg:#f6f8fb;--panel:#fff;--line:#dfe6ee;--text:#172033;--muted:#64748b;--accent:#229ed9;--danger:#dc2626}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-size:14px}}
main{{max-width:1280px;margin:0 auto;padding:24px}}
a{{color:#168ac1;text-decoration:none}}
h1{{margin:0 0 8px;font-size:24px}}
h2{{margin:0 0 12px;font-size:18px}}
.nav{{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 20px}}
.nav a{{display:inline-flex;align-items:center;min-height:34px;padding:0 12px;border:1px solid var(--line);border-radius:10px;background:var(--panel);font-weight:700}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px;margin:14px 0;box-shadow:0 1px 2px rgba(15,23,42,.04)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}}
.stat{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px}}
.stat b{{display:block;font-size:20px;margin-top:4px}}
.row{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
.stack{{display:grid;gap:8px}}
input,textarea,select,button{{font:inherit;border:1px solid var(--line);border-radius:10px;padding:8px 10px;background:#fff;color:var(--text)}}
textarea{{width:100%;min-height:72px;resize:vertical}}
button{{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:800;cursor:pointer;white-space:nowrap}}
button.secondary{{background:#fff;color:var(--text);border-color:var(--line)}}
button.danger{{background:var(--danger);border-color:var(--danger)}}
.table-wrap{{width:100%;overflow-x:auto;border:1px solid var(--line);border-radius:14px;background:var(--panel)}}
table{{width:100%;border-collapse:collapse;min-width:920px}}
th,td{{border-bottom:1px solid var(--line);padding:10px;text-align:left;vertical-align:top}}
th{{background:#f8fafc;color:#475569;font-size:13px}}
tr:last-child td{{border-bottom:0}}
small,.muted{{color:var(--muted)}}
.entry-title{{width:220px;max-width:100%}}
.category-input{{width:180px}}
.actions-inline{{display:flex;gap:8px;align-items:center;white-space:nowrap}}
.actions-inline form{{display:inline-flex;margin:0}}
.ad-form{{display:grid;grid-template-columns:minmax(140px,1fr) minmax(220px,1.5fr) 90px 90px auto;gap:8px;align-items:start}}
.ad-actions{{display:flex;gap:8px;align-items:center;white-space:nowrap}}
.ad-actions form{{display:inline-flex;margin:0}}
.badge{{display:inline-flex;align-items:center;min-height:24px;padding:0 8px;border-radius:999px;background:#eef6fc;color:#168ac1;font-weight:800}}
@media(max-width:760px){{main{{padding:16px}}.ad-form{{grid-template-columns:1fr}}table{{min-width:860px}}}}
</style>
</head>
<body><main>
<h1>💎 万青宝库管理台</h1>
<div class="muted">本地后台：管理资源、分类、广告，扫描并保存 Telegram 公开频道/群组。</div>
<nav class="nav">
<a href="/{auth_suffix}">资源</a>
<a href="/add{auth_suffix}">添加资源</a>
<a href="/categories{auth_suffix}">分类</a>
<a href="/ads{auth_suffix}">广告</a>
<a href="/export{auth_suffix}">导出 data.json</a>
</nav>
{content}
</main></body></html>"""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/add":
            self.show_add()
            return
        if parsed.path == "/categories":
            self.show_categories()
            return
        if parsed.path == "/ads":
            self.show_ads()
            return
        if parsed.path == "/export":
            output = run_export()
            self.send_html(self.layout("导出", f"<div class='panel'><pre>{h(output)}</pre></div>"))
            return
        self.show_home(parsed)

    def do_POST(self) -> None:
        if not self.is_authorized():
            self.send_html("", status=403)
            return
        parsed = urllib.parse.urlparse(self.path)
        data = self.parse_post()
        try:
            if parsed.path == "/entry/save":
                save_entry(data)
                self.redirect(self.headers.get("Referer") or self.with_auth("/"))
            elif parsed.path == "/entry/delete":
                delete_entry(int(data["id"]))
                self.redirect(self.headers.get("Referer") or self.with_auth("/"))
            elif parsed.path == "/add/scan":
                raw_targets = data.get("urls") or data.get("url", "")
                results = scan_telegram_batch(raw_targets)
                ok_count = sum(1 for item in results if not item.error)
                message = f"扫描完成：成功 {ok_count} 条，失败 {len(results) - ok_count} 条"
                self.show_add(results=results, raw_targets=raw_targets, message=message)
            elif parsed.path == "/add/save":
                saved_ids = save_scanned_entries(data)
                self.show_add(message=f"✅ 已保存 {len(saved_ids)} 条资源。请继续导出 data.json 并构建前端。")
            elif parsed.path == "/categories/add":
                add_category(data.get("name", ""))
                self.redirect(self.with_auth("/categories"))
            elif parsed.path == "/categories/rename":
                rename_category(data.get("old_name", ""), data.get("new_name", ""))
                self.redirect(self.with_auth("/categories"))
            elif parsed.path == "/categories/delete":
                delete_category(data.get("name", ""))
                self.redirect(self.with_auth("/categories"))
            elif parsed.path == "/ads/add":
                add_ad(
                    data.get("title", ""),
                    data.get("url", ""),
                    data.get("description", ""),
                    int(data.get("enabled", "1")),
                    int(data.get("sort_order") or 0),
                )
                self.redirect(self.with_auth("/ads"))
            elif parsed.path == "/ads/update":
                update_ad(data)
                self.redirect(self.with_auth("/ads"))
            elif parsed.path == "/ads/delete":
                delete_ad(int(data["id"]))
                self.redirect(self.with_auth("/ads"))
            else:
                self.send_html(self.layout("未找到", "<div class='panel'>未知操作。</div>"), status=404)
        except Exception as exc:
            self.send_html(self.layout("操作失败", f"<div class='panel'>❌ {h(exc)}</div>"), status=400)

    def category_datalist(self) -> str:
        options = "".join(f"<option value=\"{h(name)}\"></option>" for name in list_categories())
        return f"<datalist id='category-options'>{options}</datalist>"

    def show_home(self, parsed) -> None:
        query = urllib.parse.parse_qs(parsed.query)
        keyword = query.get("q", [""])[0]
        stats = db_stats()
        result = search_entries(keyword, limit=40) if keyword else search_entries("", limit=40)
        categories = self.category_datalist()

        stat_html = "".join(f"<div class='stat'>{h(k)}<b>{v}</b></div>" for k, v in stats.items())
        rows = []
        for item in result["items"]:
            entry_id = str(item["id"])
            form_id = f"entry-save-{entry_id}"
            rows.append(f"""
<tr>
<td>{h(item['id'])}</td>
<td>
<input form="{h(form_id)}" type="hidden" name="id" value="{h(item['id'])}">
<input form="{h(form_id)}" class="entry-title" name="title" value="{h(item['title'])}" placeholder="标题">
<br><small>{h(item['url'])}</small>
</td>
<td><span class="badge">{h(item['type'])}</span></td>
<td><input form="{h(form_id)}" class="category-input" list="category-options" name="category" value="{h(item['category'])}" placeholder="选择或输入分类"></td>
<td>{h(item['countStr'])}</td>
<td>
<form id="{h(form_id)}" method="post" action="{self.with_auth('/entry/save')}"></form>
<div class="row">
<select form="{h(form_id)}" name="keep"><option value="1" {'selected' if item.get('keep', 1) else ''}>keep=1</option><option value="0" {'selected' if not item.get('keep', 1) else ''}>keep=0</option></select>
<select form="{h(form_id)}" name="valid"><option value="1" {'selected' if item.get('valid', 1) else ''}>valid=1</option><option value="0" {'selected' if not item.get('valid', 1) else ''}>valid=0</option></select>
<select form="{h(form_id)}" name="private"><option value="0" {'selected' if not item.get('private', 0) else ''}>private=0</option><option value="1" {'selected' if item.get('private', 0) else ''}>private=1</option></select>
<div class="actions-inline">
<button form="{h(form_id)}">保存</button>
<form method="post" action="{self.with_auth('/entry/delete')}" onsubmit="return confirm('确认永久删除这个频道/群组？会同时从 entries 和 links 移除。')">
<input type="hidden" name="id" value="{h(item['id'])}">
<button class="danger">删除</button>
</form>
</div>
</div>
</td>
</tr>""")

        token_hidden = ""
        token_value = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
        if token_value:
            token_hidden = f'<input type="hidden" name="token" value="{h(token_value)}">'

        content = f"""
{categories}
<div class="grid">{stat_html}</div>
<div class="panel">
<form method="get" class="row">
{token_hidden}
<input name="q" value="{h(keyword)}" placeholder="搜索标题、简介、用户名、分类" size="42">
<button>搜索</button>
<a class="badge" href="{self.with_auth('/add')}">添加频道/群组</a>
</form>
</div>
<div class="panel"><b>当前列表：</b>{h(keyword or '全部')}，共 {result['total']} 条。修改标题、分类、状态后点“保存”；点“删除”会同时从 entries 和 links 移除对应频道/群组。</div>
<div class="table-wrap"><table><thead><tr><th>ID</th><th>标题</th><th>类型</th><th>分类</th><th>人数</th><th>操作</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
"""
        self.send_html(self.layout("资源", content))

    def show_add(
        self,
        results: list[ScanResult] | None = None,
        raw_targets: str = "",
        message: str = "",
    ) -> None:
        categories = self.category_datalist()
        scanned = ""

        if results:
            rows = []
            valid_index = 0
            for result in results:
                if result.error:
                    rows.append(f"""
<tr>
<td>{h(result.url)}</td>
<td colspan="7"><b>扫描失败</b><br><small>{h(result.error)}</small></td>
</tr>""")
                    continue

                idx = valid_index
                valid_index += 1
                count_value = "" if result.count is None else str(result.count)
                type_options = "".join(
                    f"<option value=\"{choice}\" {'selected' if choice == result.entry_type else ''}>{choice}</option>"
                    for choice in TYPE_CHOICES
                )
                rows.append(f"""
<tr>
<td>
<input type="hidden" name="username_{idx}" value="{h(result.username)}">
<input name="url_{idx}" value="{h(result.url)}" size="28">
<br><small>@{h(result.username)}</small>
</td>
<td><input name="title_{idx}" value="{h(result.title)}" maxlength="120" size="24"></td>
<td><textarea name="description_{idx}" rows="2">{h(result.description)}</textarea></td>
<td><select name="type_{idx}">{type_options}</select></td>
<td><input name="count_{idx}" value="{h(count_value)}" size="8"></td>
<td><input list="category-options" name="category_{idx}" placeholder="选择或输入分类" size="18"></td>
<td>
<select name="keep_{idx}"><option value="1" selected>keep=1</option><option value="0">keep=0</option></select><br>
<select name="valid_{idx}"><option value="1" {'selected' if result.valid else ''}>valid=1</option><option value="0" {'selected' if not result.valid else ''}>valid=0</option></select><br>
<select name="private_{idx}"><option value="0" {'selected' if not result.private else ''}>private=0</option><option value="1" {'selected' if result.private else ''}>private=1</option></select>
</td>
</tr>""")

            save_button = ""
            if valid_index > 0:
                save_button = f"""
<input type="hidden" name="batch_total" value="{valid_index}">
<div class="row"><button>保存全部 {valid_index} 条</button></div>
"""

            scanned = f"""
<div class="panel">
<h2>扫描结果</h2>
<form method="post" action="{self.with_auth('/add/save')}" class="stack">
<div class="table-wrap"><table class="scan-table"><thead><tr><th>链接</th><th>标题</th><th>简介</th><th>类型</th><th>人数</th><th>分类</th><th>状态</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
{save_button}
</form>
</div>
"""

        content = f"""
{categories}
<div class="panel">
<h2>批量添加频道/群组</h2>
<p class="muted">每行一个公开 t.me 链接，点“扫描”批量获取名称、简介、人数和类型。扫描后可以逐条调整，再点“保存全部”。暂不支持私密邀请链接。</p>
<form method="post" action="{self.with_auth('/add/scan')}" class="stack">
<textarea name="urls" rows="8" placeholder="https://t.me/username1&#10;https://t.me/username2&#10;@username3" required>{h(raw_targets)}</textarea>
<div class="row"><button>扫描</button></div>
</form>
</div>
{f'<div class="panel">{h(message)}</div>' if message else ''}
{scanned}
"""
        self.send_html(self.layout("添加资源", content))

    def show_categories(self) -> None:
        rows = []
        for item in category_stats():
            rows.append(f"""
<tr>
<td>{h(item['name'])}</td>
<td>{h(item['count'])}</td>
<td class="actions-inline">
<form method="post" action="{self.with_auth('/categories/rename')}">
<input type="hidden" name="old_name" value="{h(item['name'])}">
<input name="new_name" value="{h(item['name'])}" size="24">
<button>保存</button>
</form>
<form method="post" action="{self.with_auth('/categories/delete')}" onsubmit="return confirm('删除分类后，对应资源不会删除，但分类会置空。确认删除？')">
<input type="hidden" name="name" value="{h(item['name'])}">
<button class="danger">删除</button>
</form>
</td>
</tr>""")

        content = f"""
<div class="panel">
<h2>新增分类</h2>
<form method="post" action="{self.with_auth('/categories/add')}" class="row">
<input name="name" placeholder="例如：🌍 东南亚资源" size="32" required>
<button>新增</button>
</form>
</div>
<div class="panel muted">删除分类不会删除频道/群组，只会把对应 entries.category 置空。</div>
<div class="table-wrap"><table><thead><tr><th>分类</th><th>资源数</th><th>操作</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
"""
        self.send_html(self.layout("分类", content))

    def show_ads(self) -> None:
        rows = []
        for ad in list_ads():
            rows.append(f"""
<tr>
<td>{h(ad['id'])}</td>
<td>
<form method="post" action="{self.with_auth('/ads/update')}" class="ad-form">
<input type="hidden" name="id" value="{h(ad['id'])}">
<div class="stack"><input name="title" value="{h(ad['title'])}" maxlength="30" placeholder="广告标题，最多30字"><small>最多 30 字符</small></div>
<div class="stack"><input name="url" value="{h(ad['url'])}" placeholder="https://example.com"><input name="description" value="{h(ad['description'])}" placeholder="说明，可空"></div>
<input name="sort_order" value="{h(ad['sort_order'])}" placeholder="排序">
<select name="enabled"><option value="1" {'selected' if ad['enabled'] else ''}>启用</option><option value="0" {'selected' if not ad['enabled'] else ''}>禁用</option></select>
<div class="ad-actions"><button>保存</button>
</form>
<form method="post" action="{self.with_auth('/ads/delete')}" onsubmit="return confirm('确认删除这个广告？')">
<input type="hidden" name="id" value="{h(ad['id'])}">
<button class="danger">删除</button>
</form></div>
</td>
</tr>""")

        content = f"""
<div class="panel">
<h2>新增 Bot 顶部广告</h2>
<form method="post" action="{self.with_auth('/ads/add')}" class="row">
<input name="title" maxlength="30" placeholder="广告标题，最多30字" required>
<input name="url" placeholder="https://example.com" size="34" required>
<input name="description" placeholder="说明，可空" size="28">
<input name="sort_order" value="0" size="6" placeholder="排序">
<select name="enabled"><option value="1">启用</option><option value="0">禁用</option></select>
<button>新增</button>
</form>
<p class="muted">Bot 每条回复顶部显示启用广告：第 1 条🥇，第 2 条🥈，第 3 条🥉，后续🎖。</p>
</div>
<div class="table-wrap"><table><thead><tr><th>ID</th><th>广告内容 / 操作</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
"""
        self.send_html(self.layout("广告", content))


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="万青宝库本地后台管理页面")
    parser.add_argument("--host", default=os.environ.get("ADMIN_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ADMIN_PORT", DEFAULT_PORT)))
    parser.add_argument("--token", default=os.environ.get("ADMIN_TOKEN", ""))
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), AdminHandler)
    server.admin_token = args.token
    print(f"✅ Admin server: http://{args.host}:{args.port}")
    if args.token:
        print("✅ ADMIN_TOKEN enabled. Open with ?token=你的Token")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止后台")


if __name__ == "__main__":
    main()
