"""Central category definitions for TG 索引."""
from __future__ import annotations

CATEGORY_ORDER = [
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

CATEGORY_ALIASES = {
    "💎 加密货币": "🪙 加密货币",
    "💰 加密货币": "🪙 加密货币",
}

TOP_CATEGORY_ORDER = [
    "📰 资讯内容",
    "💻 技术资源",
    "🎬 影音娱乐",
    "👥 生活社群",
    "🧭 工具导航",
]

CATEGORY_GROUPS = {
    "📰 新闻快讯": "📰 资讯内容",
    "🪙 加密货币": "📰 资讯内容",
    "📡 社媒搬运": "📰 资讯内容",
    "🏀 体育运动": "📰 资讯内容",
    "💻 数码科技": "💻 技术资源",
    "👨‍💻 开发运维": "💻 技术资源",
    "🔒 信息安全": "💻 技术资源",
    "🧰 软件工具": "💻 技术资源",
    "✈️ 科学上网": "💻 技术资源",
    "🎬 影视剧集": "🎬 影音娱乐",
    "🎵 音乐音频": "🎬 影音娱乐",
    "🎐 动漫次元": "🎬 影音娱乐",
    "🎮 游戏娱乐": "🎬 影音娱乐",
    "☁️ 网盘资源": "🎬 影音娱乐",
    "📚 学习阅读": "👥 生活社群",
    "🎨 创意设计": "👥 生活社群",
    "👗 生活消费": "👥 生活社群",
    "🌍 地区社群": "👥 生活社群",
    "💬 闲聊交友": "👥 生活社群",
    "🗂️ 综合导航": "🧭 工具导航",
    "🌐 综合其他": "🧭 工具导航",
    "🤖 机器人": "🧭 工具导航",
    "🆕 新发现频道": "🧭 工具导航",
}


def normalize_category(category: str | None) -> str | None:
    if category is None:
        return None
    value = category.strip()
    if not value:
        return None
    return CATEGORY_ALIASES.get(value, value)


def get_top_category(category: str | None) -> str:
    normalized = normalize_category(category)
    if not normalized:
        return "🧭 工具导航"
    return CATEGORY_GROUPS.get(normalized, "🧭 工具导航")


def category_sort_key(category: str | None) -> tuple[int, str]:
    value = normalize_category(category) or ""
    if value in CATEGORY_ORDER:
        return CATEGORY_ORDER.index(value), value
    return len(CATEGORY_ORDER), value


def top_category_sort_key(category: str | None) -> tuple[int, str]:
    value = category or ""
    if value in TOP_CATEGORY_ORDER:
        return TOP_CATEGORY_ORDER.index(value), value
    return len(TOP_CATEGORY_ORDER), value
