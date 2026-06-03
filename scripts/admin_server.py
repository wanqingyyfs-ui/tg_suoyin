#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import os
import sqlite3
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from search_entries import DB_PATH, search_entries


ROOT_DIR = Path(__file__).resolve().parent.parent
EXPORT_SCRIPT = ROOT_DIR / "scripts" / "export_frontend_data.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787


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


def connect_db() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 数据库不存在: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


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


def update_entry_status(entry_id: int, keep: int, valid: int, private: int) -> None:
    conn = connect_db()
    conn.execute(
        """
        UPDATE entries
        SET keep = ?, valid = ?, private = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (keep, valid, private, entry_id),
    )
    conn.commit()
    conn.close()


def update_entry_category(entry_id: int, category: str) -> None:
    conn = connect_db()
    conn.execute(
        """
        UPDATE entries
        SET category = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (category.strip(), entry_id),
    )
    conn.commit()
    conn.close()


def add_ad(position: str, title: str, url: str, description: str, enabled: int) -> None:
    conn = connect_db()
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
        INSERT INTO ads (position, title, description, url, image_url, sort_order, enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, NULL, 0, ?, datetime('now'), datetime('now'))
        """,
        (position.strip(), title.strip(), description.strip(), url.strip(), enabled),
    )
    conn.commit()
    conn.close()


def list_ads() -> list[sqlite3.Row]:
    conn = connect_db()
    try:
        rows = conn.execute(
            "SELECT * FROM ads ORDER BY position COLLATE NOCASE, sort_order ASC, id ASC LIMIT 100"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return rows


class AdminHandler(BaseHTTPRequestHandler):
    server_version = "rectg-admin/0.1"

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

    def redirect(self, path: str) -> None:
        self.send_response(303)
        self.send_header("Location", path)
        self.end_headers()

    def send_html(self, body: str, status: int = 200) -> None:
        if not self.is_authorized():
            body = self.layout("未授权", "<p>需要 ADMIN_TOKEN。请在 URL 后追加 ?token=你的Token，或使用 Authorization: Bearer。</p>")
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
body{{font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f7f8fa;color:#151922}}
main{{max-width:1120px;margin:0 auto;padding:24px}}
a{{color:#168ac1;text-decoration:none}}
.card{{background:#fff;border:1px solid #dde4eb;border-radius:10px;padding:16px;margin:14px 0}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
input,select,button{{font:inherit;padding:8px;border:1px solid #dde4eb;border-radius:8px}}
button{{background:#229ed9;color:#fff;font-weight:700;cursor:pointer}}
table{{width:100%;border-collapse:collapse;background:#fff}}
th,td{{border-bottom:1px solid #dde4eb;padding:8px;text-align:left;vertical-align:top}}
small{{color:#5d6675}}
.row-form{{display:flex;gap:6px;flex-wrap:wrap;align-items:center}}
</style>
</head>
<body><main>
<h1>rectg 本地管理</h1>
<p><a href="/{auth_suffix}">首页</a> · <a href="/ads{auth_suffix}">广告</a> · <a href="/export{auth_suffix}">导出 data.json</a></p>
{content}
</main></body></html>"""

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/ads":
            self.show_ads()
            return
        if parsed.path == "/export":
            output = run_export()
            self.send_html(self.layout("导出", f"<div class='card'><pre>{h(output)}</pre></div>"))
            return
        self.show_home(parsed)

    def do_POST(self) -> None:
        if not self.is_authorized():
            self.send_html("", status=403)
            return
        parsed = urllib.parse.urlparse(self.path)
        data = self.parse_post()
        try:
            if parsed.path == "/entry/status":
                update_entry_status(
                    int(data["id"]),
                    int(data.get("keep", "0")),
                    int(data.get("valid", "0")),
                    int(data.get("private", "0")),
                )
            elif parsed.path == "/entry/category":
                update_entry_category(int(data["id"]), data.get("category", ""))
            elif parsed.path == "/ads/add":
                add_ad(
                    data.get("position", "home_top"),
                    data.get("title", ""),
                    data.get("url", ""),
                    data.get("description", ""),
                    int(data.get("enabled", "1")),
                )
        except Exception as exc:
            self.send_html(self.layout("操作失败", f"<div class='card'>❌ {h(exc)}</div>"), status=400)
            return
        self.redirect(self.headers.get("Referer") or (parsed.query and f"/?{parsed.query}" or "/"))

    def show_home(self, parsed) -> None:
        query = urllib.parse.parse_qs(parsed.query)
        keyword = query.get("q", [""])[0]
        auth_suffix = self.auth_suffix()
        stats = db_stats()
        result = search_entries(keyword, limit=30) if keyword else search_entries("", limit=30)

        stat_html = "".join(f"<div class='card'><b>{h(k)}</b><br>{v}</div>" for k, v in stats.items())
        rows = []
        for item in result["items"]:
            rows.append(f"""
<tr>
<td>{h(item['id'])}</td>
<td><b>{h(item['title'])}</b><br><small>{h(item['url'])}</small></td>
<td>{h(item['type'])}</td>
<td>{h(item['category'])}</td>
<td>{h(item['countStr'])}</td>
<td>
<form class="row-form" method="post" action="/entry/category{auth_suffix}">
<input type="hidden" name="id" value="{h(item['id'])}">
<input name="category" value="{h(item['category'])}" size="14">
<button>改分类</button>
</form>
<form class="row-form" method="post" action="/entry/status{auth_suffix}">
<input type="hidden" name="id" value="{h(item['id'])}">
<select name="keep"><option value="1">keep=1</option><option value="0">keep=0</option></select>
<select name="valid"><option value="1">valid=1</option><option value="0">valid=0</option></select>
<select name="private"><option value="0">private=0</option><option value="1">private=1</option></select>
<button>改状态</button>
</form>
</td>
</tr>""")

        token_hidden = ""
        token_value = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
        if token_value:
            token_hidden = f'<input type="hidden" name="token" value="{h(token_value)}">'

        content = f"""
<div class="grid">{stat_html}</div>
<div class="card">
<form method="get" class="row-form">
{token_hidden}
<input name="q" value="{h(keyword)}" placeholder="搜索 entries" size="40">
<button>搜索</button>
</form>
</div>
<div class="card"><b>当前列表：</b>{h(keyword or '全部')}，共 {result['total']} 条</div>
<table><thead><tr><th>ID</th><th>标题</th><th>类型</th><th>分类</th><th>人数</th><th>操作</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
"""
        self.send_html(self.layout("首页", content))

    def show_ads(self) -> None:
        rows = []
        for ad in list_ads():
            rows.append(f"""
<tr><td>{h(ad['id'])}</td><td>{h(ad['position'])}</td><td><b>{h(ad['title'])}</b><br><small>{h(ad['description'])}</small></td><td><a href="{h(ad['url'])}" target="_blank">打开</a></td><td>{h(ad['enabled'])}</td></tr>
""")
        auth_suffix = self.auth_suffix()
        content = f"""
<div class="card">
<h2>新增广告</h2>
<form method="post" action="/ads/add{auth_suffix}" class="row-form">
<input name="position" value="home_top" placeholder="position">
<input name="title" placeholder="标题">
<input name="url" placeholder="https://example.com" size="32">
<input name="description" placeholder="说明" size="32">
<select name="enabled"><option value="1">启用</option><option value="0">禁用</option></select>
<button>新增</button>
</form>
<p><small>常用 position：home_top、search_inline、bot_search_inline。</small></p>
</div>
<table><thead><tr><th>ID</th><th>位置</th><th>标题</th><th>链接</th><th>启用</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
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
