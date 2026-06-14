#!/usr/bin/env python3
"""
Telegram 公开页面爬虫。

从 SQLite 的 links 表中获取链接，爬取公开信息，结果存入 entries 表。
tg_suoyin 不做内容过滤；上游 tg_shaixuan 负责筛选，tg_suoyin 只负责采集公开元数据、分类和导出。

用法:
    python3 scripts/crawl.py
    python3 scripts/crawl.py --limit 10
    python3 scripts/crawl.py --new
    python3 scripts/crawl.py --older-than-days 7
    python3 scripts/crawl.py --no-resume
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import random
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "rectg.db"
LOG_PATH = DATA_DIR / "crawl.log"

MIN_DELAY = 3
MAX_DELAY = 6
BATCH_SIZE = 50
BATCH_PAUSE = 60
RETRY_BASE = 60
RETRY_MAX = 300
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def setup_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("crawl")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)
    return logger


log = logging.getLogger("crawl")


class ProgressTracker:
    def __init__(self, total: int):
        self.total = total
        self.done = 0
        self.saved = 0
        self.invalid = 0
        self.start_time = time.time()

    def tick(self, valid: bool):
        self.done += 1
        if valid:
            self.saved += 1
        else:
            self.invalid += 1

    def progress_str(self) -> str:
        elapsed = time.time() - self.start_time
        pct = self.done * 100 / self.total if self.total else 0
        remaining = self.total - self.done
        if self.done > 0:
            avg_time = elapsed / self.done
            eta_seconds = remaining * avg_time
            eta_min = int(eta_seconds // 60)
            eta_sec = int(eta_seconds % 60)
            eta_str = f"{eta_min}m{eta_sec}s"
        else:
            eta_str = "计算中"
        elapsed_min = int(elapsed // 60)
        elapsed_sec = int(elapsed % 60)
        return (
            f"[{self.done}/{self.total}] {pct:.1f}% "
            f"| 已记录 {self.saved} | 无效 {self.invalid} "
            f"| 耗时 {elapsed_min}m{elapsed_sec}s "
            f"| 预计剩余 {eta_str}"
        )

    def summary_str(self) -> str:
        elapsed = time.time() - self.start_time
        elapsed_min = int(elapsed // 60)
        elapsed_sec = int(elapsed % 60)
        return f"总计: {self.done} | 已记录: {self.saved} | 无效: {self.invalid} | 总耗时: {elapsed_min}m{elapsed_sec}s"


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id     INTEGER,
            username        TEXT UNIQUE,
            url             TEXT NOT NULL UNIQUE,
            type            TEXT,
            title           TEXT,
            description     TEXT,
            clean_title     TEXT,
            clean_desc      TEXT,
            category        TEXT,
            avatar          TEXT,
            count           INTEGER,
            last_active     TEXT,
            valid           INTEGER DEFAULT 0,
            private         INTEGER DEFAULT 0,
            keep            INTEGER DEFAULT 1,
            filter_reason   TEXT,
            created_at      TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn


def upsert_entry(conn: sqlite3.Connection, data: dict):
    now = datetime.now().isoformat()
    data["keep"] = 1
    data["filter_reason"] = ""

    existing = conn.execute(
        "SELECT id, created_at FROM entries WHERE url = ?",
        (data["url"],),
    ).fetchone()

    if existing:
        data["created_at"] = existing["created_at"]
        data["updated_at"] = now
        conn.execute("""
            UPDATE entries SET
                telegram_id   = :telegram_id,
                username      = :username,
                type          = :type,
                title         = :title,
                description   = :description,
                avatar        = :avatar,
                count         = :count,
                last_active   = :last_active,
                valid         = :valid,
                private       = :private,
                keep          = :keep,
                filter_reason = :filter_reason,
                updated_at    = :updated_at
            WHERE url = :url
        """, data)
    else:
        if data.get("username"):
            dup = conn.execute(
                "SELECT id, url FROM entries WHERE username = ?",
                (data["username"],),
            ).fetchone()
            if dup:
                log.info("       ⏭️  跳过: 同一频道已存在 (%s)", dup["url"])
                return

        data["created_at"] = now
        data["updated_at"] = now
        conn.execute("""
            INSERT INTO entries (
                telegram_id, username, url, type,
                title, description, avatar,
                count, last_active,
                valid, private, keep, filter_reason,
                created_at, updated_at
            ) VALUES (
                :telegram_id, :username, :url, :type,
                :title, :description, :avatar,
                :count, :last_active,
                :valid, :private, :keep, :filter_reason,
                :created_at, :updated_at
            )
        """, data)
    conn.commit()


def parse_subscriber_text(text: str) -> tuple[str | None, int | None]:
    text = text.strip()
    if not text:
        return None, None

    m = re.search(r"([\d\s\xa0]+)\s*subscribers?", text, re.IGNORECASE)
    if m:
        count = int(m.group(1).replace(" ", "").replace("\xa0", ""))
        return "channel", count

    m = re.search(r"([\d\s\xa0]+)\s*members?", text, re.IGNORECASE)
    if m:
        count = int(m.group(1).replace(" ", "").replace("\xa0", ""))
        return "group", count

    m = re.search(r"([\d\s\xa0]+)\s*monthly\s*users?", text, re.IGNORECASE)
    if m:
        count = int(m.group(1).replace(" ", "").replace("\xa0", ""))
        return "bot", count

    return None, None


def crawl_page(session: requests.Session, url: str, username: str | None) -> dict:
    result = {
        "url": url,
        "username": username,
        "telegram_id": None,
        "valid": 0,
        "private": 0,
        "type": None,
        "title": None,
        "description": None,
        "avatar": None,
        "count": None,
        "last_active": None,
    }

    if username is None:
        result["private"] = 1
        log.debug("  跳过: 无 username（私有邀请链接）")
        return result

    canonical_url = f"https://t.me/{username}"
    log.debug("  GET %s", canonical_url)
    resp = _request_with_retry(session, canonical_url)
    if resp is None or resp.status_code != 200:
        log.debug("  HTTP 失败: %s", resp.status_code if resp else "无响应")
        return result

    soup = BeautifulSoup(resp.text, "lxml")
    result["valid"] = 1

    page_text = soup.get_text(separator=" ", strip=True).lower()
    private_keywords = [
        "this channel is private",
        "this group is private",
        "this channel can't be displayed",
    ]
    extra_div = soup.find("div", class_="tgme_page_extra")
    if any(kw in page_text for kw in private_keywords):
        if not extra_div or not extra_div.get_text(strip=True):
            result["private"] = 1

    og_title = soup.find("meta", property="og:title")
    if og_title:
        title = og_title.get("content", "").strip()
        title = re.sub(r"^Telegram:\s*(Contact|View|Launch)\s*@?\s*", "", title)
        if title:
            result["title"] = title

    og_desc = soup.find("meta", property="og:description")
    if og_desc:
        result["description"] = og_desc.get("content", "").strip()

    og_image = soup.find("meta", property="og:image")
    if og_image:
        avatar_url = og_image.get("content", "").strip()
        if avatar_url and "telegram.org/img/" not in avatar_url:
            result["avatar"] = avatar_url

    if extra_div:
        extra_text = extra_div.get_text(strip=True)
        detected_type, count = parse_subscriber_text(extra_text)
        if detected_type:
            result["type"] = detected_type
            result["count"] = count

    return result


def crawl_preview_page(session: requests.Session, username: str) -> dict:
    info = {"last_active": None, "telegram_id": None}
    url = f"https://t.me/s/{username}"
    log.debug("  GET %s", url)
    resp = _request_with_retry(session, url)
    if resp is None or resp.status_code != 200:
        log.debug("  /s/ 页面不可用")
        return info

    soup = BeautifulSoup(resp.text, "lxml")
    data_view_el = soup.find(attrs={"data-view": True})
    if data_view_el:
        try:
            raw = data_view_el["data-view"]
            padding = 4 - len(raw) % 4
            if padding != 4:
                raw += "=" * padding
            decoded = base64.b64decode(raw).decode("utf-8")
            view_data = json.loads(decoded)
            if "c" in view_data:
                short_id = view_data["c"]
                info["telegram_id"] = int(f"-100{abs(short_id)}")
        except Exception as e:
            log.debug("  解析 telegram_id 失败: %s", e)

    date_elements = soup.find_all(attrs={"datetime": True})
    if date_elements:
        dates = [d["datetime"] for d in date_elements]
        dates.sort()
        if dates:
            info["last_active"] = dates[-1]
    else:
        time_elements = soup.find_all("time")
        dates = [t.get("datetime") for t in time_elements if t.get("datetime")]
        if dates:
            dates.sort()
            info["last_active"] = dates[-1]

    return info


def _request_with_retry(
    session: requests.Session,
    url: str,
    max_retries: int = MAX_RETRIES,
):
    for attempt in range(max_retries):
        try:
            resp = session.get(url, headers=HEADERS, timeout=15)
        except requests.RequestException as e:
            log.warning("  ⚠ 请求异常: %s", e)
            if attempt < max_retries - 1:
                wait = min(RETRY_BASE * (2 ** attempt), RETRY_MAX)
                log.info("  ⏳ 等待 %ds 后重试 (第 %d/%d 次)...", wait, attempt + 1, max_retries)
                time.sleep(wait)
                continue
            return None

        if resp.status_code == 429:
            wait = min(RETRY_BASE * (2 ** attempt), RETRY_MAX)
            log.warning("  ⚠ 429 Too Many Requests，等待 %ds... (第 %d/%d 次)", wait, attempt + 1, max_retries)
            time.sleep(wait)
            continue

        log.debug("  HTTP %d (%d bytes)", resp.status_code, len(resp.content))
        return resp

    return None


def main():
    global log

    parser = argparse.ArgumentParser(description="Telegram 公开页面爬虫")
    parser.add_argument("--limit", type=int, default=0, help="限制爬取数量（0=全部）")
    parser.add_argument("--new", action="store_true", help="只爬取尚未爬过的新链接，不刷新旧数据")
    parser.add_argument("--no-resume", action="store_true", help="清空 entries 表，从头开始")
    parser.add_argument("--no-active", action="store_true", help="跳过 /s/ 页面爬取")
    parser.add_argument("--older-than-days", type=int, default=30, help="默认刷新多少天前的旧 entries（默认 30）")
    args = parser.parse_args()

    log = setup_logging(LOG_PATH)

    log.info("=" * 60)
    log.info("  Telegram 公开页面爬虫")
    log.info("  启动时间: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("  日志文件: %s", LOG_PATH)
    log.info("=" * 60)

    if not DB_PATH.exists():
        log.error("❌ 未找到数据库: %s", DB_PATH)
        log.error("   请先运行: python3 scripts/parse_links.py")
        sys.exit(1)

    conn = init_db(DB_PATH)

    if args.no_resume:
        conn.execute("DELETE FROM entries")
        conn.commit()
        log.info("🗑️  已清空 entries 表")

    if args.no_resume:
        links = conn.execute("""
            SELECT url, username, name, type_hint FROM links ORDER BY id
        """).fetchall()
        log.info("🔁 全量重爬模式")
    elif args.new:
        links = conn.execute("""
            SELECT l.url, l.username, l.name, l.type_hint
            FROM links l
            LEFT JOIN entries e ON l.url = e.url OR (l.username IS NOT NULL AND l.username = e.username)
            WHERE e.id IS NULL
            ORDER BY l.id
        """).fetchall()
        log.info("🆕 只爬新链接")
    else:
        cutoff = (datetime.now() - timedelta(days=max(args.older_than_days, 0))).isoformat()
        links = conn.execute("""
            SELECT l.url, l.username, l.name, l.type_hint
            FROM links l
            LEFT JOIN entries e ON l.url = e.url OR (l.username IS NOT NULL AND l.username = e.username)
            WHERE e.id IS NULL OR e.updated_at IS NULL OR e.updated_at < ?
            ORDER BY l.id
        """, (cutoff,)).fetchall()
        log.info("♻️  爬新链接，并刷新 %d 天前的旧数据", max(args.older_than_days, 0))

    links = [dict(row) for row in links]

    if not links:
        if args.new:
            log.info("✅ 没有新链接需要爬取")
        elif args.no_resume:
            log.error("❌ links 表为空，请先运行: python3 scripts/parse_links.py")
        else:
            log.info("✅ 没有新链接或过期数据需要爬取")
        sys.exit(0)

    total_links = conn.execute("SELECT COUNT(*) FROM links").fetchone()[0]
    total_entries = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
    log.info("")
    log.info("📊 数据库概览:")
    log.info("   links 表:   %d 条", total_links)
    log.info("   entries 表: %d 条", total_entries)
    log.info("   待爬取:     %d 条", len(links))

    if args.limit > 0:
        links = links[:args.limit]
        log.info("   限制爬取:   前 %d 个", args.limit)

    session = requests.Session()
    request_count = 0
    total = len(links)
    tracker = ProgressTracker(total)

    log.info("")
    log.info("🕷️  开始爬取...")
    log.info("-" * 60)

    for i, link in enumerate(links):
        url = link["url"]
        username = link["username"]

        log.info("")
        log.info("[%d/%d] 🔍 %s", i + 1, total, link["name"])
        log.info("       %s", url)

        result = crawl_page(session, url, username)
        request_count += 1

        if result["type"] is None and link.get("type_hint"):
            result["type"] = link["type_hint"]
            log.debug("  类型由 type_hint 推断: %s", link["type_hint"])

        if (
            not args.no_active
            and result.get("valid")
            and result.get("type") == "channel"
            and not result.get("private")
            and username
        ):
            _random_delay()
            preview = crawl_preview_page(session, username)
            result["last_active"] = preview["last_active"]
            if preview["telegram_id"]:
                result["telegram_id"] = preview["telegram_id"]
            request_count += 1

        result["keep"] = 1
        result["filter_reason"] = ""

        if result.get("valid"):
            type_label = {"channel": "频道", "group": "群组", "bot": "机器人"}.get(result.get("type"), "未知")
            count_val = result.get("count")
            count_str = f"{count_val:,}" if count_val is not None else "-"
            log.info("       ✅ 记录 | %s | %s", type_label, count_str)
            if result.get("telegram_id"):
                log.debug("       🆔 ID: %s", result["telegram_id"])
            if result.get("last_active"):
                log.debug("       📅 最后活跃: %s", result["last_active"])
        else:
            log.info("       ❌ 无效链接")

        tracker.tick(bool(result.get("valid")))
        upsert_entry(conn, result)

        if (i + 1) % 10 == 0:
            log.info("")
            log.info("📈 %s", tracker.progress_str())

        _random_delay()

        if request_count > 0 and request_count % BATCH_SIZE == 0:
            log.info("")
            log.info("⏸️  已爬 %d 次请求，暂停 %ds...", request_count, BATCH_PAUSE)
            time.sleep(BATCH_PAUSE)
            log.info("▶️  继续爬取...")

    stats = conn.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN valid = 1 THEN 1 ELSE 0 END) as valid_count,
            SUM(CASE WHEN valid = 0 THEN 1 ELSE 0 END) as invalid_count,
            SUM(CASE WHEN type = 'channel' AND valid = 1 THEN 1 ELSE 0 END) as channels,
            SUM(CASE WHEN type = 'group' AND valid = 1 THEN 1 ELSE 0 END) as groups,
            SUM(CASE WHEN type = 'bot' AND valid = 1 THEN 1 ELSE 0 END) as bots
        FROM entries
    """).fetchone()

    conn.close()

    log.info("")
    log.info("=" * 60)
    log.info("  📊 爬取完成")
    log.info("=" * 60)
    log.info("  %s", tracker.summary_str())
    log.info("")
    log.info("  数据库 entries 表:")
    log.info("    总条目:    %s", stats['total'])
    log.info("    有效:      %s", stats['valid_count'])
    log.info("    无效:      %s", stats['invalid_count'])
    log.info("    ├ 频道:    %s", stats['channels'])
    log.info("    ├ 群组:    %s", stats['groups'])
    log.info("    └ 机器人:  %s", stats['bots'])
    log.info("")
    log.info("  日志: %s", LOG_PATH)
    log.info("  数据库: %s", DB_PATH)


def _random_delay():
    delay = random.uniform(MIN_DELAY, MAX_DELAY)
    time.sleep(delay)


if __name__ == "__main__":
    main()
