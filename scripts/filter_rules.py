"""Shared filtering rules for TG 索引 crawler and maintenance scripts."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Mapping, Any

import opencc


MIN_CHANNEL_SUBSCRIBERS = 1000
MIN_GROUP_MEMBERS = 200
INACTIVE_DAYS_THRESHOLD = 90
TRADITIONAL_RATIO_THRESHOLD = 0.10

CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")
T2S_CONVERTER = opencc.OpenCC("t2s")

# tg_shaixuan 负责前置筛选；tg_suoyin 只保留最硬的安全底线。
# 不再因为成人、博彩、灰产等通用行业词直接过滤，避免影响分类展示。
HARMFUL_KEYWORDS = [
    "儿童色情", "未成年色情", "幼女", "萝莉资源", "迷奸", "迷药", "催情药",
    "强奸", "偷拍", "偷拍视频", "偷拍视频群", "非自愿", "裸照勒索",
    "洗钱", "跑分", "资金盘", "杀猪盘", "诈骗", "盗刷", "黑卡", "银行卡买卖",
    "证件伪造", "假证", "代开发票", "毒品", "冰毒", "海洛因", "大麻交易",
    "枪支交易", "买枪", "卖枪", "军火交易", "爆炸物", "炸药",
    "社工库", "开盒", "人肉搜索", "查档", "开房记录", "户籍查询",
    "钓鱼网站", "木马", "免杀", "ddos", "撞库", "呼死你", "轰炸机",
]

INJECTION_RE = re.compile(
    r"(<\s*script\b|<\s*img\b|onerror\s*=|javascript\s*:)",
    re.IGNORECASE,
)

PROHIBITED_CONTEXT_RE = re.compile(
    r"(禁止|严禁|不准|不允许|拒绝|谢绝|请勿|不得|不发|不开|请不要|不要|莫开|限正版)"
    r"[^。！？；\n]{0,120}?"
    r"(黑产|灰产|暗网|广告|博彩|赌博|色情|低俗|黄赌毒|政治|违法犯罪|"
    r"盗版|破解|黑卡|免流|钓鱼|开盒|社工|nsfw|18\+|r18|开车)"
    r"[^。！？；\n]{0,160}",
    re.IGNORECASE,
)

VIOLATION_CONTEXT_RE = re.compile(
    r"(群规|如有违反|违者|封禁|立ban|踢出)"
    r"[^。！？；\n]{0,160}?"
    r"(黑产|灰产|暗网|广告|博彩|赌博|色情|低俗|黄赌毒|政治|违法犯罪|"
    r"盗版|破解|黑卡|免流|钓鱼|开盒|社工|nsfw|18\+|r18|开车)"
    r"[^。！？；\n]{0,160}",
    re.IGNORECASE,
)


def contains_chinese(text: str) -> bool:
    return bool(CJK_RE.search(text)) if text else False


def is_traditional_chinese(text: str) -> bool:
    if not text:
        return False

    cjk_chars = CJK_RE.findall(text)
    if len(cjk_chars) < 5:
        return False

    simplified = T2S_CONVERTER.convert(text)
    diff_count = sum(1 for before, after in zip(text, simplified) if before != after)
    return diff_count / max(len(text), 1) >= TRADITIONAL_RATIO_THRESHOLD


def is_harmful(text: str) -> bool:
    if not text:
        return False

    if INJECTION_RE.search(text):
        return True

    text_to_check = PROHIBITED_CONTEXT_RE.sub("", text.lower())
    text_to_check = VIOLATION_CONTEXT_RE.sub("", text_to_check)
    return any(keyword in text_to_check for keyword in HARMFUL_KEYWORDS)


def inactive_days(last_active: str | None) -> int:
    if not last_active:
        return 0

    try:
        dt_str = last_active.replace("+00:00", "").replace("Z", "")
        last_dt = datetime.fromisoformat(dt_str)
        return (datetime.now() - last_dt).days
    except (ValueError, TypeError):
        return 0


def evaluate_entry(entry: Mapping[str, Any]) -> tuple[int, str]:
    """Return (keep, reason) for a crawled Telegram entry."""
    if not entry.get("valid"):
        return 0, "链接无效"
    if entry.get("private"):
        return 0, "私密频道/群组"

    entry_type = entry.get("type")
    if not entry_type:
        return 0, "无法识别类型"

    text = f"{entry.get('title') or ''} {entry.get('description') or ''}"
    if not contains_chinese(text):
        return 0, "非中文内容"
    if is_traditional_chinese(text):
        return 0, "繁体中文内容"
    if is_harmful(text):
        return 0, "有害内容"

    count = entry.get("count") or 0
    if entry_type == "channel":
        if count < MIN_CHANNEL_SUBSCRIBERS:
            return 0, f"订阅数不足 ({count} < {MIN_CHANNEL_SUBSCRIBERS})"

        days = inactive_days(entry.get("last_active"))
        if days > INACTIVE_DAYS_THRESHOLD:
            return 0, f"频道不活跃 ({days}天未更新)"
    elif entry_type == "group":
        if count < MIN_GROUP_MEMBERS:
            return 0, f"成员数不足 ({count} < {MIN_GROUP_MEMBERS})"
    elif entry_type == "bot":
        if count == 0:
            return 0, "无月活用户数据"

    return 1, ""
