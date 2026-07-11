from __future__ import annotations

import argparse
import sys
import traceback


def main() -> int:
    parser = argparse.ArgumentParser(description="TG 索引控制中心")
    parser.add_argument("--service", choices=("frontend", "admin", "bot"))
    parser.add_argument("--utility", choices=("export", "db-backup", "frontend-build"))
    args = parser.parse_args()
    if args.service:
        from control_center.runtime import configure_child_stdio, run_service

        configure_child_stdio(args.service)
        try:
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
