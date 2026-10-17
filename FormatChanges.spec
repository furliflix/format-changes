# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

- macOS  生成 dist/FormatChanges.app（显示名：Format Changes）
- Windows 生成 dist/FormatChanges/FormatChanges.exe

打包前先跑：python packaging/make_icon.py
"""
import os
import sys

ROOT = os.path.abspath(SPECPATH)

sys.path.insert(0, ROOT)
from app import APP_SLUG, APP_VERSION  # noqa: E402


def _ffmpeg_binary():
    """找到要打包进 App 的 ffmpeg。

    优先用环境变量 FORMATWIZARD_FFMPEG_SRC 指定的静态版 ffmpeg；
    否则用 imageio-ffmpeg 自带的静态版本（requirements 里已包含）。
    """
    env = os.environ.get("FORMATWIZARD_FFMPEG_SRC")
    if env and os.path.isfile(env):
        return env
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as e:  # pragma: no cover
        print("警告：没有找到可打包的 ffmpeg 二进制：", e)
        return None


binaries = []
_ff = _ffmpeg_binary()
if _ff:
    binaries.append((_ff, "bin"))
    print("将打包 ffmpeg：", _ff)

datas = [
    (os.path.join(ROOT, "assets"), "assets"),
]

hiddenimports = ["fitz", "pymupdf"]
try:
    import pillow_heif  # noqa: F401

    hiddenimports.append("pillow_heif")
except Exception:
    pass

excludes = [
    "tkinter", "unittest", "pydoc", "doctest", "test", "xmlrpc",
    "numpy", "matplotlib", "scipy", "pandas", "IPython", "pytest",
]

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

icon_ico = os.path.join(ROOT, "assets", "AppIcon.ico")
icon_icns = os.path.join(ROOT, "assets", "AppIcon.icns")

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_SLUG,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=icon_ico if sys.platform == "win32" and os.path.isfile(icon_ico) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_SLUG,
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=f"{APP_SLUG}.app",
        icon=icon_icns if os.path.isfile(icon_icns) else None,
        bundle_identifier="com.formatchanges.app",
        info_plist={
            "CFBundleDisplayName": "Format Changes",
            "CFBundleName": APP_SLUG,
            "CFBundleShortVersionString": APP_VERSION,
            "CFBundleVersion": APP_VERSION,
            "CFBundleDevelopmentRegion": "zh_CN",
            "CFBundleAllowMixedLocalizations": True,
            "LSApplicationCategoryType": "public.app-category.utilities",
            "LSMinimumSystemVersion": "10.15",
            "NSHighResolutionCapable": True,
            "NSHumanReadableCopyright": "© 2026",
        },
    )
