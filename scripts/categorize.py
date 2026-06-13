#!/usr/bin/env python3
"""Clean, filter and assign fine categories for TG 索引 entries."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import emoji

from categories import CATEGORY_ORDER, normalize_category
from filter_rules import evaluate_entry

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rectg.db"

RULE_CONTEXT_RE = re.compile(
    r"(禁止|严禁|不准|不允许|拒绝|谢绝|不发|不开|请勿|限制|不得|请不要|不要)"
    r"[^。！？；\n]{0,120}"
    r"(广告|低俗|违规|违法|盗版|破解|黑产|灰产|钓鱼)"
    r"[^。！？；\n]{0,120}",
    re.IGNORECASE,
)

CATEGORY_KEYWORDS = {
    "📰 新闻快讯": ["新闻", "快讯", "日报", "早报", "时报", "媒体", "报道", "财经", "财新", "华尔街", "金融时报", "rss"],
    "🪙 加密货币": ["加密货币", "币圈", "区块链", "btc", "eth", "web3", "nft", "交易所", "数字货币", "比特币", "以太坊"],
    "💻 数码科技": ["科技", "数码", "硬件", "apple", "苹果", "安卓", "ios", "mac", "windows", "手机", "测评", "极客", "ai", "chatgpt", "openai"],
    "👨‍💻 开发运维": ["开源", "代码", "github", "开发", "程序员", "前端", "后端", "python", "linux", "java", "golang", "运维", "编程", "服务器", "vps", "docker"],
    "🔒 信息安全": ["信息安全", "安全技术", "隐私", "privacy", "渗透", "防护", "密码学", "adguard"],
    "🧰 软件工具": ["软件", "app", "apk", "工具", "神器", "快捷指令", "脚本", "翻译", "translate", "simpread", "notion"],
    "☁️ 网盘资源": ["网盘", "阿里云盘", "夸克", "百度云", "百度网盘", "天翼", "迅雷", "115", "资源分享", "google drive"],
    "🎬 影视剧集": ["电影", "影视", "影院", "电视剧", "剧集", "网飞", "netflix", "4k", "美剧", "韩剧", "日剧", "纪录片", "emby"],
    "🎵 音乐音频": ["音乐", "无损", "flac", "mp3", "音频", "网易云", "歌单", "播客", "podcast"],
    "🎐 动漫次元": ["动漫", "番剧", "二次元", "acg", "追番", "漫画", "轻小说", "同人", "pixiv", "galgame", "萌图"],
    "🎮 游戏娱乐": ["游戏", "手游", "端游", "主机", "steam", "switch", "ps5", "xbox", "电竞", "开黑", "狼人杀"],
    "✈️ 科学上网": ["节点", "代理", "vpn", "机场", "科学上网", "翻墙", "v2ray", "clash", "shadowsocks", "trojan", "surge", "quantumult", "loon"],
    "📚 学习阅读": ["学习", "外语", "英语", "日语", "电子书", "kindle", "epub", "pdf", "公开课", "课程", "教程", "读书", "期刊", "杂志", "博客"],
    "📡 社媒搬运": ["推特", "twitter", "微博", "reddit", "微信搬运", "公众号"],
    "🎨 创意设计": ["设计", "design", "ui", "ux", "字体", "美术", "艺术", "创意", "品牌"],
    "🏀 体育运动": ["体育", "足球", "篮球", "nba", "cba", "运动", "健身", "世界杯", "欧冠"],
    "👗 生活消费": ["日常", "购物", "优惠", "折扣", "淘宝", "京东", "拼多多", "求职", "招聘", "旅游", "美食", "壁纸", "摄影", "亚马逊", "amazon"],
    "🌍 地区社群": ["湖南", "广西", "四川", "西安", "济南", "周口", "河南", "北京", "上海", "广东", "深圳", "成都", "台湾", "香港", "大学"],
    "💬 闲聊交友": ["交友", "相亲", "闲聊", "水群", "吹水", "单身", "聊天", "互助", "同好", "表情包", "贴纸", "趣事", "猫", "树洞", "v2ex"],
    "🗂️ 综合导航": ["导航", "搜群", "索引", "频道大全", "群组大全", "机器人大全", "telegram 中文", "电报中文", "新手", "指南"],
    "🤖 机器人": ["bot", "机器人"],
}

SPAM_PATTERNS = [
    r"点击链接", r"加入群组", r"关注我们", r"点此加入", r"欢迎来到", r"点击关注",
    r"本群规", r"进群请", r"防失联", r"解封说明", r"商务合作", r"广告投放",
    r"联系群主", r"联系管理", r"投稿请联系", r"交流群", r"聊天群", r"备用频道",
    r"官方频道", r"最新地址", r"请看置顶", r"获取最新", r"合作：", r"联系：", r"客服：",
]


def remove_emoji(text: str) -> str:
    if not text:
        return ""
    return emoji.replace_emoji(text, replace="")


def remove_rule_context(text: str) -> str:
    return RULE_CONTEXT_RE.sub("", text or "")


def clean_text(text: str, title: str = "") -> str:
    if not text:
        return ""
    value = remove_emoji(text)
    value = re.sub(r"https?://[^\s]+", "", value)
    value = re.sub(r"t\.me/[^\s]+", "", value)
    value = re.sub(r"@\w+", "", value)
    value = re.sub(r"tg://[^\s]+", "", value)
    value = remove_rule_context(value)
    for pattern in SPAM_PATTERNS:
        value = re.sub(pattern, "", value, flags=re.IGNORECASE)
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = re.sub(r"\s{2,}", " ", value)
    value = re.sub(r"^[、，。！？：；\-|~= *#]+|[、，。！？：；\-|~= *#]+$", "", value.strip())
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


def determine_category(title: str, desc: str, entry_type: str | None = None) -> str:
    if entry_type == "bot":
        return "🤖 机器人"
    title_text = (title or "").lower()
    full_text = remove_rule_context(f"{title or ''} {desc or ''}").lower()
    for category in CATEGORY_ORDER:
        keywords = CATEGORY_KEYWORDS.get(category, [])
        if any(keyword.lower() in title_text for keyword in keywords):
            return category
    for category in CATEGORY_ORDER:
        keywords = CATEGORY_KEYWORDS.get(category, [])
        if any(keyword.lower() in full_text for keyword in keywords):
            return category
    return "🌐 综合其他"


def main() -> None:
    print("🧹 开始执行清洗、过滤与细分类整理...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM entries WHERE keep=1").fetchall()
    print(f"处理保留的 {len(rows)} 条记录...")

    changed = 0
    filtered_harmful = 0
    filtered_lang = 0
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
            if filter_reason == "有害内容":
                filtered_harmful += 1
            elif filter_reason in ("非中文内容", "繁体中文内容"):
                filtered_lang += 1
            print(f"  ❌ 过滤 ({filter_reason}): {title}")
            continue

        c_title = clean_title(title) or title
        c_desc = clean_text(desc, title) or "暂无详细简介。"
        category = normalize_category(determine_category(title, desc, entry.get("type"))) or "🌐 综合其他"
        conn.execute(
            "UPDATE entries SET clean_title=?, clean_desc=?, category=?, updated_at=datetime('now') WHERE id=?",
            (c_title, c_desc, category, entry["id"]),
        )
        changed += 1
        cat_counts[category] = cat_counts.get(category, 0) + 1

    conn.commit()
    conn.close()

    print(f"✅ 处理完成，共重新分类和清洗 {changed} 条记录！")
    if filtered_harmful > 0 or filtered_lang > 0:
        print(f"   其中排除了 {filtered_harmful} 条有害内容，{filtered_lang} 条非简中内容。")
    print("\n📊 细分类统计 (留存项目):")
    for cat, count in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat}: {count} 条")


if __name__ == "__main__":
    main()
