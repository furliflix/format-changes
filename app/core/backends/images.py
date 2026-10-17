# -*- coding: utf-8 -*-
"""图片转换后端（Pillow）。"""
from __future__ import annotations

from pathlib import Path

from ..cancel import CancelToken
from ..deps import Deps
from ..errors import CancelledError, ConvertError, MissingDependency


class ImagesBackend:
    def __init__(self, deps: Deps):
        self.deps = deps
        self._heif_ok = False
        if deps.pillow_heif:
            try:
                from pillow_heif import register_heif_opener

                register_heif_opener()
                self._heif_ok = True
            except Exception:
                self._heif_ok = False

    def _pil(self):
        if not self.deps.pillow:
            raise MissingDependency("图片转换需要 Pillow：pip install Pillow")
        from PIL import Image, ImageOps

        return Image, ImageOps

    def convert(
        self,
        src: Path,
        target: str,
        tmp_out: Path,
        q,
        progress,
        cancel: CancelToken,
    ) -> None:
        Image, ImageOps = self._pil()
        if cancel.cancelled():
            raise CancelledError()
        progress(0.1, "读取图片")
        try:
            img = Image.open(str(src))
        except Exception as e:
            raise ConvertError(f"无法打开图片：{e}") from e
        try:
            try:
                img = ImageOps.exif_transpose(img) or img
            except Exception:
                pass
            if getattr(img, "is_animated", False) and target != "gif":
                img.seek(0)
            progress(0.4, "转换中")
            self._save(img, target, tmp_out, q)
        finally:
            try:
                img.close()
            except Exception:
                pass
        if cancel.cancelled():
            raise CancelledError()
        progress(1.0, "完成")

    # ------------------------------------------------------------ 保存

    def _save(self, img, target: str, out: Path, q) -> None:
        quality = getattr(q, "img_quality", 92)
        if target in ("jpg", "jpeg"):
            img = self._flatten(img)
            img.save(str(out), format="JPEG", quality=quality, optimize=True, progressive=True)
        elif target == "png":
            if img.mode == "P":
                img = img.convert("RGBA")
            img.save(str(out), format="PNG", optimize=True)
        elif target == "webp":
            if img.mode == "P":
                img = img.convert("RGBA")
            img.save(str(out), format="WEBP", quality=quality, method=4)
        elif target == "bmp":
            img.convert("RGB").save(str(out), format="BMP")
        elif target == "tiff":
            img.convert("RGB").save(str(out), format="TIFF", compression="tiff_deflate")
        elif target == "ico":
            img.convert("RGBA").save(
                str(out), format="ICO",
                sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
            )
        elif target == "gif":
            self._save_gif(img, out)
        elif target == "pdf":
            img = self._flatten(img)
            img.save(str(out), format="PDF", resolution=150.0)
        elif target in ("heic", "heif"):
            if not self._heif_ok:
                raise MissingDependency("HEIC 导出需要 pillow-heif：pip install pillow-heif")
            img.convert("RGB").save(str(out), format="HEIF", quality=quality)
        else:
            raise ConvertError(f"不支持的图片目标格式：{target}")

    def _save_gif(self, img, out: Path) -> None:
        if getattr(img, "is_animated", False):
            frames = []
            n = min(getattr(img, "n_frames", 1), 300)
            for i in range(n):
                img.seek(i)
                frames.append(img.convert("RGBA"))
            frames[0].save(
                str(out), format="GIF", save_all=True, append_images=frames[1:],
                duration=img.info.get("duration", 100), loop=0, disposal=2,
            )
        else:
            img.convert("RGB").save(str(out), format="GIF")

    @staticmethod
    def _flatten(img):
        """把带透明通道的图片合到白底，用于 JPEG / PDF。"""
        from PIL import Image

        if img.mode == "P":
            img = img.convert("RGBA")
        if img.mode in ("LA", "PA"):
            img = img.convert("RGBA")
        if img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img.convert("RGB"), mask=img.getchannel("A"))
            return bg
        if img.mode != "RGB":
            return img.convert("RGB")
        return img
