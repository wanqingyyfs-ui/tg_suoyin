#!/usr/bin/env python3
"""一键重整 TG 索引数据库并重新导出前端数据。"""
from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

from categories import CATEGORY_ORDER, normalize_category

ROOT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = ROOT_DIR / "data" / "rectg.db"
CATEGORIZE_SCRIPT = ROOT_DIR / "scripts" / "categorize.py"
EXPORT_SCRIPT = ROOT_DIR / "scripts" / "export_frontend_data.py"


def run_script(script: Path) -> None:
    print(f"\n▶ 执行：{script.relative_to(ROOT_DIR)}")
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT_DIR),
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout)
    if completed.stderr:
        print(completed.stderr, file=sys.stderr)
    if completed.returncode != 0:
        raise SystemExit(f"❌ 脚本执行失败：{script}")


def normalize_existing_categories() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"❌ 数据库不存在：{DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, category FROM entries WHERE category IS NOT NULL AND TRIM(category) <> ''"
    ).fetchall()

    changed = 0
    for row in rows:
        old_category = row["category"] or ""
        new_category = normalize_category(old_category) or "🧭 综合导航"
        if new_category != old_category:
            conn.execute(
                "UPDATE entries SET category=?, updated_at=datetime('now') WHERE id=?",
                (new_category, row["id"]),
            )
            changed += 1

    # 清理后台分类表里的旧分类，只保留当前大类。
    try:
        conn.execute("DELETE FROM categories")
        now_sql = "datetime('now')"
        for index, category in enumerate(CATEGORY_ORDER):
            conn.execute(
                f"""
                INSERT OR IGNORE INTO categories (name, sort_order, created_at, updated_at)
                VALUES (?, ?, {now_sql}, {now_sql})
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
        WHERE keep=1 AND valid=1 AND private=0
        GROUP BY category
        ORDER BY count DESC
        """
    ).fetchall()
    conn.close()

    print(f"✅ 已归并历史旧分类：{changed} 条")
    print("\n📊 当前可见资源大类统计：")
    for row in stats:
        print(f"  {row['category'] or '未分类'}：{row['count']} 条")


def main() -> None:
    print("🚀 开始重整 TG 索引数据库和前端数据...")
    run_script(CATEGORIZE_SCRIPT)
    normalize_existing_categories()
    run_script(EXPORT_SCRIPT)
    print("\n✅ 重整完成。请检查 web/public/data.json 后提交数据库和前端导出文件。")


if __name__ == "__main__":
    main()
