#!/usr/bin/env python3
"""一键重整 TG 索引数据库分类并重新导出前端数据。"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from categories import CATEGORY_ORDER, FORCED_CATEGORY_REPLACEMENTS, normalize_entry_category

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"
CATEGORIZE_SCRIPT = ROOT_DIR / "scripts" / "categorize.py"
EXPORT_SCRIPT = ROOT_DIR / "scripts" / "export_frontend_data.py"

EXPECTED_CATEGORY_SET = set(CATEGORY_ORDER)


def run_script(script: Path) -> None:
    print(f"\n▶ 执行：{script.relative_to(ROOT_DIR)}", flush=True)
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT_DIR),
        check=False,
    )
    if completed.returncode != 0:
        raise SystemExit(f"❌ 脚本执行失败：{script}")


def normalize_one_category(category: str | None, entry_type: str | None = None) -> str:
    normalized = normalize_entry_category(category, entry_type)
    if normalized not in EXPECTED_CATEGORY_SET:
        return "🧭 综合导航"
    return normalized


def normalize_existing_categories() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 数据库不存在：{DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    forced_changed = 0
    for old_category, new_category in FORCED_CATEGORY_REPLACEMENTS.items():
        cur = conn.execute(
            "UPDATE entries SET category=?, keep=1, filter_reason='', updated_at=datetime('now') WHERE category=?",
            (new_category, old_category),
        )
        forced_changed += cur.rowcount if cur.rowcount is not None else 0

    rows = conn.execute(
        "SELECT id, category, type FROM entries WHERE valid=1 AND private=0 AND (category IS NULL OR TRIM(category) = '' OR category NOT IN ({}))".format(
            ",".join("?" for _ in CATEGORY_ORDER)
        ),
        CATEGORY_ORDER,
    ).fetchall()

    normalized_changed = 0
    for row in rows:
        old_category = row["category"] or ""
        new_category = normalize_one_category(old_category, row["type"])
        if new_category != old_category:
            conn.execute(
                "UPDATE entries SET category=?, keep=1, filter_reason='', updated_at=datetime('now') WHERE id=?",
                (new_category, row["id"]),
            )
            normalized_changed += 1

    allowed_placeholders = ",".join("?" for _ in CATEGORY_ORDER)
    cur = conn.execute(
        f"UPDATE entries SET category='🧭 综合导航', keep=1, filter_reason='', updated_at=datetime('now') WHERE valid=1 AND private=0 AND (category NOT IN ({allowed_placeholders}) OR category IS NULL OR TRIM(category)='')",
        CATEGORY_ORDER,
    )
    fallback_changed = cur.rowcount if cur.rowcount is not None else 0

    # 旧数据库可能保留 keep=0 / filter_reason，分类重整时统一恢复为可展示状态。
    restored = conn.execute(
        "UPDATE entries SET keep=1, filter_reason='' WHERE valid=1 AND private=0 AND (keep IS NULL OR keep != 1 OR filter_reason IS NOT NULL)",
    ).rowcount

    try:
        conn.execute("DELETE FROM categories")
        for index, category in enumerate(CATEGORY_ORDER):
            conn.execute(
                """
                INSERT OR IGNORE INTO categories (name, sort_order, created_at, updated_at)
                VALUES (?, ?, datetime('now'), datetime('now'))
                """,
                (category, index),
            )
    except sqlite3.OperationalError:
        pass

    conn.commit()

    stats = conn.execute(
        """
        SELECT category, COUNT(*) AS count
        FROM entries
        WHERE valid=1 AND private=0
        GROUP BY category
        ORDER BY count DESC
        """
    ).fetchall()

    stale_categories = tuple(FORCED_CATEGORY_REPLACEMENTS.keys())
    old_rows = []
    if stale_categories:
        placeholders = ",".join("?" for _ in stale_categories)
        old_rows = conn.execute(
            f"""
            SELECT category, COUNT(*) AS count
            FROM entries
            WHERE category IN ({placeholders})
            GROUP BY category
            """,
            stale_categories,
        ).fetchall()
    conn.close()

    print(f"✅ 强制替换旧分类：{forced_changed} 条")
    print(f"✅ 归一化非标准分类：{normalized_changed} 条")
    print(f"✅ 兜底整理非当前大类分类：{fallback_changed} 条")
    print(f"✅ 恢复旧 keep 状态：{restored if restored is not None else 0} 条")
    if old_rows:
        print("❌ 仍发现旧分类，请检查数据库写入权限：")
        for row in old_rows:
            print(f"  {row['category']}：{row['count']} 条")
    else:
        print("✅ 已确认数据库中不存在历史分类残留。")

    print("\n📊 当前公开有效资源大类统计：")
    for row in stats:
        print(f"  {row['category'] or '未分类'}：{row['count']} 条")


def main() -> None:
    print("🚀 开始重整 TG 索引数据库分类和前端数据...")
    run_script(CATEGORIZE_SCRIPT)
    normalize_existing_categories()
    run_script(EXPORT_SCRIPT)
    print("\n✅ 重整完成。请检查 web/public/data.json 后提交数据库和前端导出文件。")


if __name__ == "__main__":
    main()
