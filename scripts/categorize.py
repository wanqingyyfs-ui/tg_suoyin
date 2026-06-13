#!/usr/bin/env python3
"""Clean, filter and assign broad categories for TG 索引 entries."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import emoji

from categories import CATEGORY_ORDER, normalize_category
from filter_rules import evaluate_entry

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rectg.db"

CATEGORY_KEYWORDS = {
    "💎 加密货币": ["加密货币", "币圈", "区块链", "btc", "eth", "web3", "nft", "数字货币", "比特币", "以太坊"],
    "📰 新闻资讯": ["新闻", "快讯", "日报", "早报", "时报", "媒体", "报道", "资讯", "财经", "rss", "微博", "twitter", "体育", "足球", "篮球", "nba"],
    "💻 科技开发": ["科技", "数码", "硬件", "apple", "苹果", "安卓", "android", "ios", "mac", "windows", "ai", "chatgpt", "openai", "开源", "代码", "github", "开发", "程序员", "前端", "后端", "python", "linux", "java", "golang", "服务器", "docker", "网络工具"],
    "🧰 软件工具": ["软件", "app", "apk", "工具", "快捷指令", "脚本", "翻译", "translate", "notion", "bot", "机器人", "自动化", "插件", "扩展", "浏览器", "客户端", "效率"],
    "🎬 影音娱乐": ["电影", "影视", "影院", "电视剧", "剧集", "netflix", "4k", "美剧", "韩剧", "日剧", "纪录片", "音乐", "无损", "flac", "mp3", "音频", "播客", "动漫", "番剧", "二次元", "漫画", "游戏", "steam", "switch", "网盘", "阿里云盘", "夸克", "百度网盘", "资源分享"],
    "📚 学习阅读": ["学习", "英语", "日语", "电子书", "kindle", "epub", "pdf", "公开课", "课程", "教程", "读书", "期刊", "杂志", "博客", "知识", "资料", "设计", "ui", "ux", "字体", "艺术", "创意", "摄影"],
    "👥 生活社群": ["日常", "购物", "优惠", "折扣", "淘宝", "京东", "求职", "招聘", "旅游", "美食", "交友", "相亲", "闲聊", "聊天", "互助", "同好", "表情包", "北京", "上海", "深圳", "成都", "台湾", "香港", "大学", "柬埔寨", "金边"],
    "🧭 综合导航": ["导航", "搜群", "索引", "频道大全", "群组大全", "机器人大全", "telegram 中文", "电报中文", "新手", "指南", "目录", "收录"],
}

SPAM_PATTERNS = [
    r"点击链接", r"加入群组", r"关注我们", r"欢迎来到", r"本群规", r"进群请", r"商务合作", r"广告投放",
    r"联系群主", r"联系管理", r"投稿请联系", r"交流群", r"聊天群", r"备用频道", r"官方频道", r"最新地址",
]


def remove_emoji(text: str) -> str:
    return emoji.replace_emoji(text or "", replace="")


def clean_text(text: str, title: str = "") -> str:
    value = remove_emoji(text or "")
    value = re.sub(r"https?://[^\s]+", "", value)
    value = re.sub(r"t\.me/[^\s]+", "", value)
    value = re.sub(r"@\w+", "", value)
    for pattern in SPAM_PATTERNS:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = re.sub(r"\s{2,}", " ", value).strip(" 、，。！？：；-|~=*#")
    if len(value) > 100:
        value = value[:95].rstrip() + "..."
    if title and len(value) < 5 and value in title:
        value = f"关于 {title} 的相关讨论与分享。"
    return value.strip()


def clean_title(title: str) -> str:
    value = remove_emoji(title or "")
    value = re.sub(r"[【】\[\]《》<>|｜～~*]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def category_score(category: str, title_text: str, full_text: str, entry_type: str | None = None) -> int:
    score = 0
    for keyword in CATEGORY_KEYWORDS.get(category, []):
        key = keyword.lower()
        if key in title_text:
            score += 8
        if key in full_text:
            score += 3
    if entry_type == "bot" and category == "🧰 软件工具":
        score += 5
    return score


def determine_category(title: str, desc: str, entry_type: str | None = None) -> str:
    title_text = (title or "").lower()
    full_text = f"{title or ''} {desc or ''}".lower()
    scores = [(category_score(category, title_text, full_text, entry_type), category) for category in CATEGORY_ORDER]
    scores.sort(key=lambda item: (-item[0], CATEGORY_ORDER.index(item[1])))
    best_score, best_category = scores[0]
    return best_category if best_score > 0 else "🧭 综合导航"


def main() -> None:
    print("🧹 开始执行清洗、过滤与大类重整...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM entries WHERE keep=1").fetchall()
    print(f"处理保留的 {len(rows)} 条记录...")

    changed = 0
    filtered = 0
    cat_counts: dict[str, int] = {}

    for row in rows:
        entry = dict(row)
        title = entry.get("title") or ""
        desc = entry.get("description") or ""
        keep, filter_reason = evaluate_entry(entry)
        if not keep:
            conn.execute(
                "UPDATE entries SET keep=0, filter_reason=?, updated_at=datetime('now') WHERE id=?",
                (filter_reason, entry["id"]),
            )
            changed += 1
            filtered += 1
            print(f"  ❌ 过滤 ({filter_reason}): {title}")
            continue

        c_title = clean_title(title) or title
        c_desc = clean_text(desc, title) or "暂无详细简介。"
        category = normalize_category(determine_category(title, desc, entry.get("type"))) or "🧭 综合导航"
        conn.execute(
            "UPDATE entries SET clean_title=?, clean_desc=?, category=?, updated_at=datetime('now') WHERE id=?",
            (c_title, c_desc, category, entry["id"]),
        )
        changed += 1
        cat_counts[category] = cat_counts.get(category, 0) + 1

    conn.commit()
    conn.close()

    print(f"✅ 处理完成，共重新分类和清洗 {changed} 条记录，过滤 {filtered} 条。")
    print("\n📊 大类统计：")
    for cat, count in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat}: {count} 条")


if __name__ == "__main__":
    main()
