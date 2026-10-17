# -*- coding: utf-8 -*-
"""图形界面（PySide6）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QMainWindow, QMessageBox, QProgressBar, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from . import (APP_AUTHOR, APP_DEDICATION, APP_NAME, APP_SLUG,
               APP_VERSION, resource_path)
from .core.cancel import CancelToken
from .core.engine import Converter
from .core.errors import CancelledError
from .core.formats import PRESETS, SOURCE_GROUPS, kind_label

MAX_FILES = 1000

_COLOR_WAIT = "#8a94a6"
_COLOR_RUN = "#2e6be6"
_COLOR_OK = "#1a9c4b"
_COLOR_FAIL = "#d13438"


def _is_dark() -> bool:
    pal = QApplication.palette()
    return pal.color(QPalette.ColorRole.Window).lightness() < 128


# ================================================================ 拖放区


class DropZone(QFrame):
    filesDropped = Signal(list)
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropzone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(78)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        self.label = QLabel("＋ 把文件或文件夹拖到这里，也可以点击选择")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        lay.addWidget(self.label)
        self._active = False
        self._apply_style()

    def _apply_style(self):
        dark = _is_dark()
        if self._active:
            border, bg = "#4b8bf5", ("#22304a" if dark else "#e8f0ff")
        else:
            border = "#5c6570" if dark else "#9aa7b5"
            bg = "#262b31" if dark else "#f5f7fa"
        self.setStyleSheet(
            f"QFrame#dropzone {{ border: 2px dashed {border}; border-radius: 12px;"
            f" background: {bg}; }}"
        )

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._active = True
            self._apply_style()

    def dragLeaveEvent(self, e):
        self._active = False
        self._apply_style()

    def dropEvent(self, e):
        self._active = False
        self._apply_style()
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
        e.acceptProposedAction()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(e)


# ================================================================ 后台线程


class ConvertWorker(QThread):
    job_started = Signal(int)
    job_progress = Signal(int, float, str)
    job_finished = Signal(int, str, str)
    batch_finished = Signal(int, int, bool)  # 成功数, 失败数, 是否被取消

    def __init__(self, converter: Converter, jobs, dst_dir, quality, overwrite, parent=None):
        super().__init__(parent)
        self.converter = converter
        self.jobs = jobs                # [(行号, 源文件 Path, 目标扩展名)]
        self.dst_dir = dst_dir          # Path | None
        self.quality = quality
        self.overwrite = overwrite
        self.token = CancelToken()

    def cancel(self):
        self.token.cancel()

    def run(self):
        ok = fail = 0
        cancelled = False
        for row, src, target in self.jobs:
            if self.token.cancelled():
                cancelled = True
                break
            self.job_started.emit(row)

            def cb(frac, text, _row=row):
                self.job_progress.emit(_row, -1.0 if frac is None else float(frac), text or "")

            try:
                out = self.converter.convert(
                    src, target, dst_dir=self.dst_dir, quality=self.quality,
                    overwrite=self.overwrite, progress=cb, cancel=self.token,
                )
                ok += 1
                self.job_finished.emit(row, str(out), "")
            except CancelledError:
                self.job_finished.emit(row, "", "已取消")
                cancelled = True
                break
            except Exception as e:  # 单个文件失败不影响其它文件
                fail += 1
                self.job_finished.emit(row, "", str(e))
        self.batch_finished.emit(ok, fail, cancelled)


# ================================================================ 主窗口


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.converter = Converter()
        self.rows: list[dict] = []
        self._added: set[str] = set()
        self.out_dir: Path | None = None
        self.last_out_dir: Path | None = None
        self.worker: ConvertWorker | None = None
        self.running = False
        self._total_jobs = 0
        self._done_jobs = 0
        self._cur_frac = 0.0
        self._build_ui()

    # ------------------------------------------------------------ 界面搭建

    def _build_ui(self):
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.resize(1000, 700)
        icon_path = resource_path("assets", "icon_256.png")
        if os.path.isfile(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        central = QWidget()
        self.setCentralWidget(central)
        v = QVBoxLayout(central)
        v.setContentsMargins(16, 12, 16, 12)
        v.setSpacing(10)

        # 标题
        head = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel(APP_NAME)
        f = title.font()
        f.setPointSize(f.pointSize() + 7)
        f.setBold(True)
        title.setFont(f)
        subtitle = QLabel("音频、视频、图片、文档，拖进来就能转")
        subtitle.setStyleSheet("color: #8a94a6;")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        head.addLayout(title_box)
        head.addStretch(1)
        self.env_btn = QPushButton("环境自检")
        self.env_btn.setFlat(True)
        self.env_btn.clicked.connect(self.show_env_dialog)
        head.addWidget(self.env_btn, 0, Qt.AlignmentFlag.AlignBottom)
        v.addLayout(head)

        # 拖放区
        self.drop = DropZone()
        self.drop.filesDropped.connect(self.add_paths)
        self.drop.clicked.connect(self.choose_files)
        v.addWidget(self.drop)

        # 批量设置
        h1 = QHBoxLayout()
        h1.addWidget(QLabel("批量设置："))
        self.batch_combo = QComboBox()
        self.batch_combo.setMinimumWidth(260)
        self.batch_combo.activated.connect(self._apply_batch)
        h1.addWidget(self.batch_combo)
        h1.addStretch(1)
        self.clear_btn = QPushButton("清空列表")
        self.clear_btn.clicked.connect(self.clear_all)
        h1.addWidget(self.clear_btn)
        v.addLayout(h1)

        # 文件列表
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["文件", "类型", "转换为", "状态"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i, w in ((1, 100), (2, 210), (3, 250)):
            header.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
            self.table.setColumnWidth(i, w)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.cellDoubleClicked.connect(self._open_row_file)
        v.addWidget(self.table, 1)

        # 输出设置
        h2 = QHBoxLayout()
        h2.addWidget(QLabel("输出到："))
        self.out_label = QLabel("源文件所在文件夹")
        self.out_label.setStyleSheet("color: #8a94a6;")
        h2.addWidget(self.out_label)
        btn_out = QPushButton("选择文件夹…")
        btn_out.clicked.connect(self.choose_out_dir)
        h2.addWidget(btn_out)
        btn_reset = QPushButton("默认")
        btn_reset.clicked.connect(self.reset_out_dir)
        h2.addWidget(btn_reset)
        h2.addStretch(1)
        h2.addWidget(QLabel("画质："))
        self.quality_combo = QComboBox()
        for p in PRESETS:
            self.quality_combo.addItem(p.label, p.key)
            self.quality_combo.setItemData(
                self.quality_combo.count() - 1, p.desc, Qt.ItemDataRole.ToolTipRole)
        self.quality_combo.setCurrentIndex(1)  # 均衡
        h2.addWidget(self.quality_combo)
        self.overwrite_check = QCheckBox("覆盖同名文件")
        h2.addWidget(self.overwrite_check)
        self.auto_open_check = QCheckBox("完成后打开输出文件夹")
        h2.addWidget(self.auto_open_check)
        v.addLayout(h2)

        # 操作行
        h3 = QHBoxLayout()
        self.open_dir_btn = QPushButton("打开输出文件夹")
        self.open_dir_btn.clicked.connect(self._open_last_dir)
        self.open_dir_btn.hide()
        h3.addWidget(self.open_dir_btn)
        h3.addStretch(1)
        self.overall = QProgressBar()
        self.overall.setMinimumWidth(260)
        self.overall.setRange(0, 100)
        self.overall.hide()
        h3.addWidget(self.overall)
        self.start_btn = QPushButton("开始转换")
        self.start_btn.setObjectName("primary")
        self.start_btn.setMinimumHeight(40)
        self.start_btn.setMinimumWidth(160)
        self.start_btn.clicked.connect(self.start)
        h3.addWidget(self.start_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setMinimumHeight(40)
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self._cancel)
        h3.addWidget(self.cancel_btn)
        v.addLayout(h3)

        self.setStyleSheet("""
            QPushButton#primary { background: #2e6be6; color: white; border: none;
                                  border-radius: 8px; padding: 9px 22px; font-weight: 600; }
            QPushButton#primary:hover { background: #245ed1; }
            QPushButton#primary:disabled { background: #9aa7b5; }
        """)

        # 菜单
        file_menu = self.menuBar().addMenu("文件(&F)")
        act_files = QAction("添加文件…", self)
        act_files.setShortcut("Ctrl+O")
        act_files.triggered.connect(self.choose_files)
        file_menu.addAction(act_files)
        act_folder = QAction("添加文件夹…", self)
        act_folder.triggered.connect(self.choose_folder)
        file_menu.addAction(act_folder)
        file_menu.addSeparator()
        act_clear = QAction("清空列表", self)
        act_clear.triggered.connect(self.clear_all)
        file_menu.addAction(act_clear)
        file_menu.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        help_menu = self.menuBar().addMenu("帮助(&H)")
        act_env = QAction("检查运行环境…", self)
        act_env.triggered.connect(self.show_env_dialog)
        help_menu.addAction(act_env)
        act_about = QAction(f"关于 {APP_NAME}", self)
        act_about.triggered.connect(self._show_about)
        help_menu.addAction(act_about)

        # 状态栏
        self.dep_label = QLabel(self.converter.deps.status_text())
        self.statusBar().addPermanentWidget(self.dep_label)
        self.statusBar().showMessage("就绪：把文件拖进窗口即可开始")
        self._update_start_enabled()
        self._refresh_batch_combo()

    # ------------------------------------------------------------ 添加文件

    def _file_filter(self) -> str:
        patterns = " ".join("*." + e for e in sorted(SOURCE_GROUPS))
        return f"支持的格式 ({patterns});;所有文件 (*)"

    def choose_files(self):
        if self.running:
            return
        files, _ = QFileDialog.getOpenFileNames(self, "选择要转换的文件", "", self._file_filter())
        if files:
            self.add_paths(files)

    def choose_folder(self):
        if self.running:
            return
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹")
        if folder:
            self.add_paths([folder])

    def add_paths(self, paths: list[str]):
        if self.running:
            return
        files: list[Path] = []
        unsupported: list[str] = []
        for raw in paths:
            p = Path(raw)
            try:
                if p.is_dir():
                    for sub in sorted(p.rglob("*")):
                        if sub.is_file():
                            if sub.suffix.lower().lstrip(".") in SOURCE_GROUPS:
                                files.append(sub)
                            else:
                                unsupported.append(sub.name)
                elif p.is_file():
                    if p.suffix.lower().lstrip(".") in SOURCE_GROUPS:
                        files.append(p)
                    else:
                        unsupported.append(p.name)
            except OSError:
                continue

        added = 0
        for f in files:
            if self.table.rowCount() >= MAX_FILES:
                self.statusBar().showMessage(f"一次最多处理 {MAX_FILES} 个文件，其余已忽略", 8000)
                break
            try:
                key = os.path.normcase(str(f.resolve()))
            except OSError:
                key = os.path.normcase(str(f))
            if key in self._added:
                continue
            self._added.add(key)
            self._append_row(f)
            added += 1

        self._refresh_batch_combo()
        self._update_start_enabled()

        parts = []
        if added:
            parts.append(f"已添加 {added} 个文件")
        elif files:
            parts.append("这些文件已经在列表里了")
        if unsupported:
            parts.append(f"跳过 {len(unsupported)} 个不支持的格式")
        if parts:
            self.statusBar().showMessage("，".join(parts), 8000)
        if unsupported:
            sample = "、".join(unsupported[:8]) + ("…" if len(unsupported) > 8 else "")
            QMessageBox.information(self, "有文件被跳过",
                                    f"下面这些文件格式暂不支持，已跳过：\n\n{sample}")

    def _append_row(self, path: Path):
        group = SOURCE_GROUPS.get(path.suffix.lower().lstrip("."), "")
        r = self.table.rowCount()
        self.table.insertRow(r)

        name_item = QTableWidgetItem(path.name)
        name_item.setToolTip(str(path))
        self.table.setItem(r, 0, name_item)

        type_item = QTableWidgetItem(kind_label(group))
        type_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(r, 1, type_item)

        combo = QComboBox()
        first_available = -1
        for i, t in enumerate(self.converter.targets_for(path)):
            label = t.label if t.available else f"{t.label} · {t.note}"
            combo.addItem(label, t.ext)
            item = combo.model().item(i)
            if not t.available:
                item.setEnabled(False)
                combo.setItemData(i, t.note, Qt.ItemDataRole.ToolTipRole)
            if t.available and first_available < 0:
                first_available = i
        combo.setCurrentIndex(first_available if first_available >= 0 else -1)
        self.table.setCellWidget(r, 2, combo)

        status = QLabel("等待中")
        status.setContentsMargins(8, 0, 8, 0)
        status.setStyleSheet(f"color: {_COLOR_WAIT};")
        self.table.setCellWidget(r, 3, status)

        self.rows.append({
            "path": path, "group": group, "combo": combo,
            "status": status, "out": "",
        })

    # ------------------------------------------------------------ 批量设置

    def _refresh_batch_combo(self):
        was = self.batch_combo.currentData()
        self.batch_combo.blockSignals(True)
        self.batch_combo.clear()
        self.batch_combo.addItem("选择要批量设置的目标格式…", None)
        seen: list[str] = []
        for data in self.rows:
            combo = data["combo"]
            for i in range(combo.count()):
                ext = combo.itemData(i)
                if ext and ext not in seen and combo.model().item(i).isEnabled():
                    seen.append(ext)
        for ext in seen:
            self.batch_combo.addItem(ext.upper(), ext)
        idx = self.batch_combo.findData(was)
        self.batch_combo.setCurrentIndex(idx if idx > 0 else 0)
        self.batch_combo.blockSignals(False)

    def _apply_batch(self, index: int):
        ext = self.batch_combo.itemData(index)
        if not ext:
            return
        applied = skipped = 0
        for data in self.rows:
            combo = data["combo"]
            for i in range(combo.count()):
                if combo.itemData(i) == ext and combo.model().item(i).isEnabled():
                    combo.setCurrentIndex(i)
                    applied += 1
                    break
            else:
                skipped += 1
        msg = f"已把 {applied} 个文件的转换目标设为 {str(ext).upper()}"
        if skipped:
            msg += f"（{skipped} 个文件不支持，已跳过）"
        self.statusBar().showMessage(msg, 6000)
        self.batch_combo.blockSignals(True)
        self.batch_combo.setCurrentIndex(0)
        self.batch_combo.blockSignals(False)

    # ------------------------------------------------------------ 输出设置

    def choose_out_dir(self):
        folder = QFileDialog.getExistingDirectory(self, "选择输出文件夹")
        if folder:
            self.out_dir = Path(folder)
            self.out_label.setText(folder)
            self.out_label.setToolTip(folder)
            self.out_label.setStyleSheet("")

    def reset_out_dir(self):
        self.out_dir = None
        self.out_label.setText("源文件所在文件夹")
        self.out_label.setToolTip("")
        self.out_label.setStyleSheet("color: #8a94a6;")

    # ------------------------------------------------------------ 开始 / 取消

    def _update_start_enabled(self):
        self.start_btn.setEnabled(bool(self.rows) and not self.running)

    def start(self):
        if self.running:
            return
        jobs = []
        for r, data in enumerate(self.rows):
            ext = data["combo"].currentData()
            if ext:
                jobs.append((r, data["path"], ext))
                data["status"].setText("等待中")
                data["status"].setStyleSheet(f"color: {_COLOR_WAIT};")
                data["status"].setToolTip("")
                data["out"] = ""
        if not jobs:
            QMessageBox.information(self, "没有任务", "请先添加文件，并为它们选择目标格式。")
            return

        self.running = True
        self._set_ui_running(True)
        self._total_jobs = len(jobs)
        self._done_jobs = 0
        self._cur_frac = 0.0
        self.overall.setValue(0)
        self.statusBar().showMessage(f"开始转换 {len(jobs)} 个文件…")

        self.worker = ConvertWorker(
            self.converter, jobs, self.out_dir,
            self.quality_combo.currentData(), self.overwrite_check.isChecked(), parent=self,
        )
        self.worker.job_started.connect(self._on_job_started)
        self.worker.job_progress.connect(self._on_job_progress)
        self.worker.job_finished.connect(self._on_job_finished)
        self.worker.batch_finished.connect(self._on_batch_finished)
        self.worker.start()

    def _set_ui_running(self, running: bool):
        self.running = running
        self.drop.setEnabled(not running)
        self.clear_btn.setEnabled(not running)
        self.batch_combo.setEnabled(not running)
        self.quality_combo.setEnabled(not running)
        self.overwrite_check.setEnabled(not running)
        self.auto_open_check.setEnabled(not running)
        self.start_btn.setVisible(not running)
        self.cancel_btn.setVisible(running)
        self.overall.setVisible(running)
        for data in self.rows:
            data["combo"].setEnabled(not running)
        self._update_start_enabled()

    def _cancel(self):
        if self.worker:
            self.statusBar().showMessage("正在取消…")
            self.worker.cancel()

    def _on_job_started(self, row: int):
        data = self.rows[row]
        data["status"].setText("转换中 0%")
        data["status"].setStyleSheet(f"color: {_COLOR_RUN};")
        self._cur_frac = 0.0

    def _on_job_progress(self, row: int, frac: float, text: str):
        data = self.rows[row]
        if frac < 0:
            data["status"].setText(text or "转换中…")
            data["status"].setToolTip(text)
        else:
            data["status"].setText(f"转换中 {int(frac * 100)}%")
            self._cur_frac = max(0.0, min(1.0, frac))
        self._update_overall()

    def _on_job_finished(self, row: int, out: str, error: str):
        data = self.rows[row]
        self._done_jobs += 1
        self._cur_frac = 0.0
        if error:
            first = error.splitlines()[0] if error else "转换失败"
            data["status"].setText(f"失败：{first[:36]}")
            data["status"].setStyleSheet(f"color: {_COLOR_FAIL};")
            data["status"].setToolTip(error)
            data["out"] = ""
        else:
            data["status"].setText("完成 ✓")
            data["status"].setStyleSheet(f"color: {_COLOR_OK};")
            data["status"].setToolTip(f"{out}\n（双击本行打开文件）")
            data["out"] = out
            self.last_out_dir = Path(out).parent
            self.open_dir_btn.show()
        self._update_overall()

    def _on_batch_finished(self, ok: int, fail: int, cancelled: bool):
        self._set_ui_running(False)
        if cancelled:
            self.statusBar().showMessage("已取消")
        else:
            self.overall.setValue(100)
            self.statusBar().showMessage(f"转换结束：成功 {ok} 个，失败 {fail} 个", 0)
        if fail:
            QMessageBox.warning(
                self, "部分文件转换失败",
                f"有 {fail} 个文件转换失败。\n把鼠标移到对应行的『状态』上可以查看具体原因。",
            )
        if self.auto_open_check.isChecked() and ok and self.last_out_dir:
            self._open_last_dir()

    def _update_overall(self):
        if not self._total_jobs:
            return
        value = (self._done_jobs + self._cur_frac) / self._total_jobs
        self.overall.setValue(int(max(0.0, min(1.0, value)) * 100))

    # ------------------------------------------------------------ 小工具

    def _open_row_file(self, row: int, _col: int):
        if row < 0 or row >= len(self.rows):
            return
        data = self.rows[row]
        target = data["out"] or str(data["path"])
        if target and os.path.exists(target):
            QDesktopServices.openUrl(QUrl.fromLocalFile(target))

    def _open_last_dir(self):
        if self.last_out_dir and self.last_out_dir.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_out_dir)))

    def clear_all(self):
        if self.running:
            return
        self.table.setRowCount(0)
        self.rows.clear()
        self._added.clear()
        self.open_dir_btn.hide()
        self._refresh_batch_combo()
        self._update_start_enabled()
        self.statusBar().showMessage("已清空", 4000)

    def show_env_dialog(self):
        deps = self.converter.deps
        rows_html = []
        for name, ok, desc in deps.summary_lines():
            icon = "✅" if ok else "❌"
            rows_html.append(
                f"<tr><td>{icon}</td><td><b>{name}</b></td>"
                f"<td style='color:#888'>{desc}</td></tr>"
            )
        enc_html = ""
        if deps.ffmpeg.ok:
            bits = " · ".join(f"{n} {'✓' if ok else '✗'}" for n, ok in deps.key_encoders())
            enc_html = f"<p><b>关键编码器：</b>{bits}</p>"
        html = (
            "<table cellspacing='0' cellpadding='3'>" + "".join(rows_html) + "</table>"
            + enc_html
            + "<p style='color:#888'>LibreOffice 负责 Word / Excel / PPT 相关转换；"
              "没安装时，docx → PDF / TXT 会自动使用基础模式。</p>"
        )
        box = QMessageBox(self)
        box.setWindowTitle("运行环境自检")
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(html)
        box.exec()

    def _show_about(self):
        QMessageBox.about(
            self, f"关于 {APP_NAME}",
            f"<h3>{APP_NAME} {APP_VERSION}</h3>"
            f"<p>音频、视频、图片、文档，一个窗口全搞定。</p>"
            f"<p>{APP_DEDICATION}，由 {APP_AUTHOR} 制作。</p>"
            f"<p style='color:#888'>转换引擎：FFmpeg · LibreOffice · Pillow · PyMuPDF</p>",
        )

    def closeEvent(self, event):
        if self.running and self.worker:
            ret = QMessageBox.question(
                self, "正在转换", "还有文件在转换中，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.worker.cancel()
            self.worker.wait(3000)
        event.accept()


# ================================================================ 入口


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName(APP_SLUG)
    icon_path = resource_path("assets", "icon_256.png")
    if os.path.isfile(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
