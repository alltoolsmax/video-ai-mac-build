"""Cửa sổ xem lớn ảnh / video kết quả, chuyển qua lại giữa các kết quả của cùng một tác vụ."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSlider,
                               QStackedWidget, QVBoxLayout, QWidget)

from .theme import C, icon
from .widgets import button, label
from ..core.i18n import tr

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAS_MM = True
except Exception:  # pragma: no cover
    HAS_MM = False


class MediaViewer(QDialog):
    def __init__(self, parent, outputs: list[dict], title: str = "", start: int = 0):
        super().__init__(parent)
        self.outputs = [o for o in outputs if Path(o["path"]).exists()]
        self.i = min(start, max(0, len(self.outputs) - 1))
        self.setWindowTitle(tr("Xem kết quả"))
        self.resize(1180, 820)
        self.setStyleSheet(f"QDialog{{background:#04061a;}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        top = QHBoxLayout()
        self.title = label(title[:140], "muted")
        self.title.setWordWrap(True)
        top.addWidget(self.title, 1)
        self.counter = label("", "faint")
        top.addWidget(self.counter)
        b_dir = button("Mở thư mục", "chip", "folder", "#67e8f9")
        b_dir.clicked.connect(self._reveal)
        b_ext = button("Mở bằng ứng dụng khác", "chip", "eye", "#67e8f9")
        b_ext.clicked.connect(self._external)
        top.addWidget(b_dir)
        top.addWidget(b_ext)
        v.addLayout(top)
        mid = QHBoxLayout()
        self.b_prev = QPushButton()
        self.b_prev.setIcon(icon("chev_left", "#ffffff", 22))
        self.b_next = QPushButton()
        self.b_next.setIcon(icon("chev_right", "#ffffff", 22))
        for b in (self.b_prev, self.b_next):
            b.setProperty("kind", "icon")
            b.setFixedSize(44, 64)
        self.b_prev.clicked.connect(lambda: self.show_index(self.i - 1))
        self.b_next.clicked.connect(lambda: self.show_index(self.i + 1))
        self.stack = QStackedWidget()
        self.img = QLabel()
        self.img.setAlignment(Qt.AlignCenter)
        self.stack.addWidget(self.img)
        vw = QWidget()
        vv = QVBoxLayout(vw)
        vv.setContentsMargins(0, 0, 0, 0)
        if HAS_MM:
            self.video = QVideoWidget()
            self.player = QMediaPlayer(self)
            self.player.setVideoOutput(self.video)
            self.aout = None
            if os.environ.get("VIDEOAI_HEADLESS") != "1":
                self.aout = QAudioOutput(self)
                self.player.setAudioOutput(self.aout)
            vv.addWidget(self.video, 1)
            ctl = QHBoxLayout()
            self.b_play = QPushButton()
            self.b_play.setProperty("kind", "icon")
            self.b_play.setFixedSize(40, 32)
            self.b_play.setIcon(icon("pause", "#ffffff", 16))
            self.b_play.clicked.connect(self._toggle)
            self.seek = QSlider(Qt.Horizontal)
            self.seek.sliderMoved.connect(lambda v: self.player.setPosition(v))
            self.tlabel = label("", "faint")
            self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
            self.player.positionChanged.connect(self._pos)
            self.player.playbackStateChanged.connect(lambda s: self.b_play.setIcon(
                icon("pause" if s == QMediaPlayer.PlayingState else "play", "#ffffff", 16)))
            ctl.addWidget(self.b_play)
            ctl.addWidget(self.seek, 1)
            ctl.addWidget(self.tlabel)
            vv.addLayout(ctl)
        else:
            self.player = None
            vv.addWidget(label("Không phát được video trong ứng dụng – bấm 'Mở bằng ứng dụng khác'.", "muted"))
        self.stack.addWidget(vw)
        mid.addWidget(self.b_prev)
        mid.addWidget(self.stack, 1)
        mid.addWidget(self.b_next)
        v.addLayout(mid, 1)
        self.strip = QListWidget()
        self.strip.setViewMode(QListWidget.IconMode)
        self.strip.setFlow(QListWidget.LeftToRight)
        self.strip.setIconSize(QSize(96, 54))
        self.strip.setFixedHeight(84)
        self.strip.setWrapping(False)
        self.strip.currentRowChanged.connect(lambda r: r >= 0 and r != self.i and self.show_index(r))
        for o in self.outputs:
            it = QListWidgetItem()
            pm = QPixmap(o["path"]) if o["kind"] == "image" else QPixmap()
            if pm.isNull():
                from .task_table import video_thumb_file
                tf = video_thumb_file(o["path"])
                pm = QPixmap(str(tf)) if tf.exists() else icon("film", "#c4a5ff", 40).pixmap(54, 54)
            it.setIcon(QIcon(pm.scaled(96, 54, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
            self.strip.addItem(it)
        v.addWidget(self.strip)
        self.strip.setVisible(len(self.outputs) > 1)
        for k, fn in (("Left", lambda: self.show_index(self.i - 1)), ("Right", lambda: self.show_index(self.i + 1)),
                      ("Space", self._toggle), ("Escape", self.close)):
            QShortcut(QKeySequence(k), self, activated=fn)
        self.show_index(self.i)

    def _pos(self, ms):
        if not self.seek.isSliderDown():
            self.seek.setValue(ms)
        d = self.player.duration()
        self.tlabel.setText(f"{ms / 1000:0.1f} / {d / 1000:0.1f}s")

    def _toggle(self):
        if self.player and self.stack.currentIndex() == 1:
            if self.player.playbackState() == QMediaPlayer.PlayingState:
                self.player.pause()
            else:
                self.player.play()

    def show_index(self, i: int):
        if not self.outputs:
            return
        self.i = i % len(self.outputs)
        o = self.outputs[self.i]
        self.counter.setText(f"{self.i + 1} / {len(self.outputs)} · {Path(o['path']).name}")
        self.strip.blockSignals(True)
        self.strip.setCurrentRow(self.i)
        self.strip.blockSignals(False)
        self.b_prev.setVisible(len(self.outputs) > 1)
        self.b_next.setVisible(len(self.outputs) > 1)
        if o["kind"] == "image":
            if self.player:
                self.player.stop()
            self.stack.setCurrentIndex(0)
            self._pm = QPixmap(o["path"])
            self._fit()
        else:
            self.stack.setCurrentIndex(1)
            if self.player:
                self.player.setSource(QUrl.fromLocalFile(o["path"]))
                self.player.play()

    def _fit(self):
        if getattr(self, "_pm", None) is not None and not self._pm.isNull():
            s = self.img.size()
            self.img.setPixmap(self._pm.scaled(s.width() - 4, s.height() - 4, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def _reveal(self):
        from .pages.gen_page import reveal
        if self.outputs:
            reveal(self.outputs[self.i]["path"])

    def _external(self):
        from .pages.gen_page import open_path
        if self.outputs:
            open_path(self.outputs[self.i]["path"])

    def closeEvent(self, e):
        if self.player:
            self.player.stop()
        super().closeEvent(e)
