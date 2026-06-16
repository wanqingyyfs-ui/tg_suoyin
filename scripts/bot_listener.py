#!/usr/bin/env python3
"""兼容入口。

机器人主程序已经统一到项目根目录 bot.py。以后开发机器人逻辑请改 bot.py。
这个文件只保留旧命令兼容：python scripts/bot_listener.py poll
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from bot import main


if __name__ == "__main__":
    main()
