#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ROOT_DIR / "scripts"
WEB_DIR = ROOT_DIR / "web"


def run_command(command: list[str], cwd: Path = ROOT_DIR, allow_fail: bool = False) -> int:
    print("\n$ " + " ".join(command))
    completed = subprocess.run(command, cwd=str(cwd), check=False)
    if completed.returncode != 0 and not allow_fail:
        raise SystemExit(completed.returncode)
    return completed.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="rectg 自动化维护入口")
    parser.add_argument("--crawl-new", action="store_true", help="抓取新链接")
    parser.add_argument("--crawl-limit", type=int, default=None, help="限制抓取数量，测试用")
    parser.add_argument("--categorize", action="store_true", help="执行自动分类")
    parser.add_argument("--refilter", action="store_true", help="执行重新过滤")
    parser.add_argument("--export", action="store_true", help="导出 data.json/sitemap/robots")
    parser.add_argument("--build", action="store_true", help="执行前端构建")
    parser.add_argument("--all", action="store_true", help="crawl new + categorize + export + build")
    args = parser.parse_args()

    do_crawl = args.all or args.crawl_new
    do_categorize = args.all or args.categorize
    do_export = args.all or args.export
    do_build = args.all or args.build

    if not any((do_crawl, do_categorize, args.refilter, do_export, do_build)):
        do_export = True

    if do_crawl:
        command = [sys.executable, str(SCRIPTS_DIR / "crawl.py"), "--new", "--no-active"]
        if args.crawl_limit:
            command.extend(["--limit", str(args.crawl_limit)])
        run_command(command)

    if do_categorize:
        run_command([sys.executable, str(SCRIPTS_DIR / "categorize.py")])

    if args.refilter:
        run_command([sys.executable, str(SCRIPTS_DIR / "refilter.py")])

    if do_export:
        run_command([sys.executable, str(SCRIPTS_DIR / "export_frontend_data.py")])

    if do_build:
        run_command(["npm", "run", "build"], cwd=WEB_DIR)

    print("\n✅ maintenance 完成")


if __name__ == "__main__":
    main()
