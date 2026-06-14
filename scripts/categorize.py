#!/usr/bin/env python3
"""Clean text and assign broad categories for TG 索引 entries."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import emoji

from categories import CATEGORY_ORDER, normalize_category

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rectg.db"

# 分类原则：一级大类覆盖面要宽，标题和 username 权重大于简介，短英文词必须边界匹配。
# 成人、博彩、灰产、地区、机器人等强业务属性优先识别，但群规/禁止语境不参与分类打分。
CATEGORY_RULES = {
    "📰 新闻政经": {
        "strong": ["新闻", "快讯", "日报", "早报", "晚报", "时报", "周报", "简报", "媒体", "报道", "政经", "时政", "时事"],
        "normal": ["国际", "社会", "政治", "热点", "观察", "评论", "深度", "财新", "路透", "华尔街", "金融时报", "rss", "微博", "twitter", "reddit", "公众号", "舆论"],
        "weak": ["订阅", "推送", "资讯", "搬运", "头条", "事件"],
        "negative": ["电影", "音乐", "动漫", "游戏", "课程", "招聘", "交友", "博彩", "成人"],
    },
    "💻 科技AI": {
        "strong": ["ai", "人工智能", "科技", "数码", "开发", "编程", "程序员", "代码", "开源", "github", "前端", "后端", "运维", "服务器", "技术"],
        "normal": ["chatgpt", "openai", "claude", "gemini", "python", "java", "golang", "linux", "docker", "kubernetes", "api", "数据库", "算法", "网络安全", "信息安全", "隐私", "硬件", "苹果", "安卓", "android", "ios", "mac", "windows", "vps", "nas"],
        "weak": ["路由器", "测评", "极客", "手机", "电脑", "芯片", "云计算", "模型", "提示词", "prompt"],
        "negative": ["电影", "电视剧", "音乐", "动漫", "游戏", "电子书", "课程", "招聘", "交友", "博彩", "成人"],
    },
    "🧰 软件工具": {
        "strong": ["软件", "工具", "插件", "扩展", "脚本", "自动化", "快捷指令", "效率工具", "下载器", "客户端"],
        "normal": ["app", "apk", "应用", "浏览器", "翻译", "translate", "notion", "播放器", "编辑器", "同步", "备份", "网盘工具", "生产力", "效率"],
        "weak": ["助手", "服务", "平台", "整理", "模板", "资源包"],
        "negative": ["电影", "电视剧", "音乐", "动漫", "游戏", "电子书", "课程", "新闻", "招聘", "交友", "博彩", "成人"],
    },
    "🎬 影视音乐": {
        "strong": ["电影", "影视", "影院", "电视剧", "剧集", "纪录片", "音乐", "无损", "网盘影视", "有声书"],
        "normal": ["netflix", "4k", "美剧", "韩剧", "日剧", "港剧", "综艺", "flac", "mp3", "音频", "播客", "podcast", "阿里云盘", "夸克", "百度网盘", "资源分享", "追剧", "歌单"],
        "weak": ["娱乐", "片源", "字幕", "蓝光", "bt", "磁力", "影评", "听歌"],
        "negative": ["代码", "开发", "编程", "课程", "教程", "招聘", "求职", "博彩", "成人"],
    },
    "🎮 游戏动漫": {
        "strong": ["游戏", "手游", "网游", "电竞", "动漫", "漫画", "番剧", "二次元", "acg"],
        "normal": ["steam", "switch", "ps5", "xbox", "主机", "原神", "崩铁", "王者", "和平精英", "lol", "dota", "cosplay", "cos", "galgame", "动画"],
        "weak": ["玩家", "开黑", "攻略", "礼包", "汉化", "mod", "皮肤"],
        "negative": ["电影", "电视剧", "课程", "招聘", "财经", "成人", "博彩"],
    },
    "📚 学习知识": {
        "strong": ["学习", "课程", "教程", "电子书", "读书", "阅读", "公开课", "资料", "知识", "论文", "学术"],
        "normal": ["英语", "日语", "韩语", "kindle", "epub", "pdf", "博客", "考试", "考研", "雅思", "托福", "设计", "字体", "摄影", "艺术", "创意", "ui", "ux", "文档", "书单"],
        "weak": ["笔记", "资源库", "素材", "练习", "分享", "百科", "课件", "自学"],
        "negative": ["电影", "电视剧", "音乐", "游戏", "招聘", "博彩", "成人"],
    },
    "💼 商业职场": {
        "strong": ["招聘", "求职", "工作", "职场", "创业", "远程工作", "自由职业", "项目合作", "副业"],
        "normal": ["运营", "管理", "营销", "商务", "简历", "面试", "岗位", "内推", "猎头", "外包", "兼职", "接单", "老板", "公司", "出海", "saas"],
        "weak": ["赚钱", "商业", "资源对接", "合作", "机会", "办公"],
        "negative": ["股票", "基金", "币圈", "电影", "成人", "博彩"],
    },
    "💰 财经投资": {
        "strong": ["财经", "投资", "股票", "基金", "理财", "宏观经济", "房产投资", "外汇"],
        "normal": ["a股", "港股", "美股", "期货", "债券", "银行", "估值", "研报", "财报", "交易", "市场", "经济", "金融", "资产", "房地产"],
        "weak": ["套利", "收益", "复盘", "风控", "投研", "财富"],
        "negative": ["btc", "eth", "币圈", "web3", "电影", "成人", "博彩"],
    },
    "💎 加密Web3": {
        "strong": ["加密货币", "数字货币", "区块链", "比特币", "以太坊", "币圈", "链上", "web3"],
        "normal": ["btc", "eth", "bitcoin", "ethereum", "nft", "defi", "空投", "合约", "交易所", "币安", "binance", "okx", "钱包", "token", "crypto", "撸毛"],
        "weak": ["链游", "铭文", "矿工", "矿池", "gas", "dex", "ido", "dao"],
        "negative": ["电影", "音乐", "课程", "招聘", "求职", "成人", "博彩"],
    },
    "🎲 博彩资源": {
        "strong": ["博彩", "赌博", "赌场", "彩票", "体育投注", "棋牌", "百家乐", "六合彩", "娱乐城", "真人娱乐"],
        "normal": ["盘口", "赔率", "下注", "投注", "电竞竞猜", "体育竞猜", "菠菜", "真人", "棋牌娱乐", "返水"],
        "weak": ["开奖", "计划", "跟单", "代理", "会员"],
        "negative": ["新闻", "学习", "电影", "编程", "禁止", "群规", "封禁", "黄赌毒"],
    },
    "🔞 成人资源": {
        "strong": ["成人", "色情", "福利", "写真", "女优", "番号", "成人视频", "成人资源", "擦边", "私房", "r18", "18+"],
        "normal": ["nsfw", "里番", "h动漫", "国产自拍", "福利姬", "裸聊", "约会", "情趣", "制服", "丝袜", "白丝", "黑丝", "性感", "绅士", "开车"],
        "weak": ["养眼", "小姐姐", "美图", "福利视频", "福利群", "资源群"],
        "negative": ["新闻", "学习", "编程", "招聘", "禁止", "群规", "封禁"],
    },
    "🩶 灰产资源": {
        "strong": ["灰产", "接码", "养号", "账号资源", "引流", "矩阵", "私域", "流量变现", "卡商", "号商"],
        "normal": ["注册", "账号", "流量", "项目", "渠道", "短信", "代实名", "实名", "拉新", "获客", "变现", "信息差", "工作室", "资源对接"],
        "weak": ["玩法", "项目资源", "渠道资源", "粉丝", "推广资源", "业务交流"],
        "negative": ["电影", "音乐", "课程", "新闻", "禁止", "群规", "封禁"],
    },
    "🛡️ 军事安全": {
        "strong": ["军事", "军迷", "国防", "武器", "装备", "战争", "战报", "地缘冲突", "安全局势"],
        "normal": ["俄乌", "巴以", "台海", "中东", "军工", "导弹", "无人机", "坦克", "舰艇", "空军", "陆军", "海军", "情报", "防务"],
        "weak": ["局势", "前线", "战场", "兵器", "军情", "观察"],
        "negative": ["游戏", "电影", "成人", "博彩"],
    },
    "🏥 健康运动": {
        "strong": ["健康", "医疗", "健身", "减脂", "运动", "体育", "心理", "养生"],
        "normal": ["医生", "医院", "营养", "跑步", "瑜伽", "篮球", "足球", "nba", "世界杯", "欧冠", "中医", "睡眠", "情绪", "训练", "减肥"],
        "weak": ["锻炼", "体检", "康复", "户外", "骑行", "球迷"],
        "negative": ["博彩", "成人", "电影", "编程"],
    },
    "🏠 生活消费": {
        "strong": ["生活", "美食", "购物", "优惠", "穿搭", "宠物", "母婴", "旅游", "吃喝玩乐"],
        "normal": ["折扣", "淘宝", "京东", "拼多多", "外卖", "餐厅", "咖啡", "酒店", "机票", "旅行", "日常", "家电", "猫", "狗"],
        "weak": ["分享", "好物", "省钱", "活动", "种草", "攻略"],
        "negative": ["代码", "开发", "电影", "课程", "博彩", "成人"],
    },
    "🌍 地区本地": {
        "strong": ["同城", "本地", "地区", "海外华人", "华人群", "本地服务", "城市", "金边", "柬埔寨"],
        "normal": ["北京", "上海", "深圳", "广州", "成都", "杭州", "香港", "台湾", "澳门", "日本", "东京", "大阪", "韩国", "新加坡", "泰国", "越南", "菲律宾", "美国", "加拿大", "澳洲", "迪拜", "缅甸", "老挝"],
        "weak": ["租房", "招聘", "生活群", "交流群", "互助", "找人", "服务"],
        "negative": ["电影", "音乐", "编程", "课程"],
    },
    "👥 兴趣社群": {
        "strong": ["交友", "相亲", "闲聊", "聊天", "水群", "树洞", "情感", "同好", "兴趣"],
        "normal": ["社群", "群友", "交流群", "讨论", "分享", "活动", "摄影", "爱好", "圈子", "日常", "大学", "校园"],
        "weak": ["吹水", "唠嗑", "互助", "朋友", "约饭", "聊天群"],
        "negative": ["代码", "开发", "电影", "课程", "财经", "博彩", "成人"],
    },
    "🏛️ 人文社会": {
        "strong": ["历史", "文化", "哲学", "宗教", "法律", "艺术", "文学", "人文", "社会议题"],
        "normal": ["法学", "心理学", "社会学", "政治学", "诗歌", "小说", "绘画", "博物馆", "考古", "传统文化", "思想", "伦理"],
        "weak": ["阅读", "讨论", "讲座", "资料", "文章"],
        "negative": ["成人", "博彩", "招聘", "股票"],
    },
    "🚗 汽车交通": {
        "strong": ["汽车", "摩托", "二手车", "车友", "交通", "物流", "货运", "出行"],
        "normal": ["租车", "买车", "卖车", "修车", "改装", "保养", "电动车", "司机", "配送", "快递", "运输", "车源"],
        "weak": ["路况", "拼车", "代驾", "车辆", "驾照"],
        "negative": ["电影", "游戏", "成人", "博彩"],
    },
    "🛒 电商交易": {
        "strong": ["电商", "货源", "批发", "代购", "二手交易", "供需", "买卖", "跨境电商"],
        "normal": ["店铺", "淘宝", "拼多多", "京东", "亚马逊", "虾皮", "shopee", "tiktok shop", "闲鱼", "优惠券", "供应链", "厂家", "拿货"],
        "weak": ["交易", "出货", "求购", "转让", "团购", "采购"],
        "negative": ["股票", "币圈", "电影", "成人", "博彩"],
    },
    "🏘️ 房产家居": {
        "strong": ["房产", "租房", "买房", "装修", "家居", "建材", "物业", "公寓", "地产"],
        "normal": ["房源", "办公室出租", "写字楼", "店铺出租", "合租", "整租", "民宿", "家具", "家装", "设计装修"],
        "weak": ["看房", "中介", "房东", "搬家", "家政"],
        "negative": ["电影", "游戏", "成人", "博彩"],
    },
    "📢 营销广告": {
        "strong": ["广告", "推广", "投放", "营销", "seo", "私域", "流量", "渠道", "广告位"],
        "normal": ["代理", "联盟", "cps", "cpa", "sem", "信息流", "起号", "涨粉", "引流", "裂变", "社媒", "kol", "达人", "品牌", "获客"],
        "weak": ["商务合作", "互推", "置换", "资源对接", "合作"],
        "negative": ["电影", "音乐", "课程", "成人", "博彩"],
    },
    "🤖 机器人服务": {
        "strong": ["机器人", "bot", "telegram bot", "自动回复", "搜索机器人", "下载机器人", "翻译机器人", "客服机器人"],
        "normal": ["查询机器人", "投稿机器人", "群管机器人", "提醒机器人", "订阅机器人", "推送机器人", "bot服务", "bot开发"],
        "weak": ["助手", "自动化", "服务号", "接口"],
        "negative": ["电影", "音乐", "动漫", "博彩", "成人"],
    },
    "🧭 综合导航": {
        "strong": ["导航", "索引", "目录", "大全", "收录", "频道大全", "群组大全", "telegram 中文", "电报中文"],
        "normal": ["搜群", "搜索", "新手", "指南", "合集", "列表", "精选", "推荐", "入口", "资源导航"],
        "weak": ["资源", "分享", "频道", "群组"],
        "negative": [],
    },
}

CATEGORY_PRIORITY_BOOST = {
    "🎲 博彩资源": 10,
    "🔞 成人资源": 10,
    "🩶 灰产资源": 8,
    "🌍 地区本地": 6,
    "🤖 机器人服务": 7,
}

RULE_CONTEXT_RE = re.compile(
    r"(群规|规则|禁止|严禁|不得|不准|请勿|请不要|不要|封禁|删除\+?警告|警告|违者|只允许|不允许|包含并不仅限)"
    r"[^。！？\n\r]{0,500}?"
    r"(博彩|赌博|赌毒|黄赌毒|宗教|政治|键政|黑产|灰产|违法色情|色情|成人|nsfw|r18|18\+|机场|aff|隐私|广告|撕逼|谩骂|人身攻击|刷屏|谣言|盗版)"
    r"[^。！？\n\r]{0,500}",
    re.IGNORECASE,
)
RULE_MARKER_RE = re.compile(r"(群规|规则|禁止|严禁|不得|不准|请勿|请不要|不要|封禁|删除\+?警告|警告|违者|只允许|不允许|包含并不仅限)", re.IGNORECASE)
RULE_TARGET_RE = re.compile(r"(博彩|赌博|赌毒|黄赌毒|宗教|政治|键政|黑产|灰产|违法色情|色情|成人|nsfw|r18|18\+|机场|aff|隐私|广告|撕逼|谩骂|人身攻击|刷屏|谣言|盗版)", re.IGNORECASE)

SPAM_PATTERNS = [
    r"点击链接", r"加入群组", r"关注我们", r"欢迎来到", r"本群规", r"进群请", r"商务合作", r"广告投放",
    r"联系群主", r"联系管理", r"投稿请联系", r"交流群", r"聊天群", r"备用频道", r"官方频道", r"最新地址",
]

ASCII_RE = re.compile(r"^[a-z0-9][a-z0-9_.+-]*$", re.IGNORECASE)


def remove_emoji(text: str) -> str:
    return emoji.replace_emoji(text or "", replace="")


def strip_rule_contexts(text: str) -> str:
    value = text or ""
    value = RULE_CONTEXT_RE.sub(" ", value)
    parts = re.split(r"([。！？；;\n\r|｜*•]+)", value)
    kept: list[str] = []
    for part in parts:
        if RULE_MARKER_RE.search(part) and RULE_TARGET_RE.search(part):
            kept.append(" ")
        else:
            kept.append(part)
    return "".join(kept)


def normalize_text_for_match(text: str) -> str:
    value = strip_rule_contexts(remove_emoji(text or "")).lower()
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

    if score > 0:
        score += CATEGORY_PRIORITY_BOOST.get(category, 0)

    if entry_type == "bot" and category == "🤖 机器人服务":
        score += 22
    elif entry_type == "bot" and category == "🧰 软件工具":
        score += 4

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

    if best_score < 10:
        return "🧭 综合导航"
    if best_score < 22 and best_score - second_score <= 3:
        return "🧭 综合导航"
    return best_category


def main() -> None:
    print("🧹 开始执行文本清洗与 24 大类重整...")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM entries WHERE valid=1 AND private=0").fetchall()
    print(f"处理可分类记录 {len(rows)} 条...")

    changed = 0
    cat_counts: dict[str, int] = {}

    for row in rows:
        entry = dict(row)
        title = entry.get("title") or ""
        desc = entry.get("description") or ""
        username = entry.get("username") or ""

        c_title = clean_title(title) or title
        c_desc = clean_text(desc, title) or "暂无详细简介。"
        category = normalize_category(determine_category(title, desc, entry.get("type"), username)) or "🧭 综合导航"
        conn.execute(
            """
            UPDATE entries
            SET clean_title=?, clean_desc=?, category=?, keep=1, filter_reason='', updated_at=datetime('now')
            WHERE id=?
            """,
            (c_title, c_desc, category, entry["id"]),
        )
        changed += 1
        cat_counts[category] = cat_counts.get(category, 0) + 1

    conn.commit()
    conn.close()

    print(f"✅ 处理完成，共重新分类和清洗 {changed} 条记录。")
    print("\n📊 大类统计：")
    for cat, count in sorted(cat_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  {cat}: {count} 条")


if __name__ == "__main__":
    main()
