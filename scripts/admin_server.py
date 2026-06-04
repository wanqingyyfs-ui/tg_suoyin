#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import sqlite3
import subprocess
import sys
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from search_entries import DB_PATH, search_entries


ROOT_DIR = Path(__file__).resolve().parent.parent
EXPORT_SCRIPT = ROOT_DIR / "scripts" / "export_frontend_data.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_BOT_AD_POSITION = "bot_search_inline"


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
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_ads_position_enabled_sort
        ON ads(position, enabled, sort_order, id)
        """
    )


def init_categories_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL UNIQUE,
            sort_order      INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_categories_sort_name
        ON categories(sort_order, name)
        """
    )

    now = now_text()
    rows = conn.execute(
        """
        SELECT DISTINCT category
        FROM entries
        WHERE category IS NOT NULL AND TRIM(category) != ''
        ORDER BY category COLLATE NOCASE ASC
        """
    ).fetchall()
    for row in rows:
        name = (row["category"] or "").strip()
        if not name:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO categories (name, sort_order, created_at, updated_at)
            VALUES (?, 0, ?, ?)
            """,
            (name, now, now),
        )


def init_admin_tables(conn: sqlite3.Connection) -> None:
    init_ads_table(conn)
    init_categories_table(conn)
    conn.commit()


def db_stats() -> dict[str, int]:
    conn = connect_db()
    init_admin_tables(conn)
    stats = {}
    for name in ("links", "entries", "ads", "categories"):
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


def update_entry(entry_id: int, title: str, category: str, keep: int, valid: int, private: int) -> None:
    category_value = category.strip() or None
    conn = connect_db()
    init_admin_tables(conn)
    conn.execute(
        """
        UPDATE entries
        SET title = ?, category = ?, keep = ?, valid = ?, private = ?, updated_at = ?
        WHERE id = ?
        """,
        (title.strip(), category_value, keep, valid, private, now_text(), entry_id),
    )
    if category_value:
        now = now_text()
        conn.execute(
            """
            INSERT OR IGNORE INTO categories (name, sort_order, created_at, updated_at)
            VALUES (?, 0, ?, ?)
            """,
            (category_value, now, now),
        )
    conn.commit()
    conn.close()


def add_category(name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("分类名不能为空")
    conn = connect_db()
    init_admin_tables(conn)
    now = now_text()
    conn.execute(
        """
        INSERT OR IGNORE INTO categories (name, sort_order, created_at, updated_at)
        VALUES (?, 0, ?, ?)
        """,
        (name, now, now),
    )
    conn.commit()
    conn.close()


def update_category(old_name: str, new_name: str) -> None:
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not old_name or not new_name:
        raise ValueError("分类名不能为空")
    conn = connect_db()
    init_admin_tables(conn)
    now = now_text()
    conn.execute("UPDATE entries SET category = ?, updated_at = ? WHERE category = ?", (new_name, now, old_name))
    conn.execute(
        """
        INSERT OR IGNORE INTO categories (name, sort_order, created_at, updated_at)
        VALUES (?, 0, ?, ?)
        """,
        (new_name, now, now),
    )
    conn.execute("DELETE FROM categories WHERE name = ?", (old_name,))
    conn.commit()
    conn.close()


def delete_category(name: str) -> None:
    name = name.strip()
    if not name:
        raise ValueError("分类名不能为空")
    conn = connect_db()
    init_admin_tables(conn)
    now = now_text()
    conn.execute("UPDATE entries SET category = NULL, updated_at = ? WHERE category = ?", (now, name))
    conn.execute("DELETE FROM categories WHERE name = ?", (name,))
    conn.commit()
    conn.close()


def list_categories() -> list[dict[str, Any]]:
    conn = connect_db()
    init_admin_tables(conn)
    rows = conn.execute(
        """
        SELECT
            c.name,
            c.sort_order,
            COUNT(e.id) AS entry_count
        FROM categories c
        LEFT JOIN entries e ON e.category = c.name
        GROUP BY c.name, c.sort_order
        ORDER BY c.sort_order ASC, c.name COLLATE NOCASE ASC
        """
    ).fetchall()
    conn.close()
    return [
        {"name": row["name"], "sortOrder": row["sort_order"] or 0, "entryCount": row["entry_count"] or 0}
        for row in rows
    ]


def category_options_html() -> str:
    return "".join(f'<option value="{h(row["name"])}"></option>' for row in list_categories())


def add_ad(position: str, title: str, url: str, description: str, enabled: int, sort_order: int = 0) -> None:
    position = DEFAULT_BOT_AD_POSITION
    title = title.strip()
    url = url.strip()
    if not title:
        raise ValueError("广告标题不能为空")
    if len(title) > 30:
        raise ValueError("广告标题最多 30 个字符")
    if not url:
        raise ValueError("广告链接不能为空")
    conn = connect_db()
    init_admin_tables(conn)
    now = now_text()
    conn.execute(
        """
        INSERT INTO ads (position, title, description, url, image_url, sort_order, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (position.strip(), title, description.strip(), url, sort_order, enabled, now, now),
    )
    conn.commit()
    conn.close()


def update_ad(ad_id: int, position: str, title: str, url: str, description: str, enabled: int, sort_order: int) -> None:
    position = DEFAULT_BOT_AD_POSITION
    title = title.strip()
    url = url.strip()
    if not title:
        raise ValueError("广告标题不能为空")
    if len(title) > 30:
        raise ValueError("广告标题最多 30 个字符")
    if not url:
        raise ValueError("广告链接不能为空")
    conn = connect_db()
    init_admin_tables(conn)
    conn.execute(
        """
        UPDATE ads
        SET position = ?, title = ?, description = ?, url = ?, enabled = ?, sort_order = ?, updated_at = ?
        WHERE id = ?
        """,
        (position.strip(), title, description.strip(), url, enabled, sort_order, now_text(), ad_id),
    )
    conn.commit()
    conn.close()


def delete_ad(ad_id: int) -> None:
    conn = connect_db()
    init_admin_tables(conn)
    conn.execute("DELETE FROM ads WHERE id = ?", (ad_id,))
    conn.commit()
    conn.close()


def list_ads() -> list[sqlite3.Row]:
    conn = connect_db()
    init_admin_tables(conn)
    rows = conn.execute(
        """
        SELECT * FROM ads
        ORDER BY sort_order ASC, id ASC
        LIMIT 200
        """
    ).fetchall()
    conn.close()
    return rows


def checked(value: int, expected: int) -> str:
    return "checked" if int(value or 0) == expected else ""


def selected(value: Any, expected: Any) -> str:
    return "selected" if str(value) == str(expected) else ""


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "rectg-admin/0.2"

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
        if not token:
            return ""
        return "?token=" + urllib.parse.quote(token)

    def add_auth_to_action(self, path: str) -> str:
        suffix = self.auth_suffix()
        return path + suffix

    def redirect(self, path: str) -> None:
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def send_html(self, body: str, status: int = 200) -> None:
        if not self.is_authorized():
            body = self.layout("未授权", "<section class='panel danger'><p>需要 ADMIN_TOKEN。请在 URL 后追加 ?token=你的Token，或使用 Authorization: Bearer。</p></section>")
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
<title>{h(title)} - rectg admin</title>
<style>
:root{{--bg:#f5f7fb;--panel:#fff;--line:#dde4eb;--text:#151922;--muted:#657083;--accent:#229ed9;--danger:#d92d20;--ok:#16803c}}
*{{box-sizing:border-box}}
body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:var(--bg);color:var(--text)}}
a{{color:var(--accent);text-decoration:none}}
.header{{position:sticky;top:0;z-index:10;background:rgba(255,255,255,.9);backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}}
.header-inner{{max-width:1280px;margin:0 auto;padding:16px 20px;display:flex;align-items:center;justify-content:space-between;gap:16px}}
.brand{{font-size:20px;font-weight:800}}
.nav{{display:flex;gap:8px;flex-wrap:wrap}}
.nav a{{padding:8px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--text);font-weight:700}}
.nav a:hover{{border-color:var(--accent);color:var(--accent)}}
main{{max-width:1280px;margin:0 auto;padding:22px 20px 44px}}
.panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;margin:16px 0;box-shadow:0 1px 2px rgba(15,23,42,.04)}}
.panel h2{{margin:0 0 14px;font-size:18px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}}
.stat{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px}}
.stat b{{display:block;color:var(--muted);font-size:13px;margin-bottom:6px}}
.stat strong{{font-size:24px}}
.form-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;align-items:end}}
.row-form{{display:flex;gap:8px;flex-wrap:wrap;align-items:center}}
input,select,button,textarea{{font:inherit;padding:9px 10px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--text)}}
input[type="text"],input[type="url"],textarea{{width:100%}}
button{{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:800;cursor:pointer}}
button.secondary{{background:#fff;color:var(--text);border-color:var(--line)}}
button.danger{{background:var(--danger);border-color:var(--danger)}}
.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:14px;background:#fff}}
table{{width:100%;border-collapse:collapse;min-width:980px}}
th,td{{border-bottom:1px solid var(--line);padding:10px;text-align:left;vertical-align:top}}
th{{background:#f8fafc;color:var(--muted);font-size:13px;white-space:nowrap}}
tr:last-child td{{border-bottom:0}}
small,.muted{{color:var(--muted)}}
.title-input{{min-width:220px}}
.category-input{{min-width:180px}}
.badge{{display:inline-flex;align-items:center;padding:3px 8px;border-radius:999px;background:#eef6fb;color:#1275a8;font-weight:800;font-size:12px}}
.danger-text{{color:var(--danger)}}
.success-text{{color:var(--ok)}}
.actions{{display:flex;gap:8px;flex-wrap:wrap}}
pre{{white-space:pre-wrap;word-break:break-word;background:#0f172a;color:#e2e8f0;padding:16px;border-radius:12px}}
@media(max-width:760px){{.header-inner{{align-items:flex-start;flex-direction:column}}main{{padding:16px}}.panel{{padding:14px}}}}
</style>
</head>
<body>
<header class="header"><div class="header-inner">
<div class="brand">rectg 本地管理</div>
<nav class="nav">
<a href="/{auth_suffix}">资源</a>
<a href="/categories{auth_suffix}">分类</a>
<a href="/ads{auth_suffix}">广告</a>
<a href="/export{auth_suffix}">导出 data.json</a>
</nav>
</div></header>
<main>{content}</main>
</body></html>"""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/ads":
            self.show_ads()
            return
        if parsed.path == "/categories":
            self.show_categories()
            return
        if parsed.path == "/export":
            output = run_export()
            self.send_html(self.layout("导出", f"<section class='panel'><h2>导出结果</h2><pre>{h(output)}</pre></section>"))
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
                update_entry(
                    entry_id=int(data["id"]),
                    title=data.get("title", ""),
                    category=data.get("category", ""),
                    keep=int(data.get("keep", "0")),
                    valid=int(data.get("valid", "0")),
                    private=int(data.get("private", "0")),
                )
            elif parsed.path == "/categories/add":
                add_category(data.get("name", ""))
            elif parsed.path == "/categories/update":
                update_category(data.get("old_name", ""), data.get("new_name", ""))
            elif parsed.path == "/categories/delete":
                delete_category(data.get("name", ""))
            elif parsed.path == "/ads/add":
                add_ad(
                    data.get("position", "bot_search_inline"),
                    data.get("title", ""),
                    data.get("url", ""),
                    data.get("description", ""),
                    int(data.get("enabled", "1")),
                    int(data.get("sort_order", "0") or 0),
                )
            elif parsed.path == "/ads/update":
                update_ad(
                    int(data["id"]),
                    data.get("position", "bot_search_inline"),
                    data.get("title", ""),
                    data.get("url", ""),
                    data.get("description", ""),
                    int(data.get("enabled", "0")),
                    int(data.get("sort_order", "0") or 0),
                )
            elif parsed.path == "/ads/delete":
                delete_ad(int(data["id"]))
        except Exception as exc:
            self.send_html(self.layout("操作失败", f"<section class='panel danger'><h2>操作失败</h2><p class='danger-text'>❌ {h(exc)}</p></section>"), status=400)
            return
        self.redirect(self.headers.get("Referer") or "/")

    def show_home(self, parsed) -> None:
        query = urllib.parse.parse_qs(parsed.query)
        keyword = query.get("q", [""])[0]
        auth_suffix = self.auth_suffix()
        stats = db_stats()
        result = search_entries(keyword, limit=40) if keyword else search_entries("", limit=40)
        options = category_options_html()

        stat_html = "".join(f"<div class='stat'><b>{h(k)}</b><strong>{v}</strong></div>" for k, v in stats.items())
        rows = []
        for item in result["items"]:
            rows.append(f"""
<tr>
<td><span class="badge">#{h(item['id'])}</span></td>
<td>
<form id="entry-{h(item['id'])}" method="post" action="/entry/save{auth_suffix}">
<input type="hidden" name="id" value="{h(item['id'])}">
<input class="title-input" name="title" value="{h(item['title'])}" placeholder="标题">
<br><small>{h(item['url'])}</small>
</form>
</td>
<td>{h(item['type'])}</td>
<td><input class="category-input" form="entry-{h(item['id'])}" list="category-options" name="category" value="{h(item['category'])}" placeholder="点击选择或输入分类"></td>
<td>{h(item['countStr'])}</td>
<td>
<div class="row-form">
<select form="entry-{h(item['id'])}" name="keep"><option value="1" {selected(1, 1)}>keep=1</option><option value="0">keep=0</option></select>
<select form="entry-{h(item['id'])}" name="valid"><option value="1" {selected(1, 1)}>valid=1</option><option value="0">valid=0</option></select>
<select form="entry-{h(item['id'])}" name="private"><option value="0" {selected(0, 0)}>private=0</option><option value="1">private=1</option></select>
<button form="entry-{h(item['id'])}">保存</button>
</div>
</td>
</tr>""")

        token_hidden = ""
        token_value = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
        if token_value:
            token_hidden = f'<input type="hidden" name="token" value="{h(token_value)}">'

        content = f"""
<section class="stats">{stat_html}</section>
<section class="panel">
<h2>资源搜索</h2>
<form method="get" class="form-grid">
<div>
<label class="muted">关键词</label>
<input name="q" value="{h(keyword)}" placeholder="搜索 entries，例如 AI科技 / 金边美食">
</div>
<div class="actions">
{token_hidden}
<button>搜索</button>
<a class="badge" href="/{auth_suffix}">清空</a>
</div>
</form>
</section>
<section class="panel">
<h2>资源列表 <small>当前：{h(keyword or '全部')}，共 {result['total']} 条</small></h2>
<datalist id="category-options">{options}</datalist>
<div class="table-wrap">
<table><thead><tr><th>ID</th><th>标题</th><th>类型</th><th>分类</th><th>人数</th><th>操作</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</div>
<p class="muted">说明：点击分类输入框可以选择已有分类，也可以输入新分类；保存会同时保存标题、分类、keep、valid、private。</p>
</section>
"""
        self.send_html(self.layout("资源", content))

    def show_categories(self) -> None:
        auth_suffix = self.auth_suffix()
        rows = []
        for category in list_categories():
            name = category["name"]
            rows.append(f"""
<tr>
<td>{h(name)}</td>
<td>{h(category['entryCount'])}</td>
<td>
<form method="post" action="/categories/update{auth_suffix}" class="row-form">
<input type="hidden" name="old_name" value="{h(name)}">
<input name="new_name" value="{h(name)}" size="28">
<button>保存</button>
</form>
</td>
<td>
<form method="post" action="/categories/delete{auth_suffix}" onsubmit="return confirm('删除分类后，该分类下资源会保留，但 category 会被置空。确认删除？')">
<input type="hidden" name="name" value="{h(name)}">
<button class="danger">删除</button>
</form>
</td>
</tr>""")

        content = f"""
<section class="panel">
<h2>新增分类</h2>
<form method="post" action="/categories/add{auth_suffix}" class="row-form">
<input name="name" placeholder="例如 💻 数码科技" size="32">
<button>新增分类</button>
</form>
<p class="muted">新增分类会进入后台可选列表。只有当资源使用这个分类后，前端导出才会展示该分类。</p>
</section>
<section class="panel">
<h2>分类管理</h2>
<div class="table-wrap">
<table><thead><tr><th>分类</th><th>资源数</th><th>改名</th><th>删除</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</div>
<p class="muted">删除分类不会删除频道/群组，只会把对应资源的 category 置空。</p>
</section>
"""
        self.send_html(self.layout("分类", content))

    def show_ads(self) -> None:
        auth_suffix = self.auth_suffix()
        rows = []
        for ad in list_ads():
            rows.append(f"""
<tr>
<td><span class="badge">#{h(ad['id'])}</span></td>
<td><input form="ad-{h(ad['id'])}" name="sort_order" type="number" value="{h(ad['sort_order'])}" style="width:80px"></td>
<td><input form="ad-{h(ad['id'])}" name="title" value="{h(ad['title'])}" maxlength="30" size="26"></td>
<td><input form="ad-{h(ad['id'])}" name="url" value="{h(ad['url'])}" size="32"></td>
<td><input form="ad-{h(ad['id'])}" name="description" value="{h(ad['description'])}" size="26"></td>
<td>
<select form="ad-{h(ad['id'])}" name="enabled">
<option value="1" {selected(ad['enabled'], 1)}>启用</option>
<option value="0" {selected(ad['enabled'], 0)}>禁用</option>
</select>
</td>
<td>
<form id="ad-{h(ad['id'])}" method="post" action="/ads/update{auth_suffix}">
<input type="hidden" name="id" value="{h(ad['id'])}">
</form>
<div class="actions">
<button form="ad-{h(ad['id'])}">保存</button>
<form method="post" action="/ads/delete{auth_suffix}" onsubmit="return confirm('确认删除这条广告？')">
<input type="hidden" name="id" value="{h(ad['id'])}">
<button class="danger">删除</button>
</form>
</div>
</td>
</tr>""")

        content = f"""
<section class="panel">
<h2>新增广告</h2>
<form method="post" action="/ads/add{auth_suffix}" class="form-grid">
<div><label class="muted">排序</label><input name="sort_order" type="number" value="0"></div>
<div><label class="muted">标题，最多 30 字</label><input name="title" placeholder="广告标题" maxlength="30"></div>
<div><label class="muted">链接</label><input name="url" placeholder="https://example.com"></div>
<div><label class="muted">说明</label><input name="description" placeholder="可选说明"></div>
<div><label class="muted">状态</label><select name="enabled"><option value="1">启用</option><option value="0">禁用</option></select></div>
<div><button>新增广告</button></div>
</form>
<p class="muted">后台广告统一用于 Bot 回复顶部展示。Bot 每次回复都会优先显示启用广告，并按 sort_order 和 id 排序：第 1 条🥇、第 2 条🥈、第 3 条🥉、之后🎖。</p>
</section>
<section class="panel">
<h2>广告列表</h2>
<div class="table-wrap">
<table><thead><tr><th>ID</th><th>排序</th><th>标题</th><th>链接</th><th>说明</th><th>状态</th><th>操作</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
</div>
</section>
"""
        self.send_html(self.layout("广告", content))


def main() -> None:
    load_env_file()
    parser = argparse.ArgumentParser(description="rectg 本地后台管理页面")
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
