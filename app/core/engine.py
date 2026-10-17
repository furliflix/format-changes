# -*- coding: utf-8 -*-
"""转换引擎：负责路由到具体后端、生成输出路径、汇报进度。"""
from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .backends import simple
from .backends.ffmpeg import FfmpegBackend
from .backends.images import ImagesBackend
from .backends.office import OfficeBackend
from .backends.pdf import PdfBackend
from .cancel import CancelToken
from .deps import Deps
from .errors import CancelledError, ConvertError, MissingDependency
from .formats import (AUDIO, DOC, GIF, IMAGE, PDF, PRESETS_BY_KEY, SHEET,
                      SLIDES, SOURCE_GROUPS, TARGET_SPECS, VIDEO,
                      target_label, targets_by_group)

ProgressFn = Callable[[Optional[float], str], None]


def _noop(frac, text):  # pragma: no cover
    pass


@dataclass
class TargetOption:
    ext: str
    label: str
    available: bool
    note: str = ""


def ext_of(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


class Converter:
    def __init__(self, deps: Optional[Deps] = None):
        self.deps = deps or Deps.detect()
        self.ffmpeg = FfmpegBackend(self.deps)
        self.images = ImagesBackend(self.deps)
        self.office = OfficeBackend(self.deps)
        self.pdf = PdfBackend(self.deps)

    # ---------------------------------------------------------- 查询

    @staticmethod
    def source_group(src: Path) -> Optional[str]:
        return SOURCE_GROUPS.get(ext_of(src))

    def targets_for(self, src: Path) -> list[TargetOption]:
        ext = ext_of(src)
        group = SOURCE_GROUPS.get(ext)
        if not group:
            return []
        out: list[TargetOption] = []
        for t in targets_by_group(group):
            if t == ext:
                continue
            available, note = self._availability(group, ext, t)
            out.append(TargetOption(ext=t, label=target_label(t), available=available, note=note))
        return out

    def _availability(self, group: str, src_ext: str, target: str) -> tuple[bool, str]:
        tg = TARGET_SPECS[target].group
        # 图片类（含 图片/GIF → PDF）
        if group == IMAGE or (group == GIF and tg in (IMAGE, PDF)):
            if not self.deps.pillow:
                return False, "需要 Pillow"
            if src_ext in ("heic", "heif") and not self.deps.pillow_heif:
                return False, "需要 pillow-heif 才能读 HEIC"
            return True, ""
        # 视频 / 音频 / GIF 目标
        if tg == GIF or tg in (AUDIO, VIDEO):
            if not self.deps.ffmpeg.ok:
                return False, "需要 FFmpeg"
            return True, ""
        # Word 类文档
        if group == DOC:
            if self.deps.soffice:
                return True, ""
            if tg == PDF and src_ext == "docx":
                return True, "基础模式（装 LibreOffice 效果更好）"
            if target == "txt":
                if src_ext == "docx":
                    return True, "基础模式（装 LibreOffice 效果更好）"
                if src_ext in ("html", "htm"):
                    return True, "基础模式"
            return False, "需要安装 LibreOffice"
        # 表格 / 演示文稿
        if group in (SHEET, SLIDES):
            if self.deps.soffice:
                return True, ""
            return False, "需要安装 LibreOffice"
        # PDF 来源
        if group == PDF:
            if not self.deps.pymupdf:
                return False, "需要 PyMuPDF"
            if target == "docx" and not self.deps.python_docx:
                return False, "需要 python-docx"
            return True, ""
        return False, "不支持"

    # ---------------------------------------------------------- 转换

    def convert(
        self,
        src: Path,
        target_ext: str,
        dst_dir: Optional[Path] = None,
        quality: str = "balanced",
        overwrite: bool = False,
        progress: Optional[ProgressFn] = None,
        cancel: Optional[CancelToken] = None,
    ) -> Path:
        src = Path(src)
        progress = progress or _noop
        cancel = cancel or CancelToken()

        if not src.is_file():
            raise ConvertError(f"找不到文件：{src}")
        group = self.source_group(src)
        if not group:
            raise ConvertError(f"不支持的源格式：{src.suffix}")
        target_ext = target_ext.lower().lstrip(".")
        if target_ext not in TARGET_SPECS:
            raise ConvertError(f"不支持的目标格式：{target_ext}")
        if target_ext == ext_of(src):
            raise ConvertError("源格式和目标格式相同，不需要转换。")
        q = PRESETS_BY_KEY.get(quality or "balanced") or PRESETS_BY_KEY["balanced"]

        dst_dir = Path(dst_dir) if dst_dir else src.parent
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = self._unique_path(dst_dir / f"{src.stem}.{target_ext}", overwrite)
        if dst.resolve() == src.resolve():
            dst = self._unique_path(dst_dir / f"{src.stem} (转换).{target_ext}", overwrite)

        backend = self._pick_backend(group, ext_of(src), target_ext)
        workdir = Path(tempfile.mkdtemp(prefix=".fw-tmp-", dir=str(dst_dir)))
        tmp_out = workdir / f"out.{target_ext}"
        try:
            progress(0.0, "准备中")
            if backend == "ffmpeg":
                if target_ext == "gif":
                    self.ffmpeg.convert_gif(src, tmp_out, q, progress, cancel)
                else:
                    self.ffmpeg.convert(src, target_ext, tmp_out, q, progress, cancel)
            elif backend == "pillow":
                self.images.convert(src, target_ext, tmp_out, q, progress, cancel)
            elif backend == "office":
                self.office.convert(src, target_ext, tmp_out, q, progress, cancel)
            elif backend == "pdf":
                self.pdf.convert(src, target_ext, tmp_out, q, progress, cancel)
            elif backend == "docx_pdf":
                simple.docx_to_pdf(src, tmp_out, progress)
            elif backend == "docx_txt":
                simple.docx_to_txt(src, tmp_out)
                progress(1.0, "完成")
            elif backend == "html_txt":
                simple.html_to_txt(src, tmp_out)
                progress(1.0, "完成")
            else:  # pragma: no cover
                raise ConvertError("没有可用的转换方式。")

            if cancel.cancelled():
                raise CancelledError()
            if not tmp_out.exists() or tmp_out.stat().st_size == 0:
                raise ConvertError("转换没有生成有效的输出文件。")
            if overwrite and dst.exists():
                try:
                    dst.unlink()
                except OSError:
                    pass
            shutil.move(str(tmp_out), str(dst))
            progress(1.0, "完成")
            return dst
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # ---------------------------------------------------------- 内部

    def _pick_backend(self, group: str, src_ext: str, target_ext: str) -> str:
        tg = TARGET_SPECS[target_ext].group
        if target_ext == "gif":
            return "pillow" if group == IMAGE else "ffmpeg"
        if tg in (AUDIO, VIDEO):
            return "ffmpeg"
        if group == IMAGE or (group == GIF and tg in (IMAGE, PDF)):
            return "pillow"
        if group == GIF:
            return "ffmpeg"
        if group == DOC:
            if self.deps.soffice:
                return "office"
            if target_ext == "pdf" and src_ext == "docx":
                self._need_simple()
                return "docx_pdf"
            if target_ext == "txt":
                if src_ext == "docx":
                    self._need_simple()
                    return "docx_txt"
                if src_ext in ("html", "htm"):
                    return "html_txt"
            self.deps.need_soffice()
        if group in (SHEET, SLIDES):
            self.deps.need_soffice()
        if group == PDF:
            return "pdf"
        raise ConvertError(f"不支持的转换：{src_ext} → {target_ext}")

    def _need_simple(self) -> None:
        if not (self.deps.reportlab and self.deps.python_docx):
            raise MissingDependency(
                "基础模式需要 reportlab 和 python-docx。\n"
                "请执行：pip install reportlab python-docx"
            )

    @staticmethod
    def _unique_path(path: Path, overwrite: bool) -> Path:
        if overwrite or not path.exists():
            return path
        stem, suffix, parent = path.stem, path.suffix, path.parent
        for i in range(1, 10000):
            cand = parent / f"{stem} ({i}){suffix}"
            if not cand.exists():
                return cand
        return path  # pragma: no cover
