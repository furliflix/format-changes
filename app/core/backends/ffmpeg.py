# -*- coding: utf-8 -*-
"""FFmpeg 后端：音频 / 视频 / GIF 转换。"""
from __future__ import annotations

import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..cancel import CancelToken
from ..deps import Deps, popen_flags
from ..errors import CancelledError, ConvertError
from ..formats import Quality

AUDIO_TARGETS = {"mp3", "ogg", "wav", "flac", "m4a", "aac", "opus", "wma"}
VIDEO_TARGETS = {"mp4", "mkv", "mov", "webm", "avi", "wmv", "flv"}

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):([\d.]+)")
_STREAM_RE = re.compile(r"Stream #\d+:\d+.*?: (Video|Audio): (.+)")


@dataclass
class MediaInfo:
    duration: float | None = None
    has_video: bool = False
    has_audio: bool = False
    width: int = 0
    height: int = 0


def _friendly_ffmpeg_error(tail: list[str], rc: int) -> str:
    text = "\n".join(tail[-12:]).strip() or f"ffmpeg 退出码 {rc}"
    if "does not contain any stream" in text:
        return "文件里没有可转换的音/视频轨道。"
    if "Invalid data found" in text:
        return "无法识别这个文件，可能已损坏或格式不受支持。"
    if "No such file" in text:
        return "找不到源文件。"
    if "Permission denied" in text:
        return "没有权限读写文件，请换一个输出文件夹试试。"
    if "not divisible by 2" in text:
        return "视频宽高出现了奇数像素，请更换输入文件或换一种目标格式。"
    return "转换失败（FFmpeg）：\n" + text


class FfmpegBackend:
    def __init__(self, deps: Deps):
        self.deps = deps
        self._probe_cache: dict[tuple[str, float], MediaInfo] = {}

    @property
    def exe(self) -> str:
        self.deps.need_ffmpeg()
        assert self.deps.ffmpeg.path
        return self.deps.ffmpeg.path

    # ------------------------------------------------------------ 探测

    def _pick(self, chain: list[str]) -> str | None:
        """从编码器候选链里挑第一个可用的。"""
        enc = self.deps.ffmpeg.encoders
        if not enc:  # 探测失败时乐观使用第一候选
            return chain[0] if chain else None
        for e in chain:
            if e in enc:
                return e
        return None

    def probe(self, src: Path) -> MediaInfo:
        try:
            key = (str(src), src.stat().st_mtime)
        except OSError:
            key = (str(src), 0.0)
        if key in self._probe_cache:
            return self._probe_cache[key]
        info = MediaInfo()
        try:
            proc = subprocess.run(
                [self.exe, "-hide_banner", "-i", str(src)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                **popen_flags(),
            )
            text = proc.stdout or ""
        except Exception:
            self._probe_cache[key] = info
            return info
        m = _DURATION_RE.search(text)
        if m:
            info.duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        for kind, rest in _STREAM_RE.findall(text):
            if kind == "Audio":
                info.has_audio = True
            elif kind == "Video" and "attached pic" not in rest:
                info.has_video = True
                mw = re.search(r"(\d{2,5})x(\d{2,5})", rest)
                if mw:
                    info.width, info.height = int(mw.group(1)), int(mw.group(2))
        self._probe_cache[key] = info
        return info

    # ------------------------------------------------------------ 编码参数

    def _audio_codec_args(self, target: str, q: Quality) -> list[str]:
        if target == "mp3":
            e = self._pick(["libmp3lame"])
            if not e:
                raise ConvertError("当前的 FFmpeg 不带 MP3 编码器。")
            return ["-c:a", e, "-q:a", str(q.mp3_q)]
        if target == "ogg":
            e = self._pick(["libvorbis", "libopus"])
            if not e:
                raise ConvertError("当前的 FFmpeg 缺少 OGG 编码器（libvorbis/libopus）。")
            if e == "libvorbis":
                return ["-c:a", e, "-q:a", str(q.vorbis_q)]
            return ["-c:a", e, "-b:a", q.a_bitrate]
        if target == "wav":
            return ["-c:a", "pcm_s16le"]
        if target == "flac":
            e = self._pick(["flac"])
            if not e:
                raise ConvertError("当前的 FFmpeg 缺少 FLAC 编码器。")
            return ["-c:a", e, "-compression_level", "5"]
        if target in ("m4a", "aac"):
            return ["-c:a", "aac", "-b:a", q.a_bitrate]
        if target == "opus":
            e = self._pick(["libopus"])
            if not e:
                raise ConvertError("当前的 FFmpeg 缺少 OPUS 编码器（libopus）。")
            return ["-c:a", e, "-b:a", q.a_bitrate]
        if target == "wma":
            return ["-c:a", "wmav2", "-b:a", q.a_bitrate]
        raise ConvertError(f"不支持的目标格式：{target}")

    def _video_codec_args(self, target: str, q: Quality) -> list[str]:
        """视频编码参数 + 是否需要统一为偶数分辨率。"""
        needs_even = False
        if target in ("mp4", "mkv", "mov", "flv"):
            e = self._pick(["libx264", "h264_videotoolbox", "mpeg4"])
            if not e:
                raise ConvertError("当前的 FFmpeg 缺少 H.264 编码器（libx264）。")
            if e == "libx264":
                args = ["-c:v", e, "-preset", q.v_preset, "-crf", str(q.v_crf), "-pix_fmt", "yuv420p"]
                needs_even = True
            elif e == "h264_videotoolbox":
                args = ["-c:v", e, "-b:v", "6M", "-pix_fmt", "yuv420p"]
                needs_even = True
            else:
                args = ["-c:v", "mpeg4", "-q:v", "5"]
                needs_even = True
        elif target == "webm":
            e = self._pick(["libvpx-vp9", "libvpx"])
            if not e:
                raise ConvertError("当前的 FFmpeg 缺少 WebM 编码器（libvpx）。")
            if e == "libvpx-vp9":
                args = ["-c:v", e, "-crf", str(q.vp9_crf), "-b:v", "0", "-row-mt", "1", "-cpu-used", "2"]
            else:
                args = ["-c:v", "libvpx", "-crf", "10", "-b:v", "1M"]
            needs_even = True
        elif target == "avi":
            e = self._pick(["mpeg4", "libx264"])
            if e == "libx264":
                args = ["-c:v", "libx264", "-preset", q.v_preset, "-crf", str(q.v_crf), "-pix_fmt", "yuv420p"]
            else:
                args = ["-c:v", "mpeg4", "-q:v", "5"]
            needs_even = True
        elif target == "wmv":
            args = ["-c:v", "wmv2", "-b:v", "4M", "-pix_fmt", "yuv420p"]
            needs_even = True
        else:
            raise ConvertError(f"不支持的目标格式：{target}")
        if needs_even:
            args += ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
        return args

    def _video_audio_args(self, target: str, q: Quality) -> list[str]:
        if target == "webm":
            e = self._pick(["libopus", "libvorbis"])
            if e == "libvorbis":
                return ["-c:a", e, "-q:a", str(q.vorbis_q)]
            return ["-c:a", "libopus", "-b:a", q.a_bitrate]
        if target == "avi":
            e = self._pick(["libmp3lame"])
            if e:
                return ["-c:a", e, "-q:a", str(q.mp3_q)]
            return ["-c:a", "aac", "-b:a", q.a_bitrate]
        if target == "wmv":
            return ["-c:a", "wmav2", "-b:a", q.a_bitrate]
        return ["-c:a", "aac", "-b:a", q.a_bitrate]

    # ------------------------------------------------------------ 执行

    def _run(
        self,
        cmd: list[str],
        total_time: float | None,
        progress,
        cancel: CancelToken,
        label: str,
        t0: float = 0.0,
        tspan: float = 1.0,
    ) -> None:
        if cancel.cancelled():
            raise CancelledError()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            **popen_flags(),
        )
        cancel.attach(proc)
        tail: list[str] = []
        rc = 1
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if cancel.cancelled():
                    proc.kill()
                    raise CancelledError()
                line = line.strip()
                if not line:
                    continue
                m = re.match(r"out_time_(?:ms|us)=(\d+)", line)
                if m and total_time:
                    done = int(m.group(1)) / 1_000_000.0
                    frac = max(0.0, min(0.99, done / total_time))
                    progress(t0 + frac * tspan, label)
                elif not line.startswith(("frame=", "fps=", "bitrate=", "total_size=",
                                          "out_time", "dup_frames=", "drop_frames=",
                                          "speed=", "progress=", "stream_")):
                    tail.append(line)
                    if len(tail) > 30:
                        tail.pop(0)
            rc = proc.wait()
        finally:
            cancel.detach(proc)
        if rc != 0:
            raise ConvertError(_friendly_ffmpeg_error(tail, rc))
        if total_time:
            progress(t0 + tspan, label)

    def convert(
        self,
        src: Path,
        target: str,
        tmp_out: Path,
        q: Quality,
        progress,
        cancel: CancelToken,
    ) -> None:
        exe = self.exe
        info = self.probe(src)

        if target in AUDIO_TARGETS:
            if info.duration is not None and not info.has_audio:
                raise ConvertError("这个文件里没有音频轨道，无法提取音频。")
            cmd = [exe, "-hide_banner", "-nostdin", "-y", "-i", str(src), "-vn"]
            cmd += self._audio_codec_args(target, q)
        elif target in VIDEO_TARGETS:
            if info.duration is not None and not info.has_video:
                raise ConvertError("这个文件里没有视频画面，无法转换为视频。")
            cmd = [exe, "-hide_banner", "-nostdin", "-y", "-i", str(src)]
            cmd += self._video_codec_args(target, q)
            if info.has_audio or info.duration is None:
                cmd += self._video_audio_args(target, q)
            if target == "mkv":
                # MKV 保留字幕
                cmd += ["-map", "0:v:0?", "-map", "0:a:0?", "-map", "0:s?", "-c:s", "copy"]
            else:
                cmd += ["-sn"]
            if target in ("mp4", "mov"):
                cmd += ["-movflags", "+faststart"]
        else:
            raise ConvertError(f"FFmpeg 后端不支持的目标格式：{target}")

        cmd += ["-progress", "pipe:1", "-nostats", "-loglevel", "error", str(tmp_out)]
        progress(0.02, "正在转换")
        self._run(cmd, info.duration, progress, cancel, "正在转换")

    def convert_gif(
        self,
        src: Path,
        tmp_out: Path,
        q: Quality,
        progress,
        cancel: CancelToken,
    ) -> None:
        """两遍法生成高质量 GIF（先调色板）。"""
        exe = self.exe
        info = self.probe(src)
        w = q.gif_width
        if info.width and info.width < w:
            w = info.width
        w -= w % 2
        if w < 2:
            w = 2
        fps = q.gif_fps
        with tempfile.TemporaryDirectory(prefix=".fw-gif-", dir=str(tmp_out.parent)) as td:
            palette = Path(td) / "palette.png"
            vf1 = f"fps={fps},scale={w}:-2:flags=lanczos,palettegen=stats_mode=diff"
            self._run(
                [exe, "-hide_banner", "-nostdin", "-y", "-i", str(src), "-vf", vf1, str(palette)],
                info.duration, progress, cancel, "生成调色板", 0.0, 0.2,
            )
            vf2 = (f"fps={fps},scale={w}:-2:flags=lanczos[x];[x][1:v]"
                   "paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
            self._run(
                [exe, "-hide_banner", "-nostdin", "-y", "-i", str(src), "-i", str(palette),
                 "-lavfi", vf2, "-loop", "0", str(tmp_out)],
                info.duration, progress, cancel, "生成 GIF", 0.2, 0.8,
            )
