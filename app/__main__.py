# -*- coding: utf-8 -*-
"""python -m app 入口：默认打开图形界面，带 --cli 参数时使用命令行模式。"""
import sys


def main() -> int:
    if "--cli" in sys.argv:
        sys.argv.remove("--cli")
        from .cli import main as cli_main

        return cli_main()
    from .gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
