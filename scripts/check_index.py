#!/usr/bin/env python3
"""检查 TG 索引数据库分类整理结果。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "rectg.db"

EXPECTED_CATEGORIES = [
    "📰 新闻资讯",
    "💻 科技开发",
    "🧰 软件工具",
    "🎬 影音娱乐",
    "📚 学习阅读",
    "👥 生活社群",
    "💎 加密货币",
    "🧭 综合导航",
]

REMOVED_CATEGORY_KEYWORDS = ["🪙", "🤖", "机器人"]


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 数据库不存在：{DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    visible_rows = conn.execute(
        """
        SELECT category, COUNT(*) AS count
        FROM entries
        WHERE keep=1 AND valid=1 AND private=0
        GROUP BY category
        ORDER BY count DESC
        """
    ).fetchall()

    all_category_rows = conn.execute(
        """
        SELECT category, COUNT(*) AS count
        FROM entries
        WHERE category IS NOT NULL AND TRIM(category) <> ''
        GROUP BY category
        ORDER BY count DESC
        """
    ).fetchall()

    old_rows = [
        row for row in all_category_rows
        if any(keyword in str(row["category"] or "") for keyword in REMOVED_CATEGORY_KEYWORDS)
        or str(row["category"] or "") == "🪙 加密货币"
    ]

    unexpected_rows = [
        row for row in visible_rows
        if (row["category"] or "") not in EXPECTED_CATEGORIES
    ]

    total_visible = sum(int(row["count"] or 0) for row in visible_rows)
    conn.close()

    print("📊 当前前台可见资源分类统计：")
    for row in visible_rows:
        print(f"  {row['category'] or '未分类'}：{row['count']} 条")
    print(f"\n✅ 前台可见资源总数：{total_visible} 条")

    print("\n🔎 旧分类检查：")
    if old_rows:
        print("❌ 仍然发现旧分类：")
        for row in old_rows:
            print(f"  {row['category']}：{row['count']} 条")
    else:
        print("✅ 未发现 🪙 加密货币 / 🤖 机器人 旧分类。")

    print("\n🔎 非预期大类检查：")
    if unexpected_rows:
        print("❌ 仍然发现非预期分类：")
        for row in unexpected_rows:
            print(f"  {row['category']}：{row['count']} 条")
    else:
        print("✅ 前台可见资源只使用当前 8 个大类。")


if __name__ == "__main__":
    main()
