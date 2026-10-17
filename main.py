#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Format Changes 启动入口。

用法：
    python main.py                   打开图形界面
    python main.py --cli 文件 -t pdf 命令行模式（-h 查看帮助）
"""
import multiprocessing
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from app.cli import main as cli_main

        return cli_main()
    from app.gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
