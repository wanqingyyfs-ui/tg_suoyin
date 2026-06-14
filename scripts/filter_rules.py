"""Compatibility helpers for TG 索引.

Filtering has been moved out of tg_suoyin. The future tg_shaixuan project is
responsible for deciding whether a collected Telegram resource is acceptable.
This module only keeps old imports working and never rejects an entry.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


MIN_CHANNEL_SUBSCRIBERS = 0
MIN_GROUP_MEMBERS = 0
INACTIVE_DAYS_THRESHOLD = 0
TRADITIONAL_RATIO_THRESHOLD = 0


def contains_chinese(text: str) -> bool:
    return bool((text or "").strip())


def is_traditional_chinese(text: str) -> bool:
    return False


def is_harmful(text: str) -> bool:
    return False


def inactive_days(last_active: str | None) -> int:
    if not last_active:
        return 0
    try:
        dt_str = last_active.replace("+00:00", "").replace("Z", "")
        last_dt = datetime.fromisoformat(dt_str)
        return max((datetime.now() - last_dt).days, 0)
    except (ValueError, TypeError):
        return 0


def evaluate_entry(entry: Mapping[str, Any]) -> tuple[int, str]:
    """Return (1, "") for compatibility.

    tg_suoyin does not filter content. It only stores, classifies, searches and
    exports resources that are already accepted by the upstream data flow.
    """
    return 1, ""
