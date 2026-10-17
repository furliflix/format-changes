# -*- coding: utf-8 -*-
"""GUI 冒烟测试：离屏启动界面、加载示例文件并截图。

用法（没有显示器也能跑）：
    python tests/smoke_gui.py
生成 docs/screenshot.png（README 里用的界面截图）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from app.gui import MainWindow

    app = QApplication(sys.argv)

    # 离屏平台的字体库是空的，手动从字体文件加载中文字体，保证截图文字正常
    from PySide6.QtGui import QFont, QFontDatabase

    font_files = [
        r"C:\Windows\Fonts\msyh.ttc",                     # Windows：微软雅黑（中文）
        r"C:\Windows\Fonts\seguisym.ttf",                 # Windows：Segoe UI Symbol（✓ 等符号）
        "/System/Library/Fonts/PingFang.ttc",             # macOS：苹方
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Apple Symbols.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    families: list[str] = []
    for font_file in font_files:
        if os.path.isfile(font_file):
            fid = QFontDatabase.addApplicationFont(font_file)
            if fid != -1:
                families.extend(QFontDatabase.applicationFontFamilies(fid))
    if families:
        font = QFont()
        font.setFamilies(families)   # 按顺序回退：中文 → 符号
        font.setPointSize(10)
        app.setFont(font)
    win = MainWindow()

    tmp = Path(tempfile.mkdtemp(prefix="fw-gui-"))
    names = ["课堂录音.wav", "讲课视频.mkv", "课件截图.png", "教学大纲.docx", "复习资料.pdf"]
    files = []
    for n in names:
        p = tmp / n
        p.write_bytes(b"demo")
        files.append(str(p))
    win.add_paths(files)

    win.resize(1020, 720)
    win.show()
    for _ in range(10):
        app.processEvents()

    out = ROOT / "docs" / "screenshot.png"
    out.parent.mkdir(exist_ok=True)
    ok = win.grab().save(str(out))
    print("截图已保存：", out, ok)

    win.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
