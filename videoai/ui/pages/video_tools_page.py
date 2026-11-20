"""Edit Video: trình dựng video kiểu CapCut.

Bố cục: kho (trái: Đã tạo trong tools · Media · Âm thanh · Giọng nói AI · Chữ) · xem trước (giữa, khung theo đúng tỷ lệ
video đưa vào) · thuộc tính (phải) · thanh công cụ + timeline nhiều track (dưới). Phím tắt giống CapCut (nút "Phím tắt").
"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QMimeData, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDrag, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
                               QTabWidget, QVBoxLayout, QWidget)

from .gen_page import open_path
from ..theme import C, icon
from ..widgets import Card, GradientBar, button, combo, field, icon_button, label
from ..workers import run_bg
from ...core import log
from ...core.i18n import tr
from ...core.paths import data_dir, default_output_dir
from ...editor.model import (AUD_EXT, FILTERS, IMG_EXT, VID_EXT, AudioItem, Clip, History, Project, TextItem,
                             media_kind)
from ...editor.render import canvas_for, export, media_size, probe_media
from ...editor.timeline import TRACKS, TOTAL_H, Timeline, fmt_time, track_rects

L = log.get("editor")
CANVAS = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1080, 1080), "4:3": (1440, 1080), "3:4": (1080, 1440)}
AUTO = "Theo video"          # khung tự theo tỷ lệ video / ảnh đầu tiên trên timeline

# Phím tắt kiểu CapCut (bản máy tính)
SHORTCUTS = [
    ("Space", "Phát / tạm dừng"),
    ("Ctrl+B", "Cắt tại kim phát (S cũng được)"),
    ("Q", "Xóa phần bên trái kim phát của clip"),
    ("W", "Xóa phần bên phải kim phát của clip"),
    ("Delete / Backspace", "Xóa mục đang chọn"),
    ("Ctrl+C / Ctrl+X / Ctrl+V", "Sao chép / cắt / dán"),
    ("Ctrl+Z / Ctrl+Shift+Z", "Hoàn tác / làm lại (Ctrl+Y cũng được)"),
    ("← / →", "Lùi / tiến 1 khung hình"),
    ("Shift+← / Shift+→", "Lùi / tiến 1 giây"),
    ("↑ / ↓", "Về điểm chỉnh sửa trước / sau"),
    ("Home / End", "Về đầu / cuối video"),
    ("Ctrl+= / Ctrl+-", "Phóng to / thu nhỏ timeline"),
    ("Shift+Z", "Timeline vừa khung"),
    ("Ctrl+Shift+S", "Tách âm thanh khỏi clip"),
    ("Ctrl+I", "Nhập media"),
    ("Ctrl+E", "Xuất video"),
    ("Ctrl+S", "Lưu dự án"),
]
MEDIA_FILTER = "Media (*.mp4 *.mov *.webm *.mkv *.m4v *.png *.jpg *.jpeg *.webp)"
AUDIO_FILTER = "Âm thanh (*.mp3 *.wav *.m4a *.aac *.ogg *.flac)"

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    from PySide6.QtMultimediaWidgets import QVideoWidget
    HAS_MM = True
except Exception:  # pragma: no cover
    HAS_MM = False


class MediaList(QListWidget):
    """Kho media: bấm giữ chuột trái trên ảnh / video rồi kéo thẳng xuống timeline (không cần bấm đúp).
    Chọn nhiều mục (Ctrl / Shift) rồi kéo: thả cả nhóm theo thứ tự."""

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(124, 70))
        self.setResizeMode(QListWidget.Adjust)
        self.setSpacing(6)
        self.setDragEnabled(True)
        self.setMovement(QListWidget.Static)
        self.setWordWrap(True)
        self._press = None
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        it = self.itemAt(e.position().toPoint())
        self._press = (e.position().toPoint(), it) if (e.button() == Qt.LeftButton and it is not None) else None

    def mouseMoveEvent(self, e):
        if self._press and (e.buttons() & Qt.LeftButton):
            from PySide6.QtWidgets import QApplication
            pos, it = self._press
            if (e.position().toPoint() - pos).manhattanLength() >= QApplication.startDragDistance():
                self._press = None
                self._drag(it)
                return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def startDrag(self, actions):
        it = self.currentItem()
        if it:
            self._drag(it)

    def _drag(self, it):
        sel = [x for x in self.selectedItems()] if it.isSelected() else [it]
        if it not in sel:
            sel = [it]
        sel.sort(key=lambda x: self.row(x))
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(x.data(Qt.UserRole)) for x in sel])
        d = QDrag(self)
        d.setMimeData(md)
        d.setPixmap(it.icon().pixmap(100, 56))
        d.exec(Qt.CopyAction)


class Preview(QFrame):
    """Màn hình xem trước: phát clip dưới kim phát, chữ phủ lên trên, nhạc phát kèm."""

    def __init__(self):
        super().__init__()
        self.setObjectName("card")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 8)
        v.setSpacing(6)
        self.stage = QWidget()
        self.stage.setObjectName("stage")
        self.stage.setStyleSheet("QWidget#stage{background:#05081c;border-radius:3px;}")
        self.stage.setMinimumSize(320, 200)
        v.addWidget(self.stage, 1)
        self.frame = QLabel(self.stage)                  # khung hình đen đúng tỷ lệ dự án (16:9, 9:16, 1:1…)
        self.frame.setStyleSheet("background:#000;border:1px solid #2a3d8f;")
        self.img = QLabel(self.stage)
        self.img.setAlignment(Qt.AlignCenter)
        if HAS_MM:
            self.video = QVideoWidget(self.stage)
            self.player = QMediaPlayer(self)
            self.player.setVideoOutput(self.video)
            self.music = QMediaPlayer(self)
            self.aout = self.mout = None      # tạo khi phát lần đầu (tránh mở thiết bị âm thanh khi chưa cần)
        else:
            self.video = QLabel(self.stage)
            self.player = None
            self.music = None
        self.text = QLabel(self.stage)
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        self.text.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.empty = QLabel(tr("Thêm video / ảnh vào timeline để xem trước"), self.stage)
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet(f"color:{C['text-faint']};background:transparent;")
        ctl = QHBoxLayout()
        self.b_play = QPushButton()
        self.b_play.setProperty("kind", "icon")
        self.b_play.setIcon(icon("play", "#ffffff", 16))
        self.b_play.setFixedSize(36, 32)
        self.time = label("00:00.0 / 00:00.0", "muted")
        self.ratio = combo([AUTO] + list(CANVAS))
        self.ratio.setFixedWidth(118)
        self.ratio.setToolTip(tr("Khung hình: \"Theo video\" = tự lấy đúng tỷ lệ của video / ảnh đầu tiên trên timeline"))
        ctl.addStretch()
        ctl.addWidget(self.time)
        ctl.addWidget(self.b_play)
        ctl.addWidget(label("Khung", "faint"))
        ctl.addWidget(self.ratio)
        ctl.addStretch()
        v.addLayout(ctl)
        self.cur_src = None
        self.cur_music = None
        self.aspect = 16 / 9

    def ensure_audio(self):
        if self.player is None or self.aout is not None:
            return
        import os
        if os.environ.get("VIDEOAI_HEADLESS") == "1":
            return
        self.aout = QAudioOutput(self)
        self.player.setAudioOutput(self.aout)
        self.mout = QAudioOutput(self)
        self.music.setAudioOutput(self.mout)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._layout()

    def _layout(self):
        W, H = self.stage.width(), self.stage.height()
        if W / max(1, H) > self.aspect:
            h = H
            w = int(h * self.aspect)
        else:
            w = W
            h = int(w / self.aspect)
        x, y = (W - w) // 2, (H - h) // 2
        for wdg in (self.frame, self.video, self.img, self.empty):
            wdg.setGeometry(x, y, w, h)
        self.text.setGeometry(x + 10, y, w - 20, h)
        self.box = (x, y, w, h)

    def set_aspect(self, w, h):
        self.aspect = w / h
        self._layout()

    def show_text(self, items: list[TextItem], scale: float):
        if not items:
            self.text.setText("")
            return
        t = items[-1]
        size = max(9, int(t.size * scale * 0.75))
        align = {"Trên": Qt.AlignTop, "Giữa": Qt.AlignVCenter}.get(t.pos, Qt.AlignBottom) | Qt.AlignHCenter
        self.text.setAlignment(align)
        bg = "background:rgba(0,0,0,0.35);" if t.box else "background:transparent;"
        self.text.setStyleSheet(f"color:{t.color};font-size:{size}px;font-weight:800;padding:{size//3}px;{bg}")
        self.text.setText(t.text)
        self.text.adjustSize()
        x, y, w, h = self.box
        tw = min(w - 20, self.text.sizeHint().width())
        th = self.text.heightForWidth(tw) if self.text.hasHeightForWidth() else self.text.sizeHint().height()
        ty = {"Trên": y + int(h * 0.06), "Giữa": y + (h - th) // 2}.get(t.pos, y + h - th - int(h * 0.06))
        self.text.setGeometry(x + (w - tw) // 2, ty, tw, th)


class Props(QStackedWidget):
    """Khung thuộc tính theo loại đang chọn."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.item = None
        self._mute = False
        self.addWidget(self._empty())
        self.addWidget(self._clip())
        self.addWidget(self._text())
        self.addWidget(self._audio())
        self.addWidget(self._project())

    def _card(self, title, ic):
        c = Card(title, ic)
        return c

    def _empty(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addStretch()
        l = label("Chọn một clip, chữ hoặc âm thanh trên timeline để chỉnh.\n\n"
                  "Phím tắt (giống CapCut):\nSpace – phát / dừng\nCtrl+B – cắt tại kim\nQ / W – xóa phần trái / phải kim\n"
                  "Delete – xóa\nCtrl+Z / Ctrl+Shift+Z – hoàn tác / làm lại\nCtrl + lăn chuột – phóng to timeline\n"
                  "Xem đủ ở nút \"Phím tắt\"", "muted")
        l.setWordWrap(True)
        l.setAlignment(Qt.AlignCenter)
        v.addWidget(l)
        v.addStretch()
        return w

    def _ch(self, fn):
        def f(*a):
            if self._mute or self.item is None:
                return
            self.page.history.push(self.page.project)
            fn(*a)
            self.page.refresh(keep_sel=True)
        return f

    def _clip(self):
        c = self._card("Thuộc tính clip", "film")
        self.c_speed = QDoubleSpinBox()
        self.c_speed.setRange(0.25, 4.0)
        self.c_speed.setSingleStep(0.25)
        self.c_speed.setSuffix(" ×")
        self.c_speed.valueChanged.connect(self._ch(lambda v: setattr(self.item, "speed", v)))
        sp = QHBoxLayout()
        for v in (0.5, 1.0, 1.5, 2.0):
            b = QPushButton(f"{v:g}x")
            b.setProperty("kind", "chip")
            b.clicked.connect(lambda _=False, v=v: self.c_speed.setValue(v))
            sp.addWidget(b)
        self.c_vol = QSlider(Qt.Horizontal)
        self.c_vol.setRange(0, 200)
        self.c_vol.valueChanged.connect(self._ch(lambda v: setattr(self.item, "volume", v / 100)))
        self.c_scale = QSpinBox()
        self.c_scale.setRange(30, 300)
        self.c_scale.setSuffix(" %")
        self.c_scale.valueChanged.connect(self._ch(lambda v: setattr(self.item, "scale", v / 100)))
        self.c_fin = QDoubleSpinBox()
        self.c_fin.setRange(0, 5)
        self.c_fin.setSingleStep(0.25)
        self.c_fin.setSuffix(" s")
        self.c_fin.valueChanged.connect(self._ch(lambda v: setattr(self.item, "fade_in", v)))
        self.c_fout = QDoubleSpinBox()
        self.c_fout.setRange(0, 5)
        self.c_fout.setSingleStep(0.25)
        self.c_fout.setSuffix(" s")
        self.c_fout.valueChanged.connect(self._ch(lambda v: setattr(self.item, "fade_out", v)))
        self.c_filter = combo(list(FILTERS))
        self.c_filter.currentTextChanged.connect(self._ch(lambda v: setattr(self.item, "filter", v)))
        self.c_dur = QDoubleSpinBox()
        self.c_dur.setRange(0.2, 600)
        self.c_dur.setSuffix(" s")
        self.c_dur.valueChanged.connect(self._ch(lambda v: setattr(self.item, "out_s", self.item.in_s + v * self.item.speed)))
        self.c_info = label("", "faint")
        self.c_info.setWordWrap(True)
        c.add(self.c_info)
        c.add(field("Tốc độ", self.c_speed))
        c.add(sp)
        self.c_vol_box = field("Âm lượng", self.c_vol)
        c.add(self.c_vol_box)
        self.c_dur_box = field("Thời lượng ảnh", self.c_dur)
        c.add(self.c_dur_box)
        c.add(field("Thu phóng (100% = vừa khung)", self.c_scale))
        r = QHBoxLayout()
        r.addWidget(field("Hiện dần", self.c_fin))
        r.addWidget(field("Mờ dần", self.c_fout))
        c.add(r)
        c.add(field("Bộ lọc màu", self.c_filter))
        c.body_layout.addStretch()
        return c

    def _text(self):
        c = self._card("Chữ", "edit")
        self.t_text = QPlainTextEdit()
        self.t_text.setFixedHeight(80)
        self.t_text.textChanged.connect(self._ch(lambda: setattr(self.item, "text", self.t_text.toPlainText())))
        self.t_size = QSpinBox()
        self.t_size.setRange(12, 200)
        self.t_size.valueChanged.connect(self._ch(lambda v: setattr(self.item, "size", v)))
        self.t_pos = combo(["Dưới", "Giữa", "Trên"])
        self.t_pos.currentTextChanged.connect(self._ch(lambda v: setattr(self.item, "pos", v)))
        self.t_color = QPushButton()
        self.t_color.clicked.connect(self._pick_color)
        self.t_box = QCheckBox(tr("Nền mờ phía sau chữ"))
        self.t_box.toggled.connect(self._ch(lambda v: setattr(self.item, "box", v)))
        self.t_dur = QDoubleSpinBox()
        self.t_dur.setRange(0.2, 600)
        self.t_dur.setSuffix(" s")
        self.t_dur.valueChanged.connect(self._ch(lambda v: setattr(self.item, "dur", v)))
        c.add(field("Nội dung", self.t_text))
        r = QHBoxLayout()
        r.addWidget(field("Cỡ chữ", self.t_size))
        r.addWidget(field("Màu", self.t_color))
        c.add(r)
        c.add(field("Vị trí", self.t_pos))
        c.add(field("Thời lượng", self.t_dur))
        c.add(self.t_box)
        c.body_layout.addStretch()
        return c

    def _pick_color(self):
        if not isinstance(self.item, TextItem):
            return
        col = QColorDialog.getColor(QColor(self.item.color), self, tr("Màu chữ"))
        if col.isValid():
            self.page.history.push(self.page.project)
            self.item.color = col.name()
            self.page.refresh(keep_sel=True)

    def _audio(self):
        c = self._card("Âm thanh", "music")
        self.a_info = label("", "faint")
        self.a_info.setWordWrap(True)
        self.a_vol = QSlider(Qt.Horizontal)
        self.a_vol.setRange(0, 200)
        self.a_vol.valueChanged.connect(self._ch(lambda v: setattr(self.item, "volume", v / 100)))
        self.a_fin = QDoubleSpinBox()
        self.a_fin.setRange(0, 10)
        self.a_fin.setSuffix(" s")
        self.a_fin.valueChanged.connect(self._ch(lambda v: setattr(self.item, "fade_in", v)))
        self.a_fout = QDoubleSpinBox()
        self.a_fout.setRange(0, 10)
        self.a_fout.setSuffix(" s")
        self.a_fout.valueChanged.connect(self._ch(lambda v: setattr(self.item, "fade_out", v)))
        self.a_track = combo(["Nhạc", "Lồng tiếng"])
        self.a_track.currentTextChanged.connect(self._ch(lambda v: setattr(self.item, "track", "music" if v == "Nhạc" else "voice")))
        c.add(self.a_info)
        c.add(field("Âm lượng", self.a_vol))
        r = QHBoxLayout()
        r.addWidget(field("Hiện dần", self.a_fin))
        r.addWidget(field("Mờ dần", self.a_fout))
        c.add(r)
        c.add(field("Track", self.a_track))
        b = button("Kéo dài nhạc tới hết video", "chip", "music", "#6ee7b7")
        b.clicked.connect(self._fit_music)
        c.add(b)
        c.body_layout.addStretch()
        return c

    def _fit_music(self):
        a = self.item
        if isinstance(a, AudioItem):
            self.page.history.push(self.page.project)
            need = self.page.project.video_duration - a.start
            a.out_s = min(a.src_dur, a.in_s + max(0.2, need))
            self.page.refresh(keep_sel=True)

    def _project(self):
        c = self._card("Dự án", "sliders")
        self.p_name = QLineEdit()
        self.p_name.textChanged.connect(lambda v: setattr(self.page.project, "name", v))
        self.p_fps = combo(["24", "25", "30", "60"])
        self.p_fps.currentTextChanged.connect(lambda v: setattr(self.page.project, "fps", int(v)))
        c.add(field("Tên dự án", self.p_name))
        c.add(field("Khung hình / giây", self.p_fps))
        c.body_layout.addStretch()
        return c

    def show_item(self, it):
        self.item = it
        self._mute = True
        if isinstance(it, Clip):
            self.setCurrentIndex(1)
            self.c_info.setText(f"{Path(it.src).name}\n{tr('Đoạn')} {it.in_s:.1f}s → {it.out_s:.1f}s · {it.dur:.1f}s")
            self.c_speed.setValue(it.speed)
            self.c_vol.setValue(int(it.volume * 100))
            self.c_scale.setValue(int(it.scale * 100))
            self.c_fin.setValue(it.fade_in)
            self.c_fout.setValue(it.fade_out)
            self.c_filter.setCurrentText(it.filter)
            self.c_dur.setValue(it.out_s - it.in_s)
            self.c_vol_box.setVisible(it.kind == "video")
            self.c_dur_box.setVisible(it.kind == "image")
        elif isinstance(it, TextItem):
            self.setCurrentIndex(2)
            if self.t_text.toPlainText() != it.text:
                self.t_text.setPlainText(it.text)
            self.t_size.setValue(it.size)
            self.t_pos.setCurrentText(it.pos)
            self.t_color.setText(it.color)
            self.t_color.setStyleSheet(f"background:{it.color};color:#000;font-weight:700;")
            self.t_box.setChecked(it.box)
            self.t_dur.setValue(it.dur)
        elif isinstance(it, AudioItem):
            self.setCurrentIndex(3)
            self.a_info.setText(f"{Path(it.src).name}\n{tr('Bắt đầu')} {fmt_time(it.start)} · {it.dur:.1f}s")
            self.a_vol.setValue(int(it.volume * 100))
            self.a_fin.setValue(it.fade_in)
            self.a_fout.setValue(it.fade_out)
            self.a_track.setCurrentText("Nhạc" if it.track == "music" else "Lồng tiếng")
        else:
            self.setCurrentIndex(0)
        self._mute = False


class VideoToolsPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.db = ctx.db
        self.history = History()
        saved = self.db.get_setting("editor_current")
        try:
            self.project = Project.from_json(saved) if saved else Project()
        except Exception:
            self.project = Project()
        self.playing = False
        self._play_t0 = 0.0
        self._play_base = 0.0
        self._build()
        self.refresh()
        self._shortcuts()
        self.tick = QTimer(self)
        self.tick.setInterval(40)
        self.tick.timeout.connect(self._on_tick)
        self.autosave = QTimer(self)
        self.autosave.setInterval(4000)
        self.autosave.timeout.connect(lambda: self.db.set_setting("editor_current", self.project.to_json()))
        self.autosave.start()

    # ================================================================ giao diện
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label("Edit Video", "h1"))
        self.proj_lbl = label("", "muted")
        top.addWidget(self.proj_lbl)
        for ic, tip, fn in (("undo", "Hoàn tác (Ctrl+Z)", self.undo), ("redo", "Làm lại (Ctrl+Y)", self.redo)):
            b = icon_button(ic, tip, "#b9c3ee")
            b.setFixedSize(34, 30)
            b.clicked.connect(fn)
            top.addWidget(b)
        top.addStretch()
        for text, ic, fn in (("Mới", "plus", self.new_project), ("Mở", "folder", self.open_project),
                             ("Lưu", "save", self.save_project), ("Công cụ nhanh", "scissors", self.quick_tools),
                             ("Phím tắt", "list", self.show_shortcuts)):
            b = button(text, "chip", ic, "#67e8f9")
            b.clicked.connect(fn)
            top.addWidget(b)
        b_cc = button("Xuất sang CapCut", None, "upload", "#67e8f9")
        b_cc.clicked.connect(self.export_capcut)
        self.b_export = button("Xuất video", "primary", "download")
        self.b_export.clicked.connect(self.export_video)
        top.addWidget(b_cc)
        top.addWidget(self.b_export)
        root.addLayout(top)

        # các khu (kho · xem trước · thuộc tính · timeline) kéo viền để đổi kích thước, nhớ lại lần sau
        from PySide6.QtWidgets import QSplitter
        self.hsplit = mid = QSplitter(Qt.Horizontal)
        self.vsplit = QSplitter(Qt.Vertical)
        for sp in (self.hsplit, self.vsplit):
            sp.setChildrenCollapsible(False)
            sp.setHandleWidth(8)
            sp.setStyleSheet("QSplitter::handle{background:transparent;}"
                             f"QSplitter::handle:hover{{background:{C['accent']};border-radius:3px;}}")
        self.vsplit.addWidget(self.hsplit)
        root.addWidget(self.vsplit, 1)
        # ---- kho media
        left = QFrame()
        left.setObjectName("card")
        left.setMinimumWidth(240)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 8, 8)
        tabs = self.left_tabs = QTabWidget()
        tabs.addTab(self._library_tab(), tr("Đã tạo"))
        tabs.addTab(self._media_tab(), tr("Media"))
        tabs.addTab(self._audio_tab(), tr("Âm thanh"))
        tabs.addTab(self._tts_tab(), tr("Giọng nói AI"))
        tabs.addTab(self._text_tab(), tr("Chữ"))
        tabs.currentChanged.connect(lambda i: tabs.widget(i) is self.lib_tab and self.reload_library())
        tabs.setStyleSheet("QTabBar::tab{padding:6px 7px;margin-right:1px;}")
        tabs.tabBar().setExpanding(False)
        lv.addWidget(tabs)
        mid.addWidget(left)
        # ---- xem trước
        self.preview = Preview()
        self.preview.b_play.clicked.connect(self.toggle_play)
        self.preview.ratio.currentIndexChanged.connect(self._set_canvas)
        self.preview.setMinimumWidth(320)
        mid.addWidget(self.preview)
        # ---- thuộc tính
        self.props = Props(self)
        self.props.setMinimumWidth(220)
        mid.addWidget(self.props)

        # ---- timeline
        tl = QFrame()
        tl.setObjectName("card")
        tlv = QVBoxLayout(tl)
        tlv.setContentsMargins(8, 6, 8, 6)
        tlv.setSpacing(4)
        bar = QHBoxLayout()
        for text, ic, fn, tip in (("Cắt", "scissors", self.split, "Cắt tại kim phát (Ctrl+B)"),
                                  ("Xóa", "trash", self.delete, "Xóa mục đang chọn (Delete)"),
                                  ("Nhân đôi", "plus", self.duplicate, "Nhân đôi clip đang chọn"),
                                  ("Thêm chữ", "edit", lambda: self.add_text("Phụ đề"), "Thêm chữ tại kim phát"),
                                  ("Thêm nhạc", "music", self.import_audio, "Thêm nhạc tại kim phát"),
                                  ("Tách âm thanh", "music", self.detach_audio, "Tách tiếng của clip ra track riêng")):
            b = button(text, "chip", ic, "#67e8f9" if ic != "trash" else "#fb7185")
            b.setToolTip(tr(tip))
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        self.dur_lbl = label("", "faint")
        bar.addWidget(self.dur_lbl)
        bar.addWidget(QLabel())
        zi = QLabel()
        zi.setPixmap(icon("zoom", "#7f8bc4", 14).pixmap(14, 14))
        bar.addWidget(zi)
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(8, 300)
        self.zoom.setValue(60)
        self.zoom.setFixedWidth(150)
        self.zoom.valueChanged.connect(lambda v: self.timeline.set_zoom(v))
        bar.addWidget(self.zoom)
        tlv.addLayout(bar)
        row = QHBoxLayout()
        row.setSpacing(0)
        heads = QWidget()
        heads.setFixedWidth(92)
        heads.setFixedHeight(TOTAL_H)
        tr_ = track_rects(0)
        for key, name, h in TRACKS:
            y, hh = tr_[key]
            l = QLabel(tr(name), heads)
            l.setGeometry(4, y, 88, hh)
            l.setStyleSheet(f"color:{C['text-muted']};font-size:11px;")
        row.addWidget(heads, 0, Qt.AlignTop)
        self.timeline = Timeline()
        self.timeline.seek.connect(self._seek)
        self.timeline.selected.connect(self._select)
        self.timeline.about_to_change.connect(lambda: self.history.push(self.project))
        self.timeline.changed.connect(lambda: self.refresh(keep_sel=True))
        self.timeline.dropped_media.connect(self._dropped)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.timeline)
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(TOTAL_H + 14)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        row.addWidget(self.scroll, 1)
        tlv.addLayout(row)
        self.vsplit.addWidget(tl)
        mid.setStretchFactor(1, 1)
        self.vsplit.setStretchFactor(0, 1)
        saved = self.db.get_setting("editor_splits") or {}
        try:
            if saved.get("h"):
                self.hsplit.setSizes([int(x) for x in saved["h"]])
            else:
                self.hsplit.setSizes([340, 900, 290])
            if saved.get("v"):
                self.vsplit.setSizes([int(x) for x in saved["v"]])
        except Exception:
            pass
        for sp in (self.hsplit, self.vsplit):
            sp.splitterMoved.connect(lambda *_: self.db.set_setting(
                "editor_splits", {"h": self.hsplit.sizes(), "v": self.vsplit.sizes()}))
        self._sync_ratio_combo()
        self.preview.set_aspect(self.project.width, self.project.height)

    # ---- Đã tạo: mọi ảnh / video đã tạo trong tools (mọi nền tảng)
    def _library_tab(self):
        w = self.lib_tab = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        r = QHBoxLayout()
        self.lib_kind = combo(["Tất cả", "Video", "Ảnh"])
        self.lib_src = QComboBox()
        self.lib_src.setCursor(Qt.PointingHandCursor)
        for cb in (self.lib_kind, self.lib_src):
            cb.currentIndexChanged.connect(lambda _=0: self.reload_library())
        r.addWidget(self.lib_kind)
        r.addWidget(self.lib_src, 1)
        b_re = icon_button("retry", tr("Làm mới"), "#67e8f9")
        b_re.setFixedSize(32, 30)
        b_re.clicked.connect(self.reload_library)
        r.addWidget(b_re)
        v.addLayout(r)
        self.lib_info = label("", "faint")
        self.lib_info.setWordWrap(True)
        v.addWidget(self.lib_info)
        self.lib_list = MediaList()
        self.lib_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.lib_list.itemDoubleClicked.connect(lambda it: self.add_media(it.data(Qt.UserRole)))
        v.addWidget(self.lib_list, 1)
        b_add = button("Đưa mục đã chọn xuống timeline", "primary", "plus")
        b_add.clicked.connect(self._lib_add_selected)
        v.addWidget(b_add)
        self._lib_sig = None
        return w

    def _library_rows(self) -> list[dict]:
        return self.db.query(
            "SELECT o.path, o.kind, o.created_at, b.page, j.prompt FROM outputs o JOIN jobs j ON j.id=o.job_id"
            " JOIN batches b ON b.id=j.batch_id ORDER BY o.created_at DESC LIMIT 1500")

    def reload_library(self):
        from ...core.platforms import PAGE_BY_KEY
        rows = [r for r in self._library_rows() if Path(r["path"]).exists()]
        pages = []
        for r in rows:
            if r["page"] not in pages:
                pages.append(r["page"])
        cur_src = self.lib_src.currentData()
        self.lib_src.blockSignals(True)
        self.lib_src.clear()
        self.lib_src.addItem(tr("Mọi chức năng"), "")
        for pg in pages:
            self.lib_src.addItem(tr(PAGE_BY_KEY[pg].label) if pg in PAGE_BY_KEY else pg, pg)
        self.lib_src.setCurrentIndex(max(0, self.lib_src.findData(cur_src or "")))
        self.lib_src.blockSignals(False)
        kind = ("", "video", "image")[self.lib_kind.currentIndex()]
        src = self.lib_src.currentData() or ""
        show = [r for r in rows if (not kind or media_kind(r["path"]) == kind) and (not src or r["page"] == src)]
        sig = tuple(r["path"] for r in show)
        if sig == self._lib_sig:
            return
        self._lib_sig = sig
        self.lib_list.clear()
        for r in show:
            it = QListWidgetItem("")
            it.setData(Qt.UserRole, r["path"])
            pg = PAGE_BY_KEY.get(r["page"])
            it.setToolTip(f"{tr(pg.label) if pg else r['page']}\n{(r['prompt'] or '')[:160]}\n{r['path']}")
            self._set_thumb(it, r["path"])
            self.lib_list.addItem(it)
        self.lib_info.setText(tr("Kéo thả hoặc bấm đúp để đưa xuống timeline") + f" · {len(show)} " + tr("tệp")
                              if show else tr("Chưa có ảnh / video nào được tạo trong tools."))

    def _set_thumb(self, it, pth: str):
        if media_kind(pth) == "image":
            it.setIcon(QIcon(QPixmap(pth).scaled(124, 70, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
            return
        it.setIcon(icon("film", "#c4a5ff", 40))
        from ...editor.timeline import _want, thumb_pixmap
        _want("thumb", pth)

        def _set(it=it, pth=pth, tries=[0]):
            try:
                pm = thumb_pixmap(pth)
                if pm is not None and not pm.isNull():
                    it.setIcon(QIcon(pm.scaled(124, 70, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
                elif tries[0] < 10:
                    tries[0] += 1
                    QTimer.singleShot(800, _set)
            except RuntimeError:                                 # mục đã bị xóa khỏi danh sách
                pass
        QTimer.singleShot(600, _set)

    def _lib_add_selected(self):
        its = self.lib_list.selectedItems()
        if not its:
            return self.ctx.toast("info", tr("Chọn (bấm, giữ Ctrl để chọn nhiều) ảnh / video cần đưa xuống timeline."))
        for it in its:
            self.add_media(it.data(Qt.UserRole), refresh=False)
        self.refresh(keep_sel=True)

    # ---- Giọng nói AI: VieNeu-TTS v3 Turbo
    def _tts_tab(self):
        from ...services import tts
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        v.addWidget(label("VieNeu-TTS v3 Turbo · giọng Việt 48 kHz, chạy trên máy (CPU)", "faint"))
        self.tts_text = QPlainTextEdit()
        self.tts_text.setPlaceholderText(tr("Nhập văn bản cần đọc…"))
        v.addWidget(self.tts_text, 1)
        self.tts_voice = QComboBox()
        self.tts_voice.setCursor(Qt.PointingHandCursor)
        for lab, name in tts.voices():
            self.tts_voice.addItem(lab, name)
        if self.tts_voice.count() == 0:
            self.tts_voice.addItem(tr("Giọng mặc định"), "")
        last = self.db.get_setting("tts_voice", "")
        self.tts_voice.setCurrentIndex(max(0, self.tts_voice.findData(last)))
        v.addWidget(field("Giọng đọc", self.tts_voice))
        self.tts_track = combo(["Lồng tiếng", "Nhạc"])
        v.addWidget(field("Đưa vào track", self.tts_track))
        self.tts_state = label("" if tts.available() else tr("Bản cài này chưa có VieNeu-TTS – build lại bằng 'build Windows.bat'."),
                               "faint")
        self.tts_state.setWordWrap(True)
        v.addWidget(self.tts_state)
        self.b_tts = button("Tạo giọng nói và đưa vào timeline", "primary", "music")
        self.b_tts.clicked.connect(self.make_tts)
        v.addWidget(self.b_tts)
        return w

    def make_tts(self):
        from ...services import tts
        text = self.tts_text.toPlainText().strip()
        if not text:
            return self.ctx.toast("info", tr("Nhập văn bản cần đọc."))
        voice = self.tts_voice.currentData() or ""
        self.db.set_setting("tts_voice", voice)
        out = tts.output_path(text, voice)
        track = "voice" if self.tts_track.currentIndex() == 0 else "music"
        at = self.timeline.playhead
        self.b_tts.setEnabled(False)
        self.b_tts.setText(tr("Đang tạo giọng nói…"))

        def job(progress):
            return tts.synthesize(text, voice, out, lambda m: progress(0, m))

        def end():
            self.b_tts.setEnabled(True)
            self.b_tts.setText(tr("Tạo giọng nói và đưa vào timeline"))

        def done(path):
            end()
            self.tts_state.setText(tr("Đã tạo") + f": {Path(path).name}")
            self.add_audio(path, track, at)
            self.ctx.toast("ok", tr("Đã tạo giọng nói và đưa vào timeline"))

        def err(m):
            end()
            self.tts_state.setText(m[:300])
            self.ctx.toast("error", m[:300])
        run_bg(job, on_done=done, on_error=err, on_progress=lambda _p, m: m and self.tts_state.setText(tr(m)))

    def _media_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        b = button("Nhập video / ảnh", "primary", "plus")
        b.clicked.connect(self.import_media_dialog)
        b2 = button("Lấy kết quả vừa tạo từ Flow", "chip", "video", "#c4a5ff")
        b2.clicked.connect(self.import_from_flow)
        v.addWidget(b)
        v.addWidget(b2)
        v.addWidget(label("Bấm đúp hoặc kéo vào timeline để thêm.", "faint"))
        self.media_list = MediaList()
        self.media_list.itemDoubleClicked.connect(lambda it: self.add_media(it.data(Qt.UserRole)))
        v.addWidget(self.media_list, 1)
        return w

    def _audio_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        b = button("Nhập nhạc / âm thanh", "primary", "plus")
        b.clicked.connect(self.import_audio)
        v.addWidget(b)
        v.addWidget(label("Bấm đúp để thêm vào track Nhạc tại kim phát.", "faint"))
        self.audio_list = QListWidget()
        self.audio_list.itemDoubleClicked.connect(lambda it: self.add_audio(it.data(Qt.UserRole), "music"))
        v.addWidget(self.audio_list, 1)
        b3 = button("Thêm làm lồng tiếng", "chip", "music", "#fdba74")
        b3.clicked.connect(lambda: self.audio_list.currentItem() and self.add_audio(self.audio_list.currentItem().data(Qt.UserRole), "voice"))
        v.addWidget(b3)
        return w

    def _text_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        v.addWidget(label("Thêm chữ tại kim phát:", "faint"))
        for name, desc in (("Tiêu đề", "Chữ lớn ở giữa"), ("Phụ đề", "Chữ dưới, có nền mờ"), ("Chú thích trên", "Chữ nhỏ phía trên")):
            b = QPushButton(f"{tr(name)}\n{tr(desc)}")
            b.setStyleSheet(f"QPushButton{{text-align:left;padding:10px;background:{C['surface-2']};border:1px solid {C['border']};"
                            f"border-radius:5px;}}QPushButton:hover{{border-color:{C['accent']};}}")
            b.clicked.connect(lambda _=False, n=name: self.add_text(n))
            v.addWidget(b)
        b = button("Nhập phụ đề từ tệp SRT", "chip", "upload", "#67e8f9")
        b.clicked.connect(self.import_srt)
        v.addWidget(b)
        v.addStretch()
        return w

    def _shortcuts(self):
        """Phím tắt giống CapCut. Không bắt phím khi đang gõ trong ô chữ."""
        keys = [("Space", self.toggle_play), ("Ctrl+B", self.split), ("S", self.split),
                ("Q", lambda: self.trim("left")), ("W", lambda: self.trim("right")),
                ("Delete", self.delete), ("Backspace", self.delete),
                ("Ctrl+C", self.copy), ("Ctrl+X", self.cut), ("Ctrl+V", self.paste), ("Ctrl+D", self.duplicate),
                ("Ctrl+Z", self.undo), ("Ctrl+Shift+Z", self.redo), ("Ctrl+Y", self.redo),
                ("Left", lambda: self.step(-1 / max(1, self.project.fps))), ("Right", lambda: self.step(1 / max(1, self.project.fps))),
                ("Shift+Left", lambda: self.step(-1.0)), ("Shift+Right", lambda: self.step(1.0)),
                ("Up", lambda: self.jump_edit(-1)), ("Down", lambda: self.jump_edit(1)),
                ("Home", lambda: self.seek_to(0.0)), ("End", lambda: self.seek_to(self.project.duration)),
                ("Ctrl+=", lambda: self.zoom_by(1.25)), ("Ctrl++", lambda: self.zoom_by(1.25)), ("Ctrl+-", lambda: self.zoom_by(0.8)),
                ("Shift+Z", self.zoom_fit), ("Ctrl+Shift+S", self.detach_audio),
                ("Ctrl+I", self.import_media_dialog), ("Ctrl+E", self.export_video), ("Ctrl+S", self.save_project)]
        self._sc = []
        for k, fn in keys:
            sc = QShortcut(QKeySequence(k), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda fn=fn: None if self._typing() else fn())
            self._sc.append(sc)

    def _typing(self) -> bool:
        from PySide6.QtWidgets import QApplication, QAbstractSpinBox
        w = QApplication.focusWidget()
        return isinstance(w, (QLineEdit, QPlainTextEdit, QAbstractSpinBox)) or (
            w is not None and w.inherits("QTextEdit"))

    def show_shortcuts(self):
        d = QDialog(self)
        d.setWindowTitle(tr("Phím tắt Edit Video (giống CapCut)"))
        d.resize(520, 560)
        v = QVBoxLayout(d)
        from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
        t = QTableWidget(len(SHORTCUTS), 2)
        t.setHorizontalHeaderLabels([tr("Phím"), tr("Tác dụng")])
        t.verticalHeader().hide()
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        for i, (k, desc) in enumerate(SHORTCUTS):
            t.setItem(i, 0, QTableWidgetItem(k))
            t.setItem(i, 1, QTableWidgetItem(tr(desc)))
        v.addWidget(t)
        b = button("Đóng", "chip", "x", "#fb7185")
        b.clicked.connect(d.accept)
        v.addWidget(b, 0, Qt.AlignRight)
        d.exec()

    # ---- thao tác kiểu CapCut
    def seek_to(self, t: float):
        t = max(0.0, min(self.project.duration, t))
        self.timeline.playhead = t
        self.timeline.update()
        self._seek(t)
        x = self.timeline.x_of(t)
        sb = self.scroll.horizontalScrollBar()
        vw = self.scroll.viewport().width()
        if not (sb.value() + 40 <= x <= sb.value() + vw - 40):
            sb.setValue(int(max(0, x - vw / 2)))

    def step(self, dt: float):
        if self.playing:
            self.toggle_play()
        self.seek_to(self.timeline.playhead + dt)

    def jump_edit(self, direction: int):
        t = self.timeline.playhead
        pts = self.project.edit_points()
        if direction < 0:
            cand = [p for p in pts if p < t - 1e-3]
            self.seek_to(cand[-1] if cand else 0.0)
        else:
            cand = [p for p in pts if p > t + 1e-3]
            self.seek_to(cand[0] if cand else self.project.duration)

    def zoom_by(self, k: float):
        self.zoom.setValue(int(max(self.zoom.minimum(), min(self.zoom.maximum(), self.zoom.value() * k))))

    def zoom_fit(self):
        dur = max(1.0, self.project.duration)
        self.zoom.setValue(int(max(self.zoom.minimum(), min(self.zoom.maximum(), (self.scroll.viewport().width() - 60) / dur))))
        self.scroll.horizontalScrollBar().setValue(0)

    def trim(self, side: str):
        self.history.push(self.project)
        if self.project.trim(self.timeline.playhead, self.timeline.sel_id, side):
            if side == "left":                                  # kim phát về đầu phần còn lại (giống CapCut)
                it = self.project.find(self.timeline.sel_id) if self.timeline.sel_id else None
                if it is None or isinstance(it, Clip):
                    hit = self.project.clip_at(self.timeline.playhead)
                    if hit:
                        self.timeline.playhead = self.project.clip_starts()[hit[0]]
                else:
                    self.timeline.playhead = it.start
            self.refresh(keep_sel=True)
        else:
            self.history.undo_stack.pop()

    def copy(self):
        import copy as _copy
        it = self.project.find(self.timeline.sel_id) if self.timeline.sel_id else None
        if it is not None:
            self._clip_board = _copy.deepcopy(it)
            self.ctx.toast("info", tr("Đã sao chép"))

    def cut(self):
        if self.timeline.sel_id:
            self.copy()
            self.delete()

    def paste(self):
        import copy as _copy
        src = getattr(self, "_clip_board", None)
        if src is None:
            return
        from ...editor.model import _id
        self.history.push(self.project)
        b = _copy.deepcopy(src)
        b.id = _id()
        t = self.timeline.playhead
        if isinstance(b, Clip):
            starts = self.project.clip_starts()
            idx = next((i + 1 for i in range(len(starts)) if starts[i] <= t < starts[i] + self.project.clips[i].dur),
                       len(self.project.clips))
            self.project.clips.insert(idx, b)
        elif isinstance(b, TextItem):
            b.start = t
            self.project.texts.append(b)
        else:
            b.start = t
            self.project.audios.append(b)
        self.timeline.sel_id = b.id
        self.refresh(keep_sel=True)

    # ================================================================ làm mới
    def refresh(self, keep_sel: bool = False):
        self.timeline.set_project(self.project)
        if not keep_sel:
            self.timeline.sel_id = None
        it = self.project.find(self.timeline.sel_id) if self.timeline.sel_id else None
        self.props.show_item(it)
        if it is None:
            self.props.p_name.setText(self.project.name)
            self.props.setCurrentIndex(0)
        self.proj_lbl.setText(f"· {self.project.name}")
        self.dur_lbl.setText(tr("Tổng") + f" {fmt_time(self.project.duration)}  ")
        self._media_refresh()
        self._render_frame()

    def _media_refresh(self):
        have = {self.media_list.item(i).data(Qt.UserRole) for i in range(self.media_list.count())}
        for pth in self.project.media:
            if pth in have or not Path(pth).exists():
                continue
            k = media_kind(pth)
            if k == "audio":
                it = QListWidgetItem(icon("music", "#6ee7b7", 18), Path(pth).name)
                it.setData(Qt.UserRole, pth)
                if pth not in {self.audio_list.item(i).data(Qt.UserRole) for i in range(self.audio_list.count())}:
                    self.audio_list.addItem(it)
                continue
            it = QListWidgetItem(Path(pth).name[:22])
            it.setData(Qt.UserRole, pth)
            it.setToolTip(pth)
            if k == "image":
                it.setIcon(QIcon(QPixmap(pth).scaled(124, 70, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
            else:
                it.setIcon(icon("film", "#c4a5ff", 40))
                from ...editor.timeline import _want, thumb_pixmap
                _want("thumb", pth)

                def _set(it=it, pth=pth, tries=[0]):
                    pm = thumb_pixmap(pth)
                    if pm is not None and not pm.isNull():
                        it.setIcon(QIcon(pm.scaled(124, 70, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))
                    elif tries[0] < 10:
                        tries[0] += 1
                        QTimer.singleShot(800, _set)
                QTimer.singleShot(800, _set)
            self.media_list.addItem(it)

    # ================================================================ thêm media
    def import_media(self, paths: list[str], add_to_timeline: bool = False):
        for pth in paths:
            if pth not in self.project.media:
                self.project.media.append(pth)
            if add_to_timeline and media_kind(pth) != "audio":
                self.add_media(pth, refresh=False)
        self.refresh(keep_sel=True)

    def import_media_dialog(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Nhập video / ảnh"), "", MEDIA_FILTER)
        if fs:
            self.import_media(fs)

    def import_from_flow(self):
        rows = self.db.query("SELECT o.path FROM outputs o JOIN jobs j ON j.id=o.job_id JOIN batches b ON b.id=j.batch_id"
                             " WHERE b.platform='flow' ORDER BY o.created_at DESC LIMIT 60")
        paths = [r["path"] for r in rows if Path(r["path"]).exists()]
        if not paths:
            self.ctx.toast("info", tr("Chưa có kết quả nào từ Tạo ảnh / Tạo Video Flow."))
            return
        self.import_media(list(reversed(paths)))
        self.ctx.toast("ok", tr("Đã lấy") + f" {len(paths)} " + tr("tệp từ kết quả Flow"))

    def import_audio(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Nhập âm thanh"), "", AUDIO_FILTER)
        for f in fs:
            if f not in self.project.media:
                self.project.media.append(f)
        if len(fs) == 1:
            self.add_audio(fs[0], "music")
        else:
            self.refresh(keep_sel=True)

    def add_media(self, pth: str, at_time: float | None = None, refresh: bool = True):
        info = probe_media(pth)
        if info["kind"] == "audio":
            self.add_audio(pth, "music", at_time)
            return
        self.history.push(self.project)
        c = Clip(src=pth, kind=info["kind"], in_s=0.0, out_s=info["dur"], src_dur=info["dur"], has_audio=info["audio"])
        idx = len(self.project.clips)
        if at_time is not None:
            acc = 0.0
            for i, o in enumerate(self.project.clips):
                if at_time < acc + o.dur / 2:
                    idx = i
                    break
                acc += o.dur
        self.project.clips.insert(idx, c)
        if pth not in self.project.media:
            self.project.media.append(pth)
        if idx == 0 and self._auto_canvas():
            self.ctx.toast("info", tr("Khung hình theo video") + f": {self.project.width}×{self.project.height}")
        self.timeline.sel_id = c.id
        if refresh:
            self.refresh(keep_sel=True)

    def add_audio(self, pth: str, track: str = "music", at_time: float | None = None):
        info = probe_media(pth)
        self.history.push(self.project)
        start = self.timeline.playhead if at_time is None else at_time
        room = max(1.0, (self.project.video_duration or info["dur"]) - start)
        a = AudioItem(src=pth, track=track, start=start, in_s=0.0, out_s=min(info["dur"], room) if track == "music" else info["dur"],
                      src_dur=info["dur"], volume=0.5 if track == "music" else 1.0)
        self.project.audios.append(a)
        if pth not in self.project.media:
            self.project.media.append(pth)
        self.timeline.sel_id = a.id
        self.refresh(keep_sel=True)

    def _dropped(self, pth, t):
        if media_kind(pth) == "audio":
            self.add_audio(pth, "music", t)
        else:
            self.add_media(pth, t)

    def add_text(self, preset: str = "Phụ đề"):
        self.history.push(self.project)
        cfg = {"Tiêu đề": dict(size=96, pos="Giữa", box=False, text=tr("Tiêu đề")),
               "Chú thích trên": dict(size=40, pos="Trên", box=True, text=tr("Chú thích"))}.get(
            preset, dict(size=56, pos="Dưới", box=True, text=tr("Nhập phụ đề")))
        t = TextItem(start=self.timeline.playhead, dur=3.0, **cfg)
        self.project.texts.append(t)
        self.timeline.sel_id = t.id
        self.refresh(keep_sel=True)
        self.props.t_text.setFocus()
        self.props.t_text.selectAll()

    def import_srt(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Chọn tệp SRT"), "", "Phụ đề (*.srt)")
        if not f:
            return
        from ...media.srt import parse_srt
        cues = parse_srt(Path(f).read_text(encoding="utf-8-sig", errors="replace"))
        self.history.push(self.project)
        for cue in cues:
            self.project.texts.append(TextItem(text=cue["text"], start=cue["start"], dur=max(0.2, cue["end"] - cue["start"])))
        self.refresh(keep_sel=True)
        self.ctx.toast("ok", tr("Đã thêm") + f" {len(cues)} " + tr("dòng phụ đề"))

    # ================================================================ sửa
    def split(self):
        self.history.push(self.project)
        if self.project.split(self.timeline.playhead, self.timeline.sel_id):
            self.refresh(keep_sel=True)
        else:
            self.history.undo_stack.pop()

    def delete(self):
        if self.timeline.sel_id:
            self.history.push(self.project)
            self.project.delete(self.timeline.sel_id)
            self.timeline.sel_id = None
            self.refresh()

    def duplicate(self):
        import copy
        it = self.project.find(self.timeline.sel_id) if self.timeline.sel_id else None
        if not it:
            return
        self.history.push(self.project)
        b = copy.deepcopy(it)
        from ...editor.model import _id
        b.id = _id()
        if isinstance(it, Clip):
            self.project.clips.insert(self.project.clips.index(it) + 1, b)
        elif isinstance(it, TextItem):
            b.start = it.start + it.dur
            self.project.texts.append(b)
        else:
            b.start = it.start + it.dur
            self.project.audios.append(b)
        self.timeline.sel_id = b.id
        self.refresh(keep_sel=True)

    def detach_audio(self):
        if not self.timeline.sel_id:
            return
        self.history.push(self.project)
        a = self.project.detach_audio(self.timeline.sel_id)
        if a:
            self.timeline.sel_id = a.id
            self.refresh(keep_sel=True)
        else:
            self.history.undo_stack.pop()
            self.ctx.toast("info", tr("Chọn một clip video có tiếng để tách âm thanh."))

    def undo(self):
        p = self.history.undo(self.project)
        if p:
            self.project = p
            self.refresh(keep_sel=True)

    def redo(self):
        p = self.history.redo(self.project)
        if p:
            self.project = p
            self.refresh(keep_sel=True)

    def _select(self, it):
        self.props.show_item(it)
        if it is None:
            self.props.p_name.setText(self.project.name)

    def _sync_ratio_combo(self):
        r = self.preview.ratio
        r.blockSignals(True)
        if self.project.auto_canvas:
            r.setCurrentIndex(0)
        else:
            keys = list(CANVAS)
            k = next((i for i, key in enumerate(keys) if CANVAS[key] == (self.project.width, self.project.height)), None)
            r.setCurrentIndex(k + 1 if k is not None else 0)
        r.blockSignals(False)
        self.preview.set_aspect(self.project.width, self.project.height)

    def _set_canvas(self, idx: int):
        self.history.push(self.project)
        if idx <= 0:                                           # Theo video
            self.project.auto_canvas = True
            self._auto_canvas(force=True)
        else:
            self.project.auto_canvas = False
            self.project.width, self.project.height = CANVAS[list(CANVAS)[idx - 1]]
        self.preview.set_aspect(self.project.width, self.project.height)
        self._render_frame()

    def _auto_canvas(self, force: bool = False):
        """Khung xem trước + khung xuất theo đúng tỷ lệ video / ảnh đầu tiên trên timeline (16:9, 9:16, 1:1…)."""
        if not self.project.auto_canvas or not self.project.clips:
            return False
        sz = media_size(self.project.clips[0].src)
        if not sz:
            return False
        w, h = canvas_for(*sz)
        if force or (w, h) != (self.project.width, self.project.height):
            self.project.width, self.project.height = w, h
            self.preview.set_aspect(w, h)
            return True
        return False

    # ================================================================ xem trước
    def _seek(self, t):
        if self.playing:
            self._play_base = t
            self._play_t0 = time.monotonic()
            self._load_at(t, play=True)
        else:
            self._render_frame()

    def _active_texts(self, t):
        return [x for x in self.project.texts if x.start <= t < x.start + x.dur]

    def _load_at(self, t: float, play: bool):
        pv = self.preview
        hit = self.project.clip_at(t)
        pv.empty.setVisible(not self.project.clips)
        if not hit:
            pv.img.clear()
            if pv.player:
                pv.player.pause()
            pv.video.setVisible(False)
            pv.img.setVisible(False)
            return None
        i, src_t = hit
        c = self.project.clips[i]
        if c.kind == "image":
            pv.video.setVisible(False)
            pv.img.setVisible(True)
            x, y, w, h = pv.box
            pm = QPixmap(c.src)
            pv.img.setPixmap(pm.scaled(int(w * c.scale), int(h * c.scale), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            if pv.player:
                pv.player.pause()
            pv.cur_src = None
        else:
            pv.img.setVisible(False)
            pv.video.setVisible(True)
            if pv.player:
                if pv.cur_src != (c.id, c.src):
                    pv.player.setSource(QUrl.fromLocalFile(c.src))
                    pv.cur_src = (c.id, c.src)
                pv.player.setPlaybackRate(c.speed)
                if pv.aout:
                    pv.aout.setVolume(min(1.0, c.volume))
                pv.player.setPosition(int(src_t * 1000))
                pv.player.play() if play else pv.player.pause()
        pv.show_text(self._active_texts(t), pv.box[3] / self.project.height)
        return c

    def _render_frame(self):
        t = self.timeline.playhead
        self.preview.time.setText(f"{fmt_time(t)} / {fmt_time(self.project.duration)}")
        self._load_at(t, play=False)

    def toggle_play(self):
        pv = self.preview
        if self.playing:
            self.playing = False
            self.tick.stop()
            if pv.player:
                pv.player.pause()
                pv.music.pause()
            pv.b_play.setIcon(icon("play", "#ffffff", 16))
            return
        if not self.project.clips:
            return
        if self.timeline.playhead >= self.project.video_duration - 0.05:
            self.timeline.playhead = 0.0
        pv.ensure_audio()
        self.playing = True
        self._play_base = self.timeline.playhead
        self._play_t0 = time.monotonic()
        self._cur_clip = self._load_at(self._play_base, play=True)
        self._cur_music = None
        pv.b_play.setIcon(icon("pause", "#ffffff", 16))
        self.tick.start()

    def _on_tick(self):
        t = self._play_base + (time.monotonic() - self._play_t0)
        if t >= self.project.duration:
            self.timeline.playhead = self.project.duration
            self.toggle_play()
            self.timeline.update()
            return
        self.timeline.playhead = t
        self.timeline.update()
        pv = self.preview
        pv.time.setText(f"{fmt_time(t)} / {fmt_time(self.project.duration)}")
        hit = self.project.clip_at(t)
        c = self.project.clips[hit[0]] if hit else None
        if c is not getattr(self, "_cur_clip", None):
            self._cur_clip = self._load_at(t, play=True)
        pv.show_text(self._active_texts(t), pv.box[3] / self.project.height)
        # nhạc: phát mục âm thanh đang có tại t
        if pv.music:
            act = next((a for a in self.project.audios if a.start <= t < a.start + a.dur), None)
            if act is not self._cur_music:
                self._cur_music = act
                if act:
                    pv.music.setSource(QUrl.fromLocalFile(act.src))
                    if pv.mout:
                        pv.mout.setVolume(min(1.0, act.volume))
                    pv.music.setPosition(int((act.in_s + t - act.start) * 1000))
                    pv.music.play()
                else:
                    pv.music.stop()
        # cuộn timeline theo kim
        x = self.timeline.x_of(t)
        sb = self.scroll.horizontalScrollBar()
        if x > sb.value() + self.scroll.viewport().width() - 60:
            sb.setValue(int(x - 120))

    # ================================================================ dự án
    def new_project(self):
        if self.project.clips and QMessageBox.question(self, tr("Dự án mới"), tr("Bỏ dự án đang dựng và tạo dự án mới?")) != QMessageBox.Yes:
            return
        self.history.push(self.project)
        self.project = Project()
        self.media_list.clear()
        self.audio_list.clear()
        self.timeline.playhead = 0
        self.refresh()

    def save_project(self):
        d = data_dir() / "projects"
        d.mkdir(exist_ok=True)
        f, _ = QFileDialog.getSaveFileName(self, tr("Lưu dự án"), str(d / f"{self.project.name}.vaproj"), "Dự án (*.vaproj)")
        if f:
            self.project.name = Path(f).stem
            self.project.save(f)
            self.refresh(keep_sel=True)
            self.ctx.toast("ok", tr("Đã lưu dự án"))

    def open_project(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Mở dự án"), str(data_dir() / "projects"), "Dự án (*.vaproj)")
        if f:
            self.history.push(self.project)
            self.project = Project.load(f)
            self.media_list.clear()
            self.audio_list.clear()
            self.refresh()

    def quick_tools(self):
        from .quick_tools import QuickToolsPage
        d = QDialog(self)
        d.setWindowTitle(tr("Công cụ nhanh"))
        d.resize(1100, 720)
        v = QVBoxLayout(d)
        v.addWidget(QuickToolsPage(self.ctx))
        d.exec()

    def export_video(self):
        if not self.project.clips:
            self.ctx.toast("warn", tr("Timeline chưa có clip nào."))
            return
        out_dir = Path(self.db.get_setting("editor_out", str(default_output_dir() / "dung_video")))
        out_dir.mkdir(parents=True, exist_ok=True)
        f, _ = QFileDialog.getSaveFileName(self, tr("Xuất video"), str(out_dir / f"{self.project.name}.mp4"), "MP4 (*.mp4)")
        if not f:
            return
        self.db.set_setting("editor_out", str(Path(f).parent))
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Đang xuất video"))
        dlg.setFixedSize(420, 120)
        v = QVBoxLayout(dlg)
        bar = GradientBar()
        lab = label("0%", "muted")
        v.addWidget(label(f"{Path(f).name} · {self.project.width}×{self.project.height}", "h2"))
        v.addWidget(bar)
        v.addWidget(lab)
        proj = Project.from_json(self.project.to_json())

        def done(_):
            dlg.accept()
            self.ctx.toast("ok", tr("Đã xuất") + f" {Path(f).name}")
            open_path(str(Path(f).parent))

        def err(m):
            dlg.reject()
            L.error("Xuất video lỗi: %s", m)
            QMessageBox.warning(self, tr("Lỗi xuất video"), m[-800:])

        run_bg(lambda progress: export(proj, f, progress), on_done=done, on_error=err,
               on_progress=lambda p_, m: (bar.set(p_ / 100), lab.setText(f"{p_}%")))
        dlg.exec()

    def export_capcut(self):
        if not self.project.clips:
            self.ctx.toast("warn", tr("Timeline chưa có clip nào."))
            return
        from ...media import capcut
        try:
            d = capcut.export_project(self.project)
            self.ctx.toast("ok", tr("Đã tạo dự án CapCut. Mở CapCut để thấy trong danh sách nháp."))
            open_path(str(d.parent))
        except Exception as e:
            QMessageBox.warning(self, tr("Lỗi"), str(e))

    def showEvent(self, e):
        super().showEvent(e)
        if self.left_tabs.currentWidget() is self.lib_tab:
            self.reload_library()

    def hideEvent(self, e):
        if self.playing:
            self.toggle_play()
        self.db.set_setting("editor_current", self.project.to_json())
        super().hideEvent(e)
