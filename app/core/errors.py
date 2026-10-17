# -*- coding: utf-8 -*-
"""异常类型。"""


class ConvertError(Exception):
    """转换失败（消息会直接展示给用户）。"""


class MissingDependency(ConvertError):
    """缺少外部依赖（FFmpeg / LibreOffice 等）。"""


class CancelledError(Exception):
    """用户取消了任务。"""
