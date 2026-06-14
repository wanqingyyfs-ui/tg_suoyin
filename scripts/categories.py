"""Central category definitions for TG 索引."""
from __future__ import annotations

# 一级分类只做大方向，不做过细拆分；顺序同时影响前台展示和低分并列时的兜底排序。
CATEGORY_ORDER = [
    "📰 新闻政经",
    "💻 科技AI",
    "🧰 软件工具",
    "🎬 影视音乐",
    "🎮 游戏动漫",
    "📚 学习知识",
    "💼 商业职场",
    "💰 财经投资",
    "💎 加密Web3",
    "🎲 博彩资源",
    "🔞 成人资源",
    "🩶 灰产资源",
    "🛡️ 军事安全",
    "🏥 健康运动",
    "🏠 生活消费",
    "🌍 地区本地",
    "👥 兴趣社群",
    "🏛️ 人文社会",
    "🚗 汽车交通",
    "🛒 电商交易",
    "🏘️ 房产家居",
    "📢 营销广告",
    "🤖 机器人服务",
    "🧭 综合导航",
]

DEFAULT_CATEGORY = {
    "channel": "🧭 综合导航",
    "group": "👥 兴趣社群",
    "bot": "🤖 机器人服务",
}

# 历史分类统一归并到当前 24 个大类。
CATEGORY_ALIASES = {
    "📰 资讯内容": "📰 新闻政经",
    "📰 新闻资讯": "📰 新闻政经",
    "📰 新闻快讯": "📰 新闻政经",
    "📡 社媒搬运": "📰 新闻政经",

    "💻 技术资源": "💻 科技AI",
    "💻 科技开发": "💻 科技AI",
    "💻 数码科技": "💻 科技AI",
    "👨‍💻 开发运维": "💻 科技AI",
    "🔒 信息安全": "💻 科技AI",
    "✈️ 科学上网": "💻 科技AI",

    "🧰 软件工具": "🧰 软件工具",
    "🤖 机器人": "🤖 机器人服务",
    "🤖 机器人服务": "🤖 机器人服务",

    "🎬 影音娱乐": "🎬 影视音乐",
    "🎬 影视剧集": "🎬 影视音乐",
    "🎵 音乐音频": "🎬 影视音乐",
    "☁️ 网盘资源": "🎬 影视音乐",

    "🎐 动漫次元": "🎮 游戏动漫",
    "🎮 游戏娱乐": "🎮 游戏动漫",

    "📚 学习阅读": "📚 学习知识",
    "📚 学习知识": "📚 学习知识",
    "🎨 创意设计": "📚 学习知识",

    "👗 生活消费": "🏠 生活消费",
    "👥 生活社群": "👥 兴趣社群",
    "💬 闲聊交友": "👥 兴趣社群",
    "🌍 地区社群": "🌍 地区本地",

    "💎 加密货币": "💎 加密Web3",
    "🪙 加密货币": "💎 加密Web3",
    "💰 加密货币": "💎 加密Web3",
    "💎 加密Web3": "💎 加密Web3",

    "🎲 博彩竞猜": "🎲 博彩资源",
    "🎲 博彩资源": "🎲 博彩资源",
    "🔞 成人娱乐": "🔞 成人资源",
    "🔞 成人资源": "🔞 成人资源",
    "⚠️ 高风险行业": "🩶 灰产资源",
    "🩶 灰产资源": "🩶 灰产资源",

    "🏀 体育运动": "🏥 健康运动",
    "🏥 健康运动": "🏥 健康运动",
    "🛡️ 军事安全": "🛡️ 军事安全",
    "🏛️ 人文社会": "🏛️ 人文社会",
    "🚗 汽车交通": "🚗 汽车交通",
    "🛒 电商交易": "🛒 电商交易",
    "🏘️ 房产家居": "🏘️ 房产家居",
    "📢 营销广告": "📢 营销广告",

    "🧭 工具导航": "🧭 综合导航",
    "🗂️ 综合导航": "🧭 综合导航",
    "🌐 综合其他": "🧭 综合导航",
    "🆕 新发现频道": "🧭 综合导航",
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
