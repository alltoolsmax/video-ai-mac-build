"""Log Chi Tiết: xem log trực tiếp, lọc theo mức, mở thư mục log."""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QPlainTextEdit, QVBoxLayout, QWidget

from ..widgets import button, combo, label
from ...core import log
from ...core.i18n import tr
from ...core.paths import logs_dir


class _Bridge(QObject):
    line = Signal(str, int)


class LogsPage(QWidget):
    LEVELS = {"Tất cả": 0, "Thông tin": logging.INFO, "Cảnh báo": logging.WARNING, "Lỗi": logging.ERROR}

    def __init__(self, ctx):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        top = QHBoxLayout()
        top.addWidget(label("Log chi tiết", "h1"))
        top.addStretch()
        self.level = combo(list(self.LEVELS), "Thông tin")
        self.follow = QCheckBox(tr("Tự cuộn"))
        self.follow.setChecked(True)
        b_clear = button("Xóa màn hình", "chip", "trash", "#fb7185")
        b_open = button("Mở thư mục log", "chip", "folder", "#67e8f9")
        top.addWidget(self.level)
        top.addWidget(self.follow)
        top.addWidget(b_clear)
        top.addWidget(b_open)
        v.addLayout(top)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(5000)
        self.view.setStyleSheet("font-family:'Cascadia Mono','Consolas',monospace;font-size:12px;")
        v.addWidget(self.view, 1)
        b_clear.clicked.connect(self.view.clear)
        from .gen_page import open_path
        b_open.clicked.connect(lambda: open_path(str(logs_dir())))
        self.bridge = _Bridge()
        self.bridge.line.connect(self._append)
        log.add_listener(lambda m, lv: self.bridge.line.emit(m, lv))
        try:
            tail = (logs_dir() / "app.log").read_text(encoding="utf-8", errors="replace").splitlines()[-300:]
            self.view.setPlainText("\n".join(tail))
        except Exception:
            pass

    def _append(self, msg, lv):
        if lv < self.LEVELS[self.level.currentText()]:
            return
        color = {logging.WARNING: "#fbbf24", logging.ERROR: "#fb7185", logging.CRITICAL: "#fb7185"}.get(lv)
        self.view.appendHtml(f'<span style="color:{color}">{msg}</span>' if color else msg.replace("<", "&lt;"))
        if self.follow.isChecked():
            self.view.moveCursor(QTextCursor.End)
