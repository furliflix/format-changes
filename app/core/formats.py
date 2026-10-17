# -*- coding: utf-8 -*-
"""格式登记表：来源格式识别、目标格式列表、画质预设。"""
from __future__ import annotations

from dataclasses import dataclass

# ---- 类别 ----
AUDIO = "audio"
VIDEO = "video"
GIF = "gif"
IMAGE = "image"
DOC = "doc"          # Word 类文档
SHEET = "sheet"      # 电子表格
SLIDES = "slides"    # 演示文稿
PDF = "pdf"

GROUP_LABEL = {
    AUDIO: "音频",
    VIDEO: "视频",
    GIF: "GIF 动图",
    IMAGE: "图片",
    DOC: "文档",
    SHEET: "表格",
    SLIDES: "演示文稿",
    PDF: "PDF",
}


def kind_label(group: str) -> str:
    return GROUP_LABEL.get(group, group)


# ---------- 来源格式（扩展名 -> 类别）----------
SOURCE_GROUPS: dict[str, str] = {}


def _reg(group: str, exts: str) -> None:
    for e in exts.split():
        SOURCE_GROUPS[e] = group


_reg(AUDIO, "mp3 wav flac ogg oga opus aac m4a wma aiff alac amr")
_reg(VIDEO, "mp4 m4v mkv mov avi webm wmv flv mpg mpeg ts 3gp")
_reg(GIF, "gif")
_reg(IMAGE, "png jpg jpeg webp bmp tiff tif ico heic heif")
_reg(DOC, "docx doc odt rtf txt html htm")
_reg(SHEET, "xlsx xls ods csv")
_reg(SLIDES, "pptx ppt odp")
_reg(PDF, "pdf")

ALL_SOURCE_EXTS = set(SOURCE_GROUPS)


# ---------- 目标格式 ----------
@dataclass(frozen=True)
class TargetSpec:
    ext: str
    group: str


TARGET_SPECS: dict[str, TargetSpec] = {}


def _treg(group: str, exts: str) -> None:
    for e in exts.split():
        TARGET_SPECS[e] = TargetSpec(ext=e, group=group)


_treg(AUDIO, "mp3 ogg wav flac m4a aac opus wma")
_treg(VIDEO, "mp4 mkv mov webm avi wmv flv")
_treg(GIF, "gif")
_treg(IMAGE, "png jpg webp bmp tiff ico")
_treg(PDF, "pdf")
_treg(DOC, "docx odt rtf txt html")
_treg(SHEET, "xlsx xls ods csv")
_treg(SLIDES, "pptx ppt odp")

# 每个来源类别可以选择的目标格式（与源同名的会在程序里自动去掉）
_TARGETS_BY_GROUP = {
    AUDIO:  ["mp3", "ogg", "wav", "flac", "m4a", "aac", "opus", "wma"],
    VIDEO:  ["mp4", "mkv", "mov", "webm", "avi", "wmv", "flv", "gif",
             "mp3", "ogg", "wav", "flac", "m4a"],
    GIF:    ["mp4", "mkv", "mov", "webm", "avi", "wmv", "flv",
             "mp3", "ogg", "wav", "flac", "m4a", "png", "jpg"],
    IMAGE:  ["png", "jpg", "webp", "bmp", "tiff", "ico", "pdf"],
    DOC:    ["pdf", "docx", "odt", "rtf", "txt", "html"],
    SHEET:  ["pdf", "xlsx", "xls", "ods", "csv", "html"],
    SLIDES: ["pdf", "pptx", "ppt", "odp"],
    PDF:    ["txt", "docx"],
}


def targets_by_group(group: str) -> list[str]:
    return list(_TARGETS_BY_GROUP.get(group, []))


def target_label(ext: str) -> str:
    spec = TARGET_SPECS.get(ext)
    if not spec:
        return ext
    return f"{ext.upper()}（{kind_label(spec.group)}）"


# ---------- 画质预设 ----------
@dataclass(frozen=True)
class Quality:
    key: str
    label: str
    desc: str
    v_preset: str        # x264 preset
    v_crf: int           # x264 crf（越小越清晰、体积越大）
    a_bitrate: str       # 音频码率
    mp3_q: int           # mp3 的 -q:a
    vorbis_q: int        # ogg vorbis 的 -q:a
    vp9_crf: int         # webm 的 crf
    img_quality: int     # jpg / webp 质量（1-100）
    gif_fps: int
    gif_width: int


PRESETS = [
    Quality("fast", "快速", "转得快，体积稍大", "veryfast", 23, "160k", 4, 4, 38, 88, 12, 480),
    Quality("balanced", "均衡", "日常使用（推荐）", "medium", 22, "192k", 2, 5, 33, 92, 12, 640),
    Quality("high", "高画质", "转得慢，质量最好", "slow", 18, "256k", 0, 7, 28, 96, 15, 720),
    Quality("small", "小体积", "压得很小，适合分享", "medium", 28, "96k", 7, 2, 40, 80, 10, 480),
]

PRESETS_BY_KEY = {p.key: p for p in PRESETS}
DEFAULT_PRESET = "balanced"
