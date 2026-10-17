# -*- coding: utf-8 -*-
"""不依赖 LibreOffice 的"基础模式"：
- docx → txt / pdf
- html → txt
会丢失复杂排版（表格样式、图片等），但胜在开箱即用。
"""
from __future__ import annotations

import html as html_mod
import os
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path

from ..errors import ConvertError

# ================================================================ docx → txt


def docx_to_txt(src: Path, out: Path) -> None:
    try:
        with zipfile.ZipFile(str(src)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
    except (KeyError, zipfile.BadZipFile) as e:
        raise ConvertError(f"无法读取 Word 文件：{e}") from e
    xml = re.sub(r"<w:tab\s*/>", "\t", xml)
    xml = re.sub(r"<w:br\s*/>", "\n", xml)
    xml = xml.replace("</w:tc>", "\t").replace("</w:p>", "\n")
    text = re.sub(r"<[^>]+>", "", xml)
    text = html_mod.unescape(text)
    result: list[str] = []
    blank = 0
    for line in text.splitlines():
        line = line.rstrip()
        if line.strip():
            blank = 0
            result.append(line)
        else:
            blank += 1
            if blank <= 1:
                result.append("")
    out.write_text("\n".join(result).strip() + "\n", encoding="utf-8")


# ================================================================ 中文字体


_CJK_FONT: str | None = None


def _cjk_font() -> str:
    """注册一个能显示中文的字体，返回字体名。"""
    global _CJK_FONT
    if _CJK_FONT:
        return _CJK_FONT
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfbase.ttfonts import TTFont

    candidates: dict[str, list[tuple[str, int | None]]] = {
        "darwin": [
            ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", None),
            ("/System/Library/Fonts/PingFang.ttc", 0),
            ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
            ("/Library/Fonts/Arial Unicode.ttf", None),
        ],
        "win32": [
            (r"C:\Windows\Fonts\msyh.ttc", 0),
            (r"C:\Windows\Fonts\msyh.ttf", None),
            (r"C:\Windows\Fonts\simhei.ttf", None),
            (r"C:\Windows\Fonts\simsun.ttc", 0),
        ],
        "linux": [
            ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 0),
            ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 0),
        ],
    }.get(sys.platform, [])

    name = "FW-CJK"
    for path, idx in candidates:
        if not os.path.isfile(path):
            continue
        try:
            if path.lower().endswith(".ttc"):
                font = TTFont(name, path, subfontIndex=idx if idx is not None else 0)
            else:
                font = TTFont(name, path)
            pdfmetrics.registerFont(font)
            pdfmetrics.registerFontFamily(
                name, normal=name, bold=name, italic=name, boldItalic=name
            )
            _CJK_FONT = name
            return name
        except Exception:
            continue
    # 兜底：reportlab 内置的中文 CID 字体
    try:
        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        pdfmetrics.registerFontFamily(
            "STSong-Light", normal="STSong-Light", bold="STSong-Light",
            italic="STSong-Light", boldItalic="STSong-Light",
        )
        _CJK_FONT = "STSong-Light"
    except Exception:
        _CJK_FONT = "Helvetica"
    return _CJK_FONT


# ================================================================ docx → pdf


def docx_to_pdf(src: Path, out: Path, progress=None) -> None:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import (LongTable, Paragraph as P, SimpleDocTemplate,
                                    Spacer, Table as RT, TableStyle)

    font = _cjk_font()

    def esc(t: str) -> str:
        return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    body = ParagraphStyle("body", fontName=font, fontSize=10.5, leading=16,
                          wordWrap="CJK", spaceAfter=4)
    styles = {
        "body": body,
        "title": ParagraphStyle("title", parent=body, fontSize=24, leading=32,
                                alignment=1, spaceAfter=16),
        "h1": ParagraphStyle("h1", parent=body, fontSize=19, leading=26,
                             spaceBefore=10, spaceAfter=8),
        "h2": ParagraphStyle("h2", parent=body, fontSize=16, leading=22,
                             spaceBefore=8, spaceAfter=6),
        "h3": ParagraphStyle("h3", parent=body, fontSize=14, leading=20,
                             spaceBefore=6, spaceAfter=4),
        "h4": ParagraphStyle("h4", parent=body, fontSize=12, leading=18,
                             spaceBefore=4, spaceAfter=4),
        "bullet": ParagraphStyle("bullet", parent=body, leftIndent=14),
        "note": ParagraphStyle("note", parent=body, fontSize=8.5, textColor=colors.grey),
        "cell": ParagraphStyle("cell", parent=body, fontSize=9, leading=13, spaceAfter=0),
    }

    doc = Document(str(src))
    story: list = []
    counter = {"n": 0}
    children = list(doc.element.body.iterchildren())
    total = max(1, len(children))

    for idx, child in enumerate(children):
        if progress and idx % 20 == 0:
            progress(0.05 + 0.9 * idx / total, "排版中")
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            flow = _paragraph_flow(Paragraph(child, doc), styles, counter, esc)
            if flow is not None:
                story.append(flow)
        elif tag == "tbl":
            table = Table(child, doc)
            data = [[(cell.text or "").strip().replace("\n", " ") for cell in row.cells]
                    for row in table.rows]
            if not data:
                continue
            width = max(len(r) for r in data)
            data = [r + [""] * (width - len(r)) for r in data]
            wrapped = [[P(esc(c), styles["cell"]) for c in row] for row in data]
            avail = A4[0] - 4 * cm
            col_w = [avail / width] * width
            tbl_cls = LongTable if len(wrapped) > 24 else RT
            tbl = tbl_cls(wrapped, colWidths=col_w, repeatRows=1)
            tbl.setStyle(TableStyle([
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            story.append(Spacer(1, 4))
            story.append(tbl)
            story.append(Spacer(1, 8))

    shapes = getattr(doc, "inline_shapes", None)
    if shapes is not None and len(shapes) > 0:
        story.append(Spacer(1, 10))
        story.append(P("（基础模式：图片等复杂内容未包含。安装 LibreOffice 后可获得完整排版。）",
                       styles["note"]))
    if not story:
        story.append(P("（空文档）", styles["body"]))

    SimpleDocTemplate(
        str(out), pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        title=src.stem,
    ).build(story)
    if progress:
        progress(1.0, "完成")


def _runs_markup(paragraph, esc) -> str:
    runs = list(paragraph.runs)
    if not runs:
        return esc(paragraph.text)
    parts = []
    for r in runs:
        t = esc(r.text)
        if not t:
            continue
        if r.bold:
            t = f"<b>{t}</b>"
        if r.italic:
            t = f"<i>{t}</i>"
        parts.append(t)
    return "".join(parts)


def _paragraph_flow(paragraph, styles, counter, esc):
    from reportlab.platypus import Paragraph as P

    name = paragraph.style.name or ""
    text = _runs_markup(paragraph, esc)
    if not text.strip():
        return None
    if name.startswith("Title"):
        return P(text, styles["title"])
    if name.startswith("Heading"):
        m = re.search(r"(\d+)", name)
        lvl = min(4, max(1, int(m.group(1)) if m else 1))
        return P(text, styles[f"h{lvl}"])
    low = name.lower()
    if "bullet" in low:
        return P("• " + text, styles["bullet"])
    if "number" in low:
        counter["n"] += 1
        return P(f"{counter['n']}. " + text, styles["bullet"])
    return P(text, styles["body"])


# ================================================================ html → txt


class _HtmlText(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
              "section", "article", "ul", "ol", "table", "blockquote", "pre", "hr"}
    _SKIP = {"script", "style", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append("\t")

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_txt(src: Path, out: Path) -> None:
    raw = None
    for enc in ("utf-8", "gb18030", "latin-1"):
        try:
            raw = src.read_text(encoding=enc)
            break
        except UnicodeDecodeError:
            continue
    if raw is None:  # pragma: no cover
        raise ConvertError("无法读取 HTML 文件（编码识别失败）")
    parser = _HtmlText()
    parser.feed(raw)
    text = "".join(parser.parts)
    result: list[str] = []
    blank = 0
    for line in text.splitlines():
        line = " ".join(line.split())
        if line:
            blank = 0
            result.append(line)
        else:
            blank += 1
            if blank <= 1:
                result.append("")
    out.write_text("\n".join(result).strip() + "\n", encoding="utf-8")
