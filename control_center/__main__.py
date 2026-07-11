from __future__ import annotations

import argparse
import os
import runpy
import sys
import traceback


def _run_root_bot_service() -> int:
    """Run the canonical root bot.py without allowing scripts/bot.py to shadow it."""
    from control_center.runtime import ROOT_DIR, apply_env, ensure_runtime_dirs

    ensure_runtime_dirs()
    apply_env()
    os.chdir(ROOT_DIR)

    scripts_dir = ROOT_DIR / "scripts"
    # Insert scripts first and the repository root second so ROOT_DIR ends up at
    # sys.path[0]. This keeps shared script modules importable while ensuring
    # that the canonical root bot.py wins over the legacy scripts/bot.py.
    for path in (scripts_dir, ROOT_DIR):
        value = str(path)
        while value in sys.path:
            sys.path.remove(value)
        sys.path.insert(0, value)

    bot_script = ROOT_DIR / "bot.py"
    if not bot_script.is_file():
        raise FileNotFoundError(f"缺少统一 Bot 入口：{bot_script}")

    old_argv = sys.argv[:]
    try:
        sys.argv = [str(bot_script), "poll"]
        try:
            runpy.run_path(str(bot_script), run_name="__main__")
        except SystemExit as exc:
            if exc.code is None:
                return 0
            if isinstance(exc.code, int):
                return exc.code
            raise RuntimeError(str(exc.code)) from exc
    finally:
        sys.argv = old_argv
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TG 索引控制中心")
    parser.add_argument("--service", choices=("frontend", "admin", "bot"))
    parser.add_argument("--utility", choices=("export", "db-backup", "frontend-build"))
    args = parser.parse_args()
    if args.service:
        from control_center.runtime import configure_child_stdio, run_service

        configure_child_stdio(args.service)
        try:
            if args.service == "bot":
                return _run_root_bot_service()
            return run_service(args.service)
        except BaseException:
            traceback.print_exc()
            return 1
    if args.utility:
        from control_center.runtime import configure_child_stdio, run_utility

        configure_child_stdio("control")
        try:
            return run_utility(args.utility)
        except BaseException:
            traceback.print_exc()
            return 1
    from control_center.app import run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
