#!/usr/bin/env python3
from __future__ import annotations

import argparse, html, os, re, sqlite3, subprocess, sys, urllib.parse
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

from bot_api_client import BotApiClient, check_bot_can_listen, get_bot_token
from categories import CATEGORY_ORDER, normalize_category
from listener_settings import ensure_settings, get_interval, set_interval
from message_indexer import clear_message_index, delete_message_index_row, init_message_index_schema, list_listening_entries, list_message_index_rows, message_index_stats
from search_entries import DB_PATH, TYPE_CHOICES, TYPE_LABELS

ROOT_DIR = Path(__file__).resolve().parent.parent
EXPORT_SCRIPT = ROOT_DIR / "scripts" / "export_frontend_data.py"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_AD_POSITION = "bot_search_inline"
REQUEST_TIMEOUT = 20
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
COUNT_RE = re.compile(r"([\d\s,\u00a0]+)\s*(subscribers?|members?|monthly users?)", re.IGNORECASE)

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

def load_env_file(path: Path = ROOT_DIR / ".env") -> None:
    if not path.exists(): return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

def h(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)

def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")

def clean_text(value: str) -> str:
    return " ".join((value or "").split()).strip()

def clean_category(value: str | None) -> str:
    return normalize_category(value) or "🧭 综合导航"

def connect_db(schema: bool = False) -> sqlite3.Connection:
    if not DB_PATH.exists(): raise SystemExit(f"❌ 数据库不存在：{DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH)); conn.row_factory = sqlite3.Row
    if schema:
        init_message_index_schema(conn); ensure_settings(conn)
    return conn

def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}

def count_str(value: Any) -> str:
    try: return f"{int(value or 0):,}"
    except Exception: return "0"

def init_categories_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, sort_order INTEGER DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"); conn.commit()

def init_ads_table(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS ads (id INTEGER PRIMARY KEY AUTOINCREMENT, position TEXT NOT NULL, title TEXT NOT NULL, description TEXT, url TEXT NOT NULL, image_url TEXT, sort_order INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"); conn.commit()

def sync_categories_table(conn: sqlite3.Connection) -> None:
    init_categories_table(conn); conn.execute("DELETE FROM categories"); now = now_text()
    for i, c in enumerate(CATEGORY_ORDER):
        conn.execute("INSERT OR IGNORE INTO categories (name,sort_order,created_at,updated_at) VALUES (?,?,?,?)", (c, i, now, now))
    conn.commit()

def normalize_all_categories() -> int:
    conn = connect_db(); sync_categories_table(conn)
    rows = conn.execute("SELECT id, category FROM entries WHERE category IS NOT NULL AND TRIM(category) <> ''").fetchall(); changed = 0
    for row in rows:
        new = clean_category(row["category"] or "")
        if new != (row["category"] or ""):
            conn.execute("UPDATE entries SET category=?, updated_at=datetime('now') WHERE id=?", (new, row["id"])); changed += 1
    conn.commit(); conn.close(); return changed

def db_stats() -> dict[str, int]:
    conn = connect_db(True); stats = {}
    for name in ("links", "entries", "ads", "message_index"):
        try: stats[name] = int(conn.execute(f"SELECT COUNT(*) AS c FROM {name}").fetchone()["c"])
        except sqlite3.OperationalError: stats[name] = 0
    stats["visible_entries"] = int(conn.execute("SELECT COUNT(*) AS c FROM entries WHERE keep=1 AND valid=1 AND private=0").fetchone()["c"])
    stats["active_listening"] = int(conn.execute("SELECT COUNT(*) AS c FROM entries WHERE listen_enabled=1 AND listen_status='active'").fetchone()["c"])
    conn.close(); return stats

def run_export() -> str:
    p = subprocess.run([sys.executable, str(EXPORT_SCRIPT)], cwd=str(ROOT_DIR), check=False, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (p.stdout or "") + (p.stderr or "")

def normalize_input(raw: str) -> tuple[str, str]:
    value = (raw or "").strip()
    if not value: raise ValueError("链接不能为空")
    if value.startswith("@"): value = value[1:].strip()
    if value.startswith("t.me/") or value.startswith("telegram.me/"): value = "https://" + value
    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value); host = (parsed.netloc or "").lower()
        if host not in ("t.me", "www.t.me", "telegram.me", "www.telegram.me"): raise ValueError("只支持 t.me 或 telegram.me 公开链接")
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if not parts: raise ValueError("链接中没有 username")
        if parts[0] in ("joinchat", "+") or parts[0].startswith("+"): raise ValueError("暂不支持私密邀请链接，只支持公开 username")
        username = parts[1] if parts[0] == "s" and len(parts) > 1 else parts[0]
    else:
        username = value
    username = username.strip().strip("/")
    if not USERNAME_RE.match(username): raise ValueError("username 格式不合法。要求以英文字母开头，只包含字母、数字、下划线，长度 4-32 位")
    return username, f"https://t.me/{username}"

def parse_count(extra: str) -> int | None:
    m = COUNT_RE.search((extra or "").replace("\u00a0", " "))
    if not m: return None
    digits = re.sub(r"\D", "", m.group(1)); return int(digits) if digits else None

def infer_type(username: str, extra_text: str, page_text: str) -> str:
    extra = (extra_text or "").casefold(); page = (page_text or "").casefold()
    if username.casefold().endswith("bot") or " bot" in extra or "telegram bot" in page or "monthly users" in extra: return "bot"
    if "member" in extra: return "group"
    return "channel"

def scan_telegram_public_page(raw_target: str) -> ScanResult:
    username, url = normalize_input(raw_target); headers = {"User-Agent":"Mozilla/5.0","Accept-Language":"zh-CN,zh;q=0.9,en;q=0.8"}
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT); r.raise_for_status()
    except Exception as exc:
        return ScanResult(username, url, username, "", "channel", None, 1, 0, f"抓取失败：{exc}")
    soup = BeautifulSoup(r.text, "html.parser")
    title_el = soup.select_one(".tgme_page_title span") or soup.select_one(".tgme_page_title")
    desc_el = soup.select_one(".tgme_page_description"); extra_el = soup.select_one(".tgme_page_extra")
    og_title = soup.find("meta", attrs={"property":"og:title"}); og_desc = soup.find("meta", attrs={"property":"og:description"})
    title = clean_text(title_el.get_text(" ", strip=True) if title_el else "") or clean_text(str(og_title.get("content"))) if og_title and og_title.get("content") else ""
    desc = clean_text(desc_el.get_text(" ", strip=True) if desc_el else "") or clean_text(str(og_desc.get("content"))) if og_desc and og_desc.get("content") else ""
    extra = clean_text(extra_el.get_text(" ", strip=True) if extra_el else ""); page_text = clean_text(soup.get_text(" ", strip=True))
    count = parse_count(extra); entry_type = infer_type(username, extra, page_text); title = title or username
    private = 0 if title and (desc or extra or count is not None) else 1; valid = 1 if title and not private else 0
    return ScanResult(username, url, title, desc, entry_type, count, private, valid)

def scan_telegram_batch(raw_text: str) -> list[ScanResult]:
    targets, seen = [], set()
    for raw in (raw_text or "").splitlines():
        v = raw.strip()
        if v and v not in seen: seen.add(v); targets.append(v)
    if not targets: raise ValueError("请至少输入一个 Telegram 公开链接，每行一个")
    results = []
    for t in targets:
        try: results.append(scan_telegram_public_page(t))
        except Exception as exc: results.append(ScanResult(t, t, t, "", "channel", None, 1, 0, str(exc)))
    return results

def save_scanned_entry(data: dict[str, str]) -> int:
    username, url = normalize_input(data.get("url") or data.get("username") or "")
    title = clean_text(data.get("title") or username); desc = clean_text(data.get("description") or "")
    entry_type = data.get("type") if data.get("type") in TYPE_CHOICES else "channel"; category = clean_category(data.get("category") or "🧭 综合导航")
    keep, valid, private = int(data.get("keep", "1")), int(data.get("valid", "1")), int(data.get("private", "0"))
    try: count = int(data.get("count") or "")
    except ValueError: count = None
    conn = connect_db(True); sync_categories_table(conn); now = now_text()
    conn.execute("INSERT INTO links (url,username,name,type_hint,created_at,updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT(url) DO UPDATE SET username=excluded.username,name=excluded.name,type_hint=excluded.type_hint,updated_at=excluded.updated_at", (url, username, title, entry_type, now, now))
    existing = conn.execute("SELECT id FROM entries WHERE url=? OR username=? LIMIT 1", (url, username)).fetchone()
    payload = dict(username=username,url=url,type=entry_type,title=title,description=desc,clean_title=title,clean_desc=desc,category=category,count=count,valid=valid,private=private,keep=keep,filter_reason="",updated_at=now)
    if existing:
        payload["id"] = existing["id"]
        conn.execute("UPDATE entries SET username=:username,url=:url,type=:type,title=:title,description=:description,clean_title=:clean_title,clean_desc=:clean_desc,category=:category,count=:count,valid=:valid,private=:private,keep=:keep,filter_reason=:filter_reason,updated_at=:updated_at WHERE id=:id", payload)
        entry_id = int(existing["id"])
    else:
        payload["created_at"] = now
        conn.execute("INSERT INTO entries (username,url,type,title,description,clean_title,clean_desc,category,count,valid,private,keep,filter_reason,created_at,updated_at) VALUES (:username,:url,:type,:title,:description,:clean_title,:clean_desc,:category,:count,:valid,:private,:keep,:filter_reason,:created_at,:updated_at)", payload)
        entry_id = int(conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])
    conn.commit(); conn.close(); return entry_id

def save_scanned_entries(data: dict[str, str]) -> list[int]:
    total = int(data.get("batch_total") or "0")
    if total <= 0: return [save_scanned_entry(data)]
    ids = []
    for i in range(total):
        item = {k: data.get(f"{k}_{i}", "") for k in ("username","url","title","description","type","count","category","keep","valid","private")}
        if item.get("url") or item.get("username"): ids.append(save_scanned_entry(item))
    return ids

def list_admin_entries(keyword: str = "") -> list[sqlite3.Row]:
    conn = connect_db(True); q = clean_text(keyword); where = ""; params: list[Any] = []
    if q:
        like = f"%{q}%"; where = "WHERE e.title LIKE ? OR e.clean_title LIKE ? OR e.clean_desc LIKE ? OR e.username LIKE ? OR e.category LIKE ? OR e.url LIKE ?"; params = [like]*6
    rows = conn.execute(f"SELECT e.id,e.title,e.clean_title,e.username,e.url,e.type,e.count,e.category,e.keep,e.valid,e.private,e.telegram_id,e.listen_enabled,e.listen_status,e.listen_error,e.listen_checked_at,e.last_indexed_message_id,COUNT(mi.id) AS message_count FROM entries e LEFT JOIN message_index mi ON mi.entry_id=e.id {where} GROUP BY e.id ORDER BY e.id DESC LIMIT 100", params).fetchall()
    conn.close(); return rows

def save_entry(data: dict[str, str]) -> None:
    conn = connect_db(True); sync_categories_table(conn)
    conn.execute("UPDATE entries SET title=?,category=?,keep=?,valid=?,private=?,updated_at=datetime('now') WHERE id=?", (clean_text(data.get("title") or ""), clean_category(data.get("category")), int(data.get("keep","0")), int(data.get("valid","0")), int(data.get("private","0")), int(data["id"])))
    conn.commit(); conn.close()

def delete_entry(entry_id: int) -> None:
    conn = connect_db(True); row = conn.execute("SELECT username,url FROM entries WHERE id=?", (entry_id,)).fetchone()
    if not row: conn.close(); raise ValueError("未找到要删除的资源")
    conn.execute("DELETE FROM message_index WHERE entry_id=?", (entry_id,)); conn.execute("DELETE FROM entries WHERE id=?", (entry_id,)); conn.execute("DELETE FROM links WHERE url=? OR username=?", (row["url"], row["username"]))
    conn.commit(); conn.close()

def enable_listener(entry_id: int) -> str:
    load_env_file(); conn = connect_db(True); row = conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
    if not row: conn.close(); raise ValueError("未找到要开启监听的资源")
    if row["type"] not in ("channel", "group"): conn.close(); raise ValueError("只有频道和群组支持监听")
    try: result = check_bot_can_listen(row_dict(row), BotApiClient(get_bot_token()))
    except Exception as exc: result = None; error = f"该群组/频道无法启动监听功能，请检查bot权限。详情：{exc}"
    else: error = "" if result.ok else result.message
    if not result or not result.ok:
        conn.execute("UPDATE entries SET listen_enabled=0,listen_status='error',listen_error=?,listen_checked_at=datetime('now'),updated_at=datetime('now') WHERE id=?", (error or "该群组/频道无法启动监听功能，请检查bot权限。", entry_id)); conn.commit(); conn.close(); raise ValueError(error or "该群组/频道无法启动监听功能，请检查bot权限。")
    conn.execute("UPDATE entries SET listen_enabled=1,listen_status='active',listen_error=NULL,listen_checked_at=datetime('now'),telegram_id=COALESCE(?,telegram_id),username=COALESCE(NULLIF(?,''),username),updated_at=datetime('now') WHERE id=?", (result.chat_id, result.chat_username, entry_id)); conn.commit(); conn.close(); return "监听已开启"

def disable_listener(entry_id: int) -> None:
    conn = connect_db(True); conn.execute("UPDATE entries SET listen_enabled=0,listen_status='off',listen_error=NULL,listen_checked_at=datetime('now'),updated_at=datetime('now') WHERE id=?", (entry_id,)); conn.commit(); conn.close()

def category_stats() -> list[dict[str, Any]]:
    conn = connect_db(); sync_categories_table(conn); rows = []
    for c in CATEGORY_ORDER:
        rows.append({"name": c, "count": int(conn.execute("SELECT COUNT(*) AS c FROM entries WHERE keep=1 AND valid=1 AND private=0 AND category=?", (c,)).fetchone()["c"])})
    conn.close(); return rows

def add_ad(title: str, url: str, desc: str, enabled: int, sort_order: int) -> None:
    conn = connect_db(); init_ads_table(conn); now = now_text(); conn.execute("INSERT INTO ads (position,title,description,url,image_url,sort_order,enabled,created_at,updated_at) VALUES (?,?,?,?,NULL,?,?,?,?)", (DEFAULT_AD_POSITION, clean_text(title)[:30], clean_text(desc), clean_text(url), sort_order, enabled, now, now)); conn.commit(); conn.close()

def update_ad(data: dict[str, str]) -> None:
    conn = connect_db(); init_ads_table(conn); conn.execute("UPDATE ads SET title=?,description=?,url=?,sort_order=?,enabled=?,updated_at=datetime('now') WHERE id=?", (clean_text(data.get("title") or "")[:30], clean_text(data.get("description") or ""), clean_text(data.get("url") or ""), int(data.get("sort_order") or 0), int(data.get("enabled", "0")), int(data["id"]))); conn.commit(); conn.close()

def delete_ad(ad_id: int) -> None:
    conn = connect_db(); init_ads_table(conn); conn.execute("DELETE FROM ads WHERE id=?", (ad_id,)); conn.commit(); conn.close()

def list_ads() -> list[sqlite3.Row]:
    conn = connect_db(); init_ads_table(conn); rows = conn.execute("SELECT * FROM ads ORDER BY sort_order ASC,id ASC LIMIT 200").fetchall(); conn.close(); return rows

class AdminHandler(BaseHTTPRequestHandler):
    server_version = "tg-suoyin-admin/3.0"
    def log_message(self, fmt: str, *args: Any) -> None: sys.stdout.write("后台访问：" + (fmt % args) + "\n")
    def is_authorized(self) -> bool:
        token = getattr(self.server, "admin_token", "")
        if not token: return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return q.get("token", [""])[0] == token or self.headers.get("Authorization", "") == f"Bearer {token}"
    def auth_suffix(self) -> str:
        token = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("token", [""])[0]
        return "?token=" + urllib.parse.quote(token) if token else ""
    def with_auth(self, path: str) -> str:
        s = self.auth_suffix(); return path if not s else path + ("&" if "?" in path else "?") + s.lstrip("?")
    def redirect(self, path: str) -> None:
        self.send_response(303); self.send_header("Location", path); self.end_headers()
    def send_html(self, body: str, status: int = 200) -> None:
        if not self.is_authorized(): body = self.layout("未授权", "<div class='panel error'>需要 ADMIN_TOKEN。</div>"); status = 403
        encoded = body.encode("utf-8"); self.send_response(status); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(encoded))); self.end_headers(); self.wfile.write(encoded)
    def parse_post(self) -> dict[str, str]:
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0)).decode("utf-8"); data = urllib.parse.parse_qs(raw); return {k: v[0] for k, v in data.items()}
    def layout(self, title: str, content: str) -> str:
        auth = self.auth_suffix(); css = "body{margin:0;background:#f6f8fb;color:#172033;font-family:system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px}main{max-width:1380px;margin:0 auto;padding:24px}a{color:#168ac1;text-decoration:none}.nav{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0 20px}.nav a,.badge{display:inline-flex;align-items:center;min-height:28px;padding:0 10px;border:1px solid #dfe6ee;border-radius:999px;background:#fff;font-weight:800}.panel,.stat{background:#fff;border:1px solid #dfe6ee;border-radius:14px;padding:16px;margin:14px 0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}.stat b{display:block;font-size:20px}.row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}.stack{display:grid;gap:8px}input,textarea,select,button{font:inherit;border:1px solid #dfe6ee;border-radius:10px;padding:8px 10px;background:#fff;color:#172033}button{background:#229ed9;border-color:#229ed9;color:#fff;font-weight:800;cursor:pointer}button.danger{background:#dc2626;border-color:#dc2626}button.secondary{background:#64748b;border-color:#64748b}.table-wrap{overflow-x:auto;border:1px solid #dfe6ee;border-radius:14px;background:#fff}table{width:100%;border-collapse:collapse;min-width:980px}th,td{border-bottom:1px solid #dfe6ee;padding:10px;text-align:left;vertical-align:top}th{background:#f8fafc;color:#475569}small,.muted{color:#64748b}.ok{color:#16a34a;font-weight:800}.error{color:#dc2626;font-weight:800}.entry-title{width:220px}.category-input{width:180px}.actions-inline{display:flex;gap:8px;flex-wrap:wrap}.actions-inline form{display:inline-flex;margin:0}pre{white-space:pre-wrap;background:#0f172a;color:#e2e8f0;border-radius:12px;padding:12px;overflow:auto}"
        return f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>{h(title)} - TG 索引管理后台</title><style>{css}</style></head><body><main><h1>💎 TG 索引管理后台</h1><div class='muted'>Bot API 监听只用于消息锚点索引，不导出到前台网页。</div><nav class='nav'><a href='/{auth}'>资源管理</a><a href='/add{auth}'>添加资源</a><a href='/categories{auth}'>分类管理</a><a href='/ads{auth}'>广告管理</a><a href='/messages{auth}'>消息管理</a><a href='/export{auth}'>导出数据</a></nav>{content}</main></body></html>"
    def category_datalist(self) -> str: return "<datalist id='category-options'>" + "".join(f"<option value=\"{h(c)}\"></option>" for c in CATEGORY_ORDER) + "</datalist>"
    def do_GET(self) -> None:
        p = urllib.parse.urlparse(self.path)
        if p.path == "/add": self.show_add()
        elif p.path == "/categories": self.show_categories()
        elif p.path == "/ads": self.show_ads()
        elif p.path == "/messages": self.show_messages(p)
        elif p.path == "/export": self.send_html(self.layout("导出数据", f"<div class='panel'><h2>导出结果</h2><pre>{h(run_export())}</pre></div>"))
        else: self.show_home(p)
    def do_POST(self) -> None:
        if not self.is_authorized(): self.send_html("", 403); return
        p = urllib.parse.urlparse(self.path); data = self.parse_post()
        try:
            if p.path == "/entry/save": save_entry(data); self.redirect(self.headers.get("Referer") or self.with_auth("/"))
            elif p.path == "/entry/delete": delete_entry(int(data["id"])); self.redirect(self.headers.get("Referer") or self.with_auth("/"))
            elif p.path == "/listener/enable": enable_listener(int(data["id"])); self.redirect(self.headers.get("Referer") or self.with_auth("/messages"))
            elif p.path == "/listener/disable": disable_listener(int(data["id"])); self.redirect(self.headers.get("Referer") or self.with_auth("/messages"))
            elif p.path == "/listener/settings": conn=connect_db(True); set_interval(conn, int(data.get("summary_interval") or 300)); conn.close(); self.redirect(self.with_auth("/messages"))
            elif p.path == "/message/delete": conn=connect_db(True); delete_message_index_row(conn, int(data["id"])); conn.close(); self.redirect(self.headers.get("Referer") or self.with_auth("/messages"))
            elif p.path == "/message/clear": conn=connect_db(True); clear_message_index(conn, int(data["entry_id"]) if data.get("entry_id") else None); conn.close(); self.redirect(self.with_auth("/messages"))
            elif p.path == "/add/scan": r=scan_telegram_batch(data.get("urls") or data.get("url", "")); self.show_add(r, data.get("urls", ""), f"扫描完成：成功 {sum(1 for x in r if not x.error)} 条，失败 {sum(1 for x in r if x.error)} 条")
            elif p.path == "/add/save": ids=save_scanned_entries(data); self.show_add(message=f"✅ 已保存 {len(ids)} 条资源。")
            elif p.path == "/categories/clean": self.show_categories(f"✅ 已清理旧分类并同步固定大类，归并 {normalize_all_categories()} 条记录。")
            elif p.path == "/ads/add": add_ad(data.get("title",""), data.get("url",""), data.get("description",""), int(data.get("enabled","1")), int(data.get("sort_order") or 0)); self.redirect(self.with_auth("/ads"))
            elif p.path == "/ads/update": update_ad(data); self.redirect(self.with_auth("/ads"))
            elif p.path == "/ads/delete": delete_ad(int(data["id"])); self.redirect(self.with_auth("/ads"))
            else: self.send_html(self.layout("未找到", "<div class='panel'>未知操作。</div>"), 404)
        except Exception as exc: self.send_html(self.layout("操作失败", f"<div class='panel error'>❌ {h(exc)}</div>"), 400)
    def show_home(self, parsed) -> None:
        q = urllib.parse.parse_qs(parsed.query); keyword = q.get("q", [""])[0]; stats = db_stats(); rows_html=[]
        for item in list_admin_entries(keyword):
            fid=f"entry-save-{item['id']}"; tlabel=TYPE_LABELS.get(item['type'], item['type'] or "未知"); status=item['listen_status'] or "off"; cls="ok" if item['listen_enabled'] and status=="active" else ("error" if status=="error" else "muted")
            if item['type'] in ('channel','group'):
                lbtn = f"<form method='post' action='{self.with_auth('/listener/disable')}'><input type='hidden' name='id' value='{h(item['id'])}'><button class='secondary'>关闭监听</button></form>" if item['listen_enabled'] and status=='active' else f"<form method='post' action='{self.with_auth('/listener/enable')}'><input type='hidden' name='id' value='{h(item['id'])}'><button>开启监听</button></form>"
            else: lbtn="<span class='muted'>机器人不监听</span>"
            err=f"<br><small class='error'>{h(item['listen_error'])}</small>" if item['listen_error'] else ""
            rows_html.append(f"<tr><td>{h(item['id'])}</td><td><input form='{h(fid)}' type='hidden' name='id' value='{h(item['id'])}'><input form='{h(fid)}' class='entry-title' name='title' value='{h(item['title'] or item['clean_title'] or item['username'])}'><br><small>{h(item['url'])}</small></td><td><span class='badge'>{h(tlabel)}</span></td><td><input form='{h(fid)}' class='category-input' list='category-options' name='category' value='{h(clean_category(item['category']))}'></td><td>{h(count_str(item['count']))}</td><td><span class='{cls}'>{h('ON' if item['listen_enabled'] else 'OFF')} / {h(status)}</span><br><small>消息 {h(item['message_count'])} 条</small>{err}</td><td><form id='{h(fid)}' method='post' action='{self.with_auth('/entry/save')}'></form><div class='actions-inline'><select form='{h(fid)}' name='keep'><option value='1' {'selected' if item['keep'] else ''}>显示</option><option value='0' {'selected' if not item['keep'] else ''}>隐藏</option></select><select form='{h(fid)}' name='valid'><option value='1' {'selected' if item['valid'] else ''}>有效</option><option value='0' {'selected' if not item['valid'] else ''}>无效</option></select><select form='{h(fid)}' name='private'><option value='0' {'selected' if not item['private'] else ''}>公开</option><option value='1' {'selected' if item['private'] else ''}>私密</option></select><button form='{h(fid)}'>保存</button>{lbtn}<form method='post' action='{self.with_auth('/entry/delete')}' onsubmit=\"return confirm('确认删除这个资源？')\"><input type='hidden' name='id' value='{h(item['id'])}'><button class='danger'>删除</button></form></div></td></tr>")
        stat_names={"links":"链接数","entries":"资源总数","ads":"广告数","message_index":"消息索引","visible_entries":"前台可见","active_listening":"监听中"}; stat_html="".join(f"<div class='stat'>{h(stat_names.get(k,k))}<b>{v}</b></div>" for k,v in stats.items()); token=f'<input type="hidden" name="token" value="{h(q.get("token", [""])[0])}">' if q.get("token", [""])[0] else ""
        content=f"{self.category_datalist()}<div class='grid'>{stat_html}</div><div class='panel'><form method='get' class='row'>{token}<input name='q' value='{h(keyword)}' placeholder='搜索标题、简介、用户名、分类' size='42'><button>搜索</button><a class='badge' href='{self.with_auth('/add')}'>添加资源</a><a class='badge' href='{self.with_auth('/messages')}'>消息管理</a></form></div><div class='table-wrap'><table><thead><tr><th>ID</th><th>标题</th><th>类型</th><th>分类</th><th>人数</th><th>监听</th><th>操作</th></tr></thead><tbody>{''.join(rows_html)}</tbody></table></div>"
        self.send_html(self.layout("资源管理", content))
    def show_messages(self, parsed) -> None:
        q=urllib.parse.parse_qs(parsed.query); keyword=q.get("q", [""])[0]; entry_raw=q.get("entry_id", [""])[0]; entry_id=int(entry_raw) if entry_raw.isdigit() else None; conn=connect_db(True)
        try: stats=message_index_stats(conn); interval=get_interval(conn); listeners=list_listening_entries(conn); msgs=list_message_index_rows(conn, keyword=keyword, entry_id=entry_id, limit=120)
        finally: conn.close()
        lrows=[]
        for item in listeners:
            status=item['listen_status'] or 'off'; cls='ok' if item['listen_enabled'] and status=='active' else ('error' if status=='error' else 'muted')
            btn=f"<form method='post' action='{self.with_auth('/listener/disable')}'><input type='hidden' name='id' value='{h(item['id'])}'><button class='secondary'>关闭监听</button></form>" if item['listen_enabled'] and status=='active' else f"<form method='post' action='{self.with_auth('/listener/enable')}'><input type='hidden' name='id' value='{h(item['id'])}'><button>开启监听</button></form>"
            lrows.append(f"<tr><td>{h(item['id'])}</td><td>{h(item['title'] or item['username'] or item['url'])}<br><small>@{h(item['username'] or '-')} | chat_id={h(item['telegram_id'] or '-')}</small></td><td>{h(TYPE_LABELS.get(item['type'], item['type']))}</td><td><span class='{cls}'>{h('ON' if item['listen_enabled'] else 'OFF')} / {h(status)}</span><br><small>{h(item['listen_error'] or '')}</small></td><td>{h(item['message_count'])}</td><td><div class='actions-inline'>{btn}<a class='badge' href='{self.with_auth('/messages?entry_id=' + str(item['id']))}'>查看消息</a></div></td></tr>")
        mrows=[]
        for m in msgs:
            mrows.append(f"<tr><td>{h(m['id'])}</td><td>{h(m['chat_title'] or m['entry_title'] or '')}<br><small>entry={h(m['entry_id'])} | chat={h(m['chat_id'])} | msg={h(m['message_id'])}</small></td><td><a href='{h(m['link'])}' target='_blank'>{h(m['link'])}</a><br><small>{h(m['message_date'])}</small></td><td><small>{h(' '.join((m['keywords'] or '').split()[:30]))}</small></td><td><form method='post' action='{self.with_auth('/message/delete')}' onsubmit=\"return confirm('确认删除这条消息索引？')\"><input type='hidden' name='id' value='{h(m['id'])}'><button class='danger'>删除</button></form></td></tr>")
        stat_html="".join(f"<div class='stat'>{h(k)}<b>{h(v)}</b></div>" for k,v in stats.items())
        content=f"<div class='grid'>{stat_html}<div class='stat'>终端汇总间隔<b>{h(interval)} 秒</b></div></div><div class='panel'><h2>监听设置</h2><p class='muted'>一个 Bot 进程会同时监听所有已开启的频道/群组。默认每 300 秒汇总打印一次。</p><form method='post' action='{self.with_auth('/listener/settings')}' class='row'><input name='summary_interval' value='{h(interval)}' size='8'><button>保存间隔</button></form></div><div class='panel'><h2>已收录频道/群组监听</h2><p class='muted'>开启监听前，请先把 Bot 加入对应频道/群组并设置为管理员。</p></div><div class='table-wrap'><table><thead><tr><th>ID</th><th>资源</th><th>类型</th><th>监听状态</th><th>消息数</th><th>操作</th></tr></thead><tbody>{''.join(lrows)}</tbody></table></div><div class='panel'><h2>消息索引</h2><form method='get' class='row'><input name='q' value='{h(keyword)}' placeholder='搜索关键词索引' size='32'><input name='entry_id' value='{h(entry_raw)}' placeholder='资源ID，可空' size='10'><button>筛选</button><a class='badge' href='{self.with_auth('/messages')}'>重置</a></form><form method='post' action='{self.with_auth('/message/clear')}' class='row' onsubmit=\"return confirm('确认清空消息索引？')\"><input name='entry_id' value='{h(entry_raw)}' placeholder='只清空某资源ID；空=全部' size='22'><button class='danger'>清空消息索引</button></form></div><div class='table-wrap'><table><thead><tr><th>ID</th><th>来源</th><th>跳转链接</th><th>关键词索引</th><th>操作</th></tr></thead><tbody>{''.join(mrows)}</tbody></table></div>"
        self.send_html(self.layout("消息管理", content))
    def show_add(self, results: list[ScanResult] | None = None, raw_targets: str = "", message: str = "") -> None:
        scanned=""
        if results:
            rows=[]; idx=0; cats="".join(f"<option value='{h(c)}'>{h(c)}</option>" for c in CATEGORY_ORDER)
            for r in results:
                if r.error: rows.append(f"<tr><td>{h(r.url)}</td><td colspan='7'><b>扫描失败</b><br><small>{h(r.error)}</small></td></tr>"); continue
                opts="".join(f"<option value='{c}' {'selected' if c==r.entry_type else ''}>{h(TYPE_LABELS.get(c,c))}</option>" for c in TYPE_CHOICES); cnt="" if r.count is None else str(r.count)
                rows.append(f"<tr><td><input type='hidden' name='username_{idx}' value='{h(r.username)}'><input name='url_{idx}' value='{h(r.url)}' size='28'><br><small>@{h(r.username)}</small></td><td><input name='title_{idx}' value='{h(r.title)}'></td><td><textarea name='description_{idx}'>{h(r.description)}</textarea></td><td><select name='type_{idx}'>{opts}</select></td><td><input name='count_{idx}' value='{h(cnt)}' size='8'></td><td><select name='category_{idx}'>{cats}</select></td><td><select name='keep_{idx}'><option value='1'>显示</option><option value='0'>隐藏</option></select><input type='hidden' name='valid_{idx}' value='{h(r.valid)}'><input type='hidden' name='private_{idx}' value='{h(r.private)}'></td></tr>"); idx+=1
            scanned=f"<div class='panel'><h2>扫描结果</h2><form method='post' action='{self.with_auth('/add/save')}' class='stack'><input type='hidden' name='batch_total' value='{idx}'><div class='table-wrap'><table><thead><tr><th>链接</th><th>标题</th><th>简介</th><th>类型</th><th>人数</th><th>分类</th><th>状态</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div><button>保存全部 {idx} 条</button></form></div>"
        self.send_html(self.layout("添加资源", f"<div class='panel'><h2>批量添加资源</h2><form method='post' action='{self.with_auth('/add/scan')}' class='stack'><textarea name='urls' rows='8' placeholder='https://t.me/username1&#10;@username2' required>{h(raw_targets)}</textarea><button>扫描</button></form></div>{f'<div class="panel ok">{h(message)}</div>' if message else ''}{scanned}"))
    def show_categories(self, message: str = "") -> None:
        rows="".join(f"<tr><td>{h(x['name'])}</td><td>{h(x['count'])}</td></tr>" for x in category_stats())
        self.send_html(self.layout("分类管理", f"<div class='panel'><h2>固定大类</h2>{f'<p class="ok">{h(message)}</p>' if message else ''}<form method='post' action='{self.with_auth('/categories/clean')}'><button>立即清理旧分类并同步大类</button></form></div><div class='table-wrap'><table><thead><tr><th>分类</th><th>前台可见资源数</th></tr></thead><tbody>{rows}</tbody></table></div>"))
    def show_ads(self) -> None:
        rows=[]
        for ad in list_ads():
            rows.append(f"<tr><td>{h(ad['id'])}</td><td><form method='post' action='{self.with_auth('/ads/update')}' class='row'><input type='hidden' name='id' value='{h(ad['id'])}'><input name='title' value='{h(ad['title'])}' maxlength='30'><input name='url' value='{h(ad['url'])}' size='34'><input name='description' value='{h(ad['description'])}'><input name='sort_order' value='{h(ad['sort_order'])}' size='6'><select name='enabled'><option value='1' {'selected' if ad['enabled'] else ''}>启用</option><option value='0' {'selected' if not ad['enabled'] else ''}>禁用</option></select><button>保存</button></form><form method='post' action='{self.with_auth('/ads/delete')}' onsubmit=\"return confirm('确认删除这个广告？')\"><input type='hidden' name='id' value='{h(ad['id'])}'><button class='danger'>删除</button></form></td></tr>")
        self.send_html(self.layout("广告管理", f"<div class='panel'><h2>新增 Bot 顶部广告</h2><form method='post' action='{self.with_auth('/ads/add')}' class='row'><input name='title' maxlength='30' placeholder='广告标题' required><input name='url' placeholder='https://example.com' required><input name='description' placeholder='说明，可空'><input name='sort_order' value='0' size='6'><select name='enabled'><option value='1'>启用</option><option value='0'>禁用</option></select><button>新增</button></form></div><div class='table-wrap'><table><thead><tr><th>ID</th><th>广告内容 / 操作</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"))

def main() -> None:
    load_env_file(); parser=argparse.ArgumentParser(description="TG 索引本地管理后台"); parser.add_argument("--host", default=os.environ.get("ADMIN_HOST", DEFAULT_HOST)); parser.add_argument("--port", type=int, default=int(os.environ.get("ADMIN_PORT", DEFAULT_PORT))); parser.add_argument("--token", default=os.environ.get("ADMIN_TOKEN", "")); args=parser.parse_args()
    normalize_all_categories(); conn=connect_db(True); conn.close(); server=ThreadingHTTPServer((args.host, args.port), AdminHandler); server.admin_token=args.token
    print(f"✅ 管理后台已启动：http://{args.host}:{args.port}")
    if args.token: print("✅ 已启用 ADMIN_TOKEN。打开后台时请在地址后追加 ?token=你的Token")
    try: server.serve_forever()
    except KeyboardInterrupt: print("\n已停止管理后台。")

if __name__ == "__main__": main()
