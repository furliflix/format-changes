# -*- coding: utf-8 -*-
"""运行环境探测：FFmpeg / LibreOffice / 可选 Python 库。"""
from __future__ import annotations

import glob
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .errors import MissingDependency

# Windows 下隐藏子进程控制台窗口
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def popen_flags() -> dict:
    if _CREATE_NO_WINDOW:
        return {"creationflags": _CREATE_NO_WINDOW}
    return {}


def run_capture(cmd, timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        **popen_flags(),
    )


def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# ---------------------------------------------------------------- FFmpeg

_ENCODER_RE = re.compile(r"^\s*[A-Z.]{6}\s+(\S+)", re.MULTILINE)

_MACOS_FFMPEG_CANDIDATES = [
    "/opt/homebrew/bin/ffmpeg",   # Apple 芯片 Homebrew
    "/usr/local/bin/ffmpeg",      # Intel Homebrew
    "/usr/bin/ffmpeg",
]


def find_ffmpeg() -> str | None:
    """按优先级找 ffmpeg 可执行文件。"""
    # 1) 打包进 App 的自带版本
    base = getattr(sys, "_MEIPASS", None)
    if base:
        for p in glob.glob(os.path.join(base, "bin", "ffmpeg*")):
            if os.path.isfile(p):
                try:
                    os.chmod(p, 0o755)
                except OSError:
                    pass
                return p
    # 2) 环境变量指定
    env = os.environ.get("FORMATWIZARD_FFMPEG")
    if env and os.path.isfile(env):
        return env
    # 3) 系统 PATH + macOS Homebrew 常见位置
    p = shutil.which("ffmpeg")
    if p:
        return p
    for c in _MACOS_FFMPEG_CANDIDATES:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    # 4) 源码运行时用 imageio-ffmpeg 自带的静态版本（已在 requirements 里）
    if not getattr(sys, "frozen", False):
        try:
            import imageio_ffmpeg  # type: ignore

            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return None


@dataclass
class FFmpegInfo:
    path: str | None = None
    version: str = ""
    encoders: set = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return bool(self.path and self.version)


def detect_ffmpeg() -> FFmpegInfo:
    info = FFmpegInfo()
    path = find_ffmpeg()
    if not path:
        return info
    info.path = path
    try:
        out = run_capture([path, "-hide_banner", "-version"], timeout=20).stdout or ""
        first = out.splitlines()[0] if out else ""
        m = re.search(r"ffmpeg version ([^\s]+)", first)
        info.version = m.group(1) if m else first.strip()
    except Exception:
        return FFmpegInfo(path=path)
    try:
        out = run_capture([path, "-hide_banner", "-encoders"], timeout=30).stdout or ""
        info.encoders = set(_ENCODER_RE.findall(out))
    except Exception:
        pass
    return info


# ------------------------------------------------------------ LibreOffice

_SOFFICE_CANDIDATES = [
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    os.path.expanduser("~/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    "/opt/homebrew/bin/soffice",
    "/usr/local/bin/soffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    r"C:\ProgramData\chocolatey\bin\soffice.exe",
]


def _soffice_from_registry_win() -> str | None:
    """从 Windows 注册表找 LibreOffice（支持装在任意盘符，如 D:\\App\\LibreOffice）。"""
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore
    except ImportError:  # pragma: no cover
        return None
    subkeys = [
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
        r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
    ]
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey in subkeys:
            try:
                key = winreg.OpenKey(hive, subkey)
            except OSError:
                continue
            with key:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(key, i)
                    except OSError:
                        break
                    i += 1
                    try:
                        sub = winreg.OpenKey(key, name)
                    except OSError:
                        continue
                    with sub:
                        try:
                            display = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                        except OSError:
                            continue
                        if "libreoffice" not in display.lower():
                            continue
                        for value in ("InstallLocation", "DisplayIcon"):
                            try:
                                raw = str(winreg.QueryValueEx(sub, value)[0])
                            except OSError:
                                continue
                            raw = raw.split(",")[0].strip().strip('"')
                            if not raw:
                                continue
                            if value == "InstallLocation":
                                cand = Path(raw) / "program" / "soffice.exe"
                            else:
                                cand = Path(raw)
                            if cand.is_file():
                                return str(cand)
    return None


def find_soffice() -> str | None:
    env = os.environ.get("FORMATWIZARD_SOFFICE")
    if env and os.path.isfile(env):
        return env
    p = shutil.which("soffice") or shutil.which("libreoffice")
    if p:
        return p
    for c in _SOFFICE_CANDIDATES:
        if os.path.isfile(c):
            return c
    # scoop 安装
    for c in glob.glob(os.path.expanduser(
            "~/scoop/apps/libreoffice/current/*/program/soffice.exe")):
        if os.path.isfile(c):
            return c
    return _soffice_from_registry_win()


# ------------------------------------------------------------------ Deps

@dataclass
class Deps:
    ffmpeg: FFmpegInfo = field(default_factory=FFmpegInfo)
    soffice: str | None = None
    pillow: bool = False
    pymupdf: bool = False
    python_docx: bool = False
    reportlab: bool = False
    pillow_heif: bool = False

    # ---- 断言式检查（缺了就抛带安装提示的错误）----
    def need_ffmpeg(self) -> None:
        if not self.ffmpeg.ok:
            raise MissingDependency(
                "缺少 FFmpeg 转换引擎。\n"
                "正常安装包会自带；如果是源码运行，请执行 pip install imageio-ffmpeg，\n"
                "或在 macOS 上执行：brew install ffmpeg"
            )

    def need_soffice(self) -> None:
        if not self.soffice:
            raise MissingDependency(
                "Word / Excel / PPT 文档转换需要 LibreOffice。\n"
                "macOS 安装：brew install --cask libreoffice\n"
                "或到 https://zh-cn.libreoffice.org/download/ 下载安装。"
            )

    @classmethod
    def detect(cls) -> "Deps":
        return cls(
            ffmpeg=detect_ffmpeg(),
            soffice=find_soffice(),
            pillow=_has_module("PIL"),
            pymupdf=_has_module("fitz"),
            python_docx=_has_module("docx"),
            reportlab=_has_module("reportlab"),
            pillow_heif=_has_module("pillow_heif"),
        )

    # ---- 给界面 / 命令行用的摘要 ----
    def summary_lines(self) -> list[tuple[str, bool, str]]:
        """返回 [(名称, 是否可用, 说明)]。"""
        return [
            ("FFmpeg 音视频引擎", self.ffmpeg.ok,
             self.ffmpeg.version if self.ffmpeg.version else "未找到"),
            ("LibreOffice 文档引擎", bool(self.soffice),
             self.soffice or "未安装（Word→PDF/TXT 可用基础模式）"),
            ("Pillow 图片引擎", self.pillow, "已安装" if self.pillow else "未安装"),
            ("PyMuPDF PDF 引擎", self.pymupdf, "已安装" if self.pymupdf else "未安装"),
            ("HEIC 照片支持（可选）", self.pillow_heif,
             "已安装" if self.pillow_heif else "未安装：pip install pillow-heif"),
        ]

    def status_text(self) -> str:
        return (f"FFmpeg {'✓' if self.ffmpeg.ok else '✗'} · "
                f"LibreOffice {'✓' if self.soffice else '✗'} · "
                f"图片 {'✓' if self.pillow else '✗'} · "
                f"PDF {'✓' if self.pymupdf else '✗'}")

    def key_encoders(self) -> list[tuple[str, bool]]:
        if not self.ffmpeg.ok:
            return []
        want = ["libx264", "libmp3lame", "libvorbis", "libopus", "aac", "libvpx-vp9", "flac"]
        return [(w, w in self.ffmpeg.encoders) for w in want]
