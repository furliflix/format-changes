# -*- coding: utf-8 -*-
"""Format Changes

一个跨平台的格式转换小工具：音频 / 视频 / 图片 / 文档。
本文件顶部的常量可以在打包前自由修改。
"""

APP_NAME = "Format Changes"    # 界面上显示的名字
APP_SLUG = "FormatChanges"      # 英文代号（文件名、进程名用，不要带空格）
APP_VERSION = "1.0.0"

# ↓↓↓↓↓↓  打包前把这里改成你自己的名字和想对老师说的话  ↓↓↓↓↓↓
APP_AUTHOR = "你的名字"
APP_DEDICATION = "送给敬爱的计算机老师"
# ↑↑↑↑↑↑  改这两行就行，其它都不用动  ↑↑↑↑↑↑

import os
import sys


def resource_path(*parts: str) -> str:
    """返回随程序打包的资源文件路径（兼容 PyInstaller 打包后运行）。"""
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        # 源码运行时：项目根目录
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def is_frozen() -> bool:
    """是否运行在打包后的独立程序里。"""
    return bool(getattr(sys, "frozen", False))
