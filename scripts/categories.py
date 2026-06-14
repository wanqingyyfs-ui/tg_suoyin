"""Central category definitions for TG 索引."""
from __future__ import annotations

# 只保留少量大类，避免前台分类过细、过杂。
CATEGORY_ORDER = [
    "📰 新闻资讯",
    "💻 科技开发",
    "🧰 软件工具",
    "🎬 影音娱乐",
    "📚 学习阅读",
    "👥 生活社群",
    "💎 加密货币",
    "🧭 综合导航",
]

DEFAULT_CATEGORY = {
    "channel": "🧭 综合导航",
    "group": "👥 生活社群",
    "bot": "🧰 软件工具",
}

# 历史分类统一归并到当前大类。
# 注意：机器人是资源类型，不是内容主题；历史“🤖 机器人”统一归入软件工具。
CATEGORY_ALIASES = {
    "📰 资讯内容": "📰 新闻资讯",
    "📰 新闻快讯": "📰 新闻资讯",
    "📡 社媒搬运": "📰 新闻资讯",
    "🏀 体育运动": "📰 新闻资讯",
    "💻 技术资源": "💻 科技开发",
    "💻 数码科技": "💻 科技开发",
    "👨‍💻 开发运维": "💻 科技开发",
    "🔒 信息安全": "💻 科技开发",
    "✈️ 科学上网": "💻 科技开发",
    "🧰 软件工具": "🧰 软件工具",
    "☁️ 网盘资源": "🎬 影音娱乐",
    "🎬 影视剧集": "🎬 影音娱乐",
    "🎵 音乐音频": "🎬 影音娱乐",
    "🎐 动漫次元": "🎬 影音娱乐",
    "🎮 游戏娱乐": "🎬 影音娱乐",
    "📚 学习阅读": "📚 学习阅读",
    "🎨 创意设计": "📚 学习阅读",
    "👗 生活消费": "👥 生活社群",
    "🌍 地区社群": "👥 生活社群",
    "💬 闲聊交友": "👥 生活社群",
    "🧭 工具导航": "🧭 综合导航",
    "🗂️ 综合导航": "🧭 综合导航",
    "🌐 综合其他": "🧭 综合导航",
    "🆕 新发现频道": "🧭 综合导航",
    "🤖 机器人": "🧰 软件工具",
    "🪙 加密货币": "💎 加密货币",
    "💰 加密货币": "💎 加密货币",
}

FORCED_CATEGORY_REPLACEMENTS = {
    key: value
    for key, value in CATEGORY_ALIASES.items()
    if key not in CATEGORY_ORDER and value in CATEGORY_ORDER
}

# 当前前台一级分类也使用同一组大类。
TOP_CATEGORY_ORDER = CATEGORY_ORDER[:]

CATEGORY_GROUPS = {category: category for category in CATEGORY_ORDER}


def normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    value = category.strip()
    if not value:
        return None
    return CATEGORY_ALIASES.get(value, value if value in CATEGORY_ORDER else "🧭 综合导航")


def normalize_entry_category(category: str | None, entry_type: str | None = None) -> str:
    normalized = normalize_category(category)
    if normalized in CATEGORY_ORDER:
        return normalized
    return DEFAULT_CATEGORY.get((entry_type or "").strip().lower(), "🧭 综合导航")


def get_top_category(category: str | None) -> str:
    normalized = normalize_category(category)
    if not normalized:
        return "🧭 综合导航"
    return CATEGORY_GROUPS.get(normalized, "🧭 综合导航")


def category_sort_key(category: str | None) -> tuple[int, str]:
    value = normalize_category(category) or ""
    if value in CATEGORY_ORDER:
        return CATEGORY_ORDER.index(value), value
    return len(CATEGORY_ORDER), value


def top_category_sort_key(category: str | None) -> tuple[int, str]:
    value = normalize_category(category) or ""
    if value in TOP_CATEGORY_ORDER:
        return TOP_CATEGORY_ORDER.index(value), value
    return len(TOP_CATEGORY_ORDER), value
