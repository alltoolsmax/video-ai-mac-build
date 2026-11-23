"""Cửa sổ xem lớn ảnh / video kết quả.

· Khung cửa sổ theo đúng tỷ lệ của ảnh / video, ảnh / video phủ kín khung (không chữ, không tên file).
· Ảnh: lăn chuột để phóng to / thu nhỏ quanh con trỏ, kéo để di chuyển, bấm đúp để về vừa khung.
· Nhiều kết quả: mũi tên nổi hai bên (hoặc phím ← →). Nút "Mở thư mục" / "Mở bằng ứng dụng khác" nổi ở góc trên phải.
"""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, QSizeF, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QColor, QGuiApplication, QImageReader, QKeySequence, QPainter, QPixmap, QShortcut
from PySide6.QtWidgets import (QDialog, QFrame, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView, QHBoxLayout,
                               QLabel, QMenu, QPushButton, QSlider, QStackedWidget, QVBoxLayout, QWidget)

from .theme import icon
from .widgets import button
from ..core.i18n import tr

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
    HAS_MM = True
except Exception:  # pragma: no cover
    HAS_MM = False

BG = "#000000"
OVERLAY_BTN = ("QPushButton{background:rgba(0,0,0,110);border:none;border-radius:22px;}"
               "QPushButton:hover{background:rgba(124,58,237,190);}")


class ZoomView(QGraphicsView):
    """Ảnh vừa khung; lăn chuột phóng to / thu nhỏ quanh con trỏ, kéo để di chuyển, bấm đúp về vừa khung."""
    MAX_ZOOM = 12.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.item = QGraphicsPixmapItem()
        self.item.setTransformationMode(Qt.SmoothTransformation)
        self.scene().addItem(self.item)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setFrameShape(QFrame.NoFrame)
        self.setBackgroundBrush(QColor(BG))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setAlignment(Qt.AlignCenter)
        self.zoom = 1.0                     # 1 = vừa khung

    def set_pixmap(self, pm: QPixmap):
        self.item.setPixmap(pm)
        self.scene().setSceneRect(QRectF(pm.rect()))
        self.fit()

    def fit(self):
        if self.item.pixmap().isNull():
            return
        self.resetTransform()
        r, vp = self.item.boundingRect(), self.viewport().rect()
        k = min(vp.width() / r.width(), vp.height() / r.height())   # fitInView của Qt chừa viền 2px → tự tính
        self.scale(k, k)
        self.centerOn(self.item)
        self.zoom = 1.0

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if not d or self.item.pixmap().isNull():
            return
        f = 1.15 if d > 0 else 1 / 1.15
        new = self.zoom * f
        if new <= 1.0:                      # không nhỏ hơn vừa khung
            self.fit()
            return
        if new > self.MAX_ZOOM:
            f = self.MAX_ZOOM / self.zoom
            new = self.MAX_ZOOM
        self.scale(f, f)
        self.zoom = new

    def mouseDoubleClickEvent(self, e):
        self.fit()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.zoom <= 1.0001:
            self.fit()


def media_size(o: dict) -> QSize:
    """Kích thước thật của ảnh / video (video: theo ảnh xem trước đã lưu)."""
    p = o["path"]
    if o.get("kind") != "image":
        from .task_table import video_thumb_file
        tf = video_thumb_file(p)
        p = str(tf) if tf.exists() else ""
    if p:
        s = QImageReader(p).size()
        if s.isValid() and s.width() > 0 and s.height() > 0:
            return s
    return QSize(1080, 1920) if o.get("kind") != "image" else QSize(1024, 1024)


class MediaViewer(QDialog):
    def __init__(self, parent, outputs: list[dict], title: str = "", start: int = 0):
        super().__init__(parent)
        self.outputs = [o for o in outputs if Path(o["path"]).exists()]
        self.i = min(start, max(0, len(self.outputs) - 1))
        self.setWindowTitle(tr("Xem kết quả"))
        self.setStyleSheet(f"QDialog{{background:{BG};}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.stack = QStackedWidget()
        self.view = ZoomView()
        self.stack.addWidget(self.view)
        vw = QWidget()
        vw.setStyleSheet(f"background:{BG};")
        vv = QVBoxLayout(vw)
        vv.setContentsMargins(0, 0, 0, 0)
        vv.setSpacing(0)
        if HAS_MM:
            # video vẽ trong khung đồ họa (không dùng cửa sổ gốc) → thanh điều khiển / mũi tên nổi hiện được trên video
            self.video = QGraphicsView()
            self.video.setFrameShape(QFrame.NoFrame)
            self.video.setBackgroundBrush(QColor(BG))
            self.video.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.video.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.video.setScene(QGraphicsScene(self.video))
            self.vitem = QGraphicsVideoItem()
            self.vitem.setAspectRatioMode(Qt.KeepAspectRatio)
            self.video.scene().addItem(self.vitem)
            self.vitem.nativeSizeChanged.connect(self._video_size)
            self.player = QMediaPlayer(self)
            self.player.setVideoOutput(self.vitem)
            self.aout = None
            if os.environ.get("VIDEOAI_HEADLESS") != "1":
                self.aout = QAudioOutput(self)
                self.player.setAudioOutput(self.aout)
            vv.addWidget(self.video, 1)
        else:
            self.player = None
            vv.addWidget(QLabel(tr("Không phát được video trong ứng dụng – chuột phải › Mở bằng ứng dụng khác.")))
        self.stack.addWidget(vw)
        v.addWidget(self.stack, 1)

        # thanh điều khiển video nổi ở đáy khung (hiện khi rê chuột)
        self.ctl = QWidget(self)
        self.ctl.setStyleSheet("QWidget{background:rgba(0,0,0,150);border-radius:10px;}"
                               "QLabel{background:transparent;color:#e5e7eb;font-size:11px;}")
        ch = QHBoxLayout(self.ctl)
        ch.setContentsMargins(10, 4, 10, 4)
        self.b_play = QPushButton()
        self.b_play.setFlat(True)
        self.b_play.setFixedSize(30, 26)
        self.b_play.setIcon(icon("pause", "#ffffff", 16))
        self.b_play.clicked.connect(self._toggle)
        self.seek = QSlider(Qt.Horizontal)
        self.tlabel = QLabel("")
        ch.addWidget(self.b_play)
        ch.addWidget(self.seek, 1)
        ch.addWidget(self.tlabel)
        if self.player:
            self.seek.sliderMoved.connect(lambda x: self.player.setPosition(x))
            self.player.durationChanged.connect(lambda d: self.seek.setRange(0, d))
            self.player.positionChanged.connect(self._pos)
            self.player.playbackStateChanged.connect(lambda s: self.b_play.setIcon(
                icon("pause" if s == QMediaPlayer.PlayingState else "play", "#ffffff", 16)))
        self.ctl.hide()
        self._ctl_timer = QTimer(self, singleShot=True, interval=2200, timeout=self._hide_ctl)

        # mũi tên chuyển kết quả nổi hai bên
        self.b_prev = QPushButton(self)
        self.b_prev.setIcon(icon("chev_left", "#ffffff", 22))
        self.b_next = QPushButton(self)
        self.b_next.setIcon(icon("chev_right", "#ffffff", 22))
        for b in (self.b_prev, self.b_next):
            b.setFixedSize(44, 44)
            b.setStyleSheet(OVERLAY_BTN)
            b.setCursor(Qt.PointingHandCursor)
            b.setVisible(len(self.outputs) > 1)
        self.b_prev.clicked.connect(lambda: self.show_index(self.i - 1))
        self.b_next.clicked.connect(lambda: self.show_index(self.i + 1))
        # 2 nút như cũ, nổi ở góc trên bên phải khung xem
        self.tools = QWidget(self)
        self.tools.setStyleSheet("QWidget#tb{background:rgba(0,0,0,120);border-radius:10px;}")
        self.tools.setObjectName("tb")
        self.tools.setAttribute(Qt.WA_StyledBackground, True)
        th = QHBoxLayout(self.tools)
        th.setContentsMargins(6, 6, 6, 6)
        th.setSpacing(6)
        self.b_dir = button("Mở thư mục", "chip", "folder", "#67e8f9")
        self.b_dir.clicked.connect(self._reveal)
        self.b_ext = button("Mở bằng ứng dụng khác", "chip", "eye", "#67e8f9")
        self.b_ext.clicked.connect(self._external)
        th.addWidget(self.b_dir)
        th.addWidget(self.b_ext)
        self.counter = QLabel("")           # không hiển thị (giữ để biết đang xem kết quả thứ mấy)
        self.counter.hide()

        for w in (self, self.stack, self.view.viewport(), vw):
            w.setMouseTracking(True)
        if HAS_MM:
            self.video.viewport().setMouseTracking(True)
            self.video.viewport().installEventFilter(self)
        vw.installEventFilter(self)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(lambda p: self._menu(self.view.mapTo(self, p)))
        for k, fn in (("Left", lambda: self.show_index(self.i - 1)), ("Right", lambda: self.show_index(self.i + 1)),
                      ("Space", self._toggle), ("Escape", self.close), ("0", self.view.fit)):
            QShortcut(QKeySequence(k), self, activated=fn)
        self._sized = False
        self.show_index(self.i)

    # ------------------------------------------------------------ khung theo tỷ lệ
    def _fit_window(self, s: QSize):
        """Đặt kích thước cửa sổ đúng tỷ lệ ảnh / video, lớn nhất có thể trong 90% màn hình."""
        if not s.isValid() or s.width() <= 0 or s.height() <= 0:
            return
        scr = (self.parentWidget().screen() if self.parentWidget() else None) or QGuiApplication.primaryScreen()
        g = scr.availableGeometry()
        mw, mh = int(g.width() * 0.9), int(g.height() * 0.88)
        k = min(mw / s.width(), mh / s.height())
        w, h = max(240, int(s.width() * k)), max(240, int(s.height() * k))
        self.resize(w, h)
        self.move(g.x() + (g.width() - w) // 2, g.y() + (g.height() - h) // 2)

    def _video_size(self, sz):
        """Biết kích thước thật của video → khung cửa sổ theo đúng tỷ lệ video."""
        if self.stack.currentIndex() != 1 or sz.width() <= 0 or sz.height() <= 0:
            return
        s = QSize(round(sz.width()), round(sz.height()))
        if getattr(self, "_vsize", None) != s:
            self._vsize = s
            self._fit_window(s)
        self._fit_video()

    def _fit_video(self):
        if not HAS_MM:
            return
        r = self.video.viewport().rect()
        self.vitem.setSize(QSizeF(r.width(), r.height()))
        self.video.scene().setSceneRect(QRectF(0, 0, r.width(), r.height()))
        self.video.centerOn(r.width() / 2, r.height() / 2)

    # ------------------------------------------------------------ điều khiển nổi
    def _place_overlays(self):
        w, h = self.width(), self.height()
        self.b_prev.move(12, (h - 44) // 2)
        self.b_next.move(w - 56, (h - 44) // 2)
        cw = min(w - 24, 640)
        self.ctl.setGeometry((w - cw) // 2, h - 46, cw, 36)
        self.tools.adjustSize()
        self.tools.move(max(8, w - self.tools.width() - 10), 10)
        self.tools.raise_()
        self.b_prev.raise_()
        self.b_next.raise_()
        self.ctl.raise_()

    def _show_ctl(self):
        if self.player and self.stack.currentIndex() == 1:
            self.ctl.show()
            self.ctl.raise_()
            self._ctl_timer.start()

    def _hide_ctl(self):
        if not self.ctl.underMouse() and not self.seek.isSliderDown():
            self.ctl.hide()
        else:
            self._ctl_timer.start()

    def eventFilter(self, obj, e):
        t = e.type()
        if t == e.Type.MouseMove:
            self._show_ctl()
        elif t == e.Type.MouseButtonRelease and e.button() == Qt.LeftButton:
            self._toggle()
            self._show_ctl()
        elif t == e.Type.ContextMenu:
            self._menu(obj.mapTo(self, e.pos()))
            return True
        return super().eventFilter(obj, e)

    def mouseMoveEvent(self, e):
        self._show_ctl()
        super().mouseMoveEvent(e)

    def _menu(self, pos):
        m = QMenu(self)
        a1 = QAction(icon("folder", "#67e8f9", 16), tr("Mở thư mục"), m)
        a1.triggered.connect(self._reveal)
        a2 = QAction(icon("eye", "#67e8f9", 16), tr("Mở bằng ứng dụng khác"), m)
        a2.triggered.connect(self._external)
        m.addAction(a1)
        m.addAction(a2)
        if self.stack.currentIndex() == 0:
            a3 = QAction(tr("Vừa khung"), m)
            a3.triggered.connect(self.view.fit)
            m.addAction(a3)
        m.exec(self.mapToGlobal(pos))

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
        self._fit_window(media_size(o))
        if o["kind"] == "image":
            if self.player:
                self.player.stop()
            self.ctl.hide()
            self.stack.setCurrentIndex(0)
            self.view.set_pixmap(QPixmap(o["path"]))
        else:
            self.stack.setCurrentIndex(1)
            self._vsize = None
            if self.player:
                self.player.setSource(QUrl.fromLocalFile(o["path"]))
                self.player.play()
                self._show_ctl()
        self._place_overlays()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_overlays()
        QTimer.singleShot(0, self._fit_video)

    def showEvent(self, e):
        super().showEvent(e)
        QTimer.singleShot(0, self.view.fit)

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
