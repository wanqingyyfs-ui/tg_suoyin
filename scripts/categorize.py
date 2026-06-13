#!/usr/bin/env python3
"""Clean, filter and assign accurate broad categories for TG 索引 entries."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import emoji

from categories import CATEGORY_ORDER, normalize_category
from filter_rules import evaluate_entry

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rectg.db"

# 分类原则：少量大类 + 高置信度。标题和 username 权重大于简介，短英文词必须边界匹配。
CATEGORY_RULES = {
    "💎 加密货币": {
        "strong": ["加密货币", "数字货币", "区块链", "比特币", "以太坊", "币圈", "链上", "web3"],
        "normal": ["btc", "eth", "bitcoin", "ethereum", "nft", "defi", "空投", "合约", "交易所", "币安", "binance"],
        "weak": ["crypto", "token", "wallet", "钱包"],
        "negative": ["电影", "音乐", "网盘", "课程", "招聘", "求职"],
    },
    "📰 新闻资讯": {
        "strong": ["新闻", "快讯", "日报", "早报", "晚报", "时报", "周报", "简报", "媒体", "报道", "资讯"],
        "normal": ["财经", "财新", "路透", "华尔街", "金融时报", "rss", "微博", "twitter", "x", "reddit", "公众号", "时事", "国际", "政治", "社会"],
        "weak": ["体育", "足球", "篮球", "nba", "世界杯", "欧冠", "订阅", "推送"],
        "negative": ["电影", "音乐", "动漫", "游戏", "网盘", "课程", "教程", "招聘", "交友"],
    },
    "💻 科技开发": {
        "strong": ["开发", "编程", "程序员", "代码", "开源", "github", "前端", "后端", "运维", "服务器", "技术", "科技"],
        "normal": ["python", "java", "golang", "linux", "docker", "kubernetes", "api", "数据库", "算法", "安全", "隐私", "数码", "硬件", "苹果", "安卓", "android", "ios", "mac", "windows", "ai", "openai", "chatgpt"],
        "weak": ["vps", "nas", "路由器", "网络工具", "测试", "测评", "极客", "手机", "电脑"],
        "negative": ["电影", "电视剧", "音乐", "动漫", "游戏", "电子书", "课程", "招聘", "交友", "美食"],
    },
    "🧰 软件工具": {
        "strong": ["软件", "工具", "插件", "扩展", "脚本", "自动化", "机器人", "快捷指令", "效率工具"],
        "normal": ["app", "apk", "bot", "客户端", "浏览器", "翻译", "translate", "notion", "下载器", "播放器", "编辑器", "同步", "备份"],
        "weak": ["效率", "生产力", "整理", "助手", "服务", "平台"],
        "negative": ["电影", "电视剧", "音乐", "动漫", "游戏", "电子书", "课程", "新闻", "招聘", "交友"],
    },
    "🎬 影音娱乐": {
        "strong": ["电影", "影视", "影院", "电视剧", "剧集", "纪录片", "动漫", "番剧", "漫画", "游戏", "音乐", "网盘"],
        "normal": ["netflix", "4k", "美剧", "韩剧", "日剧", "无损", "flac", "mp3", "音频", "播客", "podcast", "二次元", "acg", "steam", "switch", "ps5", "xbox", "阿里云盘", "夸克", "百度网盘", "资源分享"],
        "weak": ["娱乐", "追剧", "歌单", "图片", "壁纸", "表情", "素材"],
        "negative": ["代码", "开发", "编程", "课程", "教程", "招聘", "求职", "新闻", "财经"],
    },
    "📚 学习阅读": {
        "strong": ["学习", "课程", "教程", "电子书", "读书", "阅读", "公开课", "资料", "知识", "期刊", "杂志"],
        "normal": ["英语", "日语", "kindle", "epub", "pdf", "博客", "论文", "学术", "考试", "考研", "设计", "字体", "摄影", "艺术", "创意", "ui", "ux"],
        "weak": ["笔记", "书单", "文档", "资源库", "素材", "练习", "分享"],
        "negative": ["电影", "电视剧", "音乐", "游戏", "招聘", "交友", "购物", "优惠"],
    },
    "👥 生活社群": {
        "strong": ["交友", "相亲", "闲聊", "聊天", "水群", "生活", "本地", "同城", "招聘", "求职", "美食", "旅游"],
        "normal": ["购物", "优惠", "折扣", "淘宝", "京东", "拼多多", "互助", "同好", "日常", "大学", "北京", "上海", "深圳", "成都", "广州", "香港", "台湾", "柬埔寨", "金边"],
        "weak": ["社群", "群友", "交流群", "讨论", "分享", "活动", "树洞", "猫", "摄影"],
        "negative": ["代码", "开发", "电影", "音乐", "课程", "教程", "新闻", "财经"],
    },
    "🧭 综合导航": {
        "strong": ["导航", "索引", "目录", "大全", "收录", "频道大全", "群组大全", "telegram 中文", "电报中文"],
        "normal": ["搜群", "搜索", "新手", "指南", "合集", "列表", "精选", "推荐", "入口"],
        "weak": ["资源", "分享", "频道", "群组"],
        "negative": [],
    },
}

SPAM_PATTERNS = [
    r"点击链接", r"加入群组", r"关注我们", r"欢迎来到", r"本群规", r"进群请", r"商务合作", r"广告投放",
    r"联系群主", r"联系管理", r"投稿请联系", r"交流群", r"聊天群", r"备用频道", r"官方频道", r"最新地址",
]

ASCII_RE = re.compile(r"^[a-z0-9][a-z0-9_.+-]*$", re.IGNORECASE)


def remove_emoji(text: str) -> str:
    return emoji.replace_emoji(text or "", replace="")


def normalize_text_for_match(text: str) -> str:
    value = remove_emoji(text or "").lower()
    value = re.sub(r"https?://[^\s]+", " ", value)
    value = re.sub(r"t\.me/[^\s]+", " ", value)
    value = re.sub(r"@\w+", " ", value)
    value = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def keyword_hit(text: str, keyword: str) -> bool:
    key = (keyword or "").lower().strip()
    if not key:
        return False
    if ASCII_RE.match(key):
        return re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])", text) is not None
    return key in text


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


def score_keywords(category: str, title_text: str, username_text: str, desc_text: str, entry_type: str | None) -> int:
    rules = CATEGORY_RULES.get(category, {})
    score = 0
    weights = {
        "strong": (30, 22, 10),
        "normal": (18, 13, 6),
        "weak": (8, 5, 2),
    }
    for group, (title_weight, username_weight, desc_weight) in weights.items():
        for keyword in rules.get(group, []):
            if keyword_hit(title_text, keyword):
                score += title_weight
            if keyword_hit(username_text, keyword):
                score += username_weight
            if keyword_hit(desc_text, keyword):
                score += desc_weight

    for keyword in rules.get("negative", []):
        if keyword_hit(title_text, keyword):
            score -= 16
        if keyword_hit(desc_text, keyword):
            score -= 8

    # 机器人不再是独立分类，但如果没有明显内容指向，通常属于软件工具。
    if entry_type == "bot" and category == "🧰 软件工具":
        score += 8

    return score


def determine_category(
    title: str,
    desc: str,
    entry_type: str | None = None,
    username: str = "",
) -> str:
    title_text = normalize_text_for_match(title)
    username_text = normalize_text_for_match(username)
    desc_text = normalize_text_for_match(desc)

    scores = [
        (score_keywords(category, title_text, username_text, desc_text, entry_type), category)
        for category in CATEGORY_ORDER
    ]
    scores.sort(key=lambda item: (-item[0], CATEGORY_ORDER.index(item[1])))
    best_score, best_category = scores[0]
    second_score = scores[1][0] if len(scores) > 1 else 0

    # 低置信度或强烈冲突时，不乱分，回到综合导航。
    if best_score < 10:
        return "🧭 综合导航"
    if best_score < 22 and best_score - second_score <= 3:
        return "🧭 综合导航"
    return best_category


def main() -> None:
    print("🧹 开始执行高准确率清洗、过滤与大类重整...")
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
        username = entry.get("username") or ""
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
        category = normalize_category(determine_category(title, desc, entry.get("type"), username)) or "🧭 综合导航"
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
