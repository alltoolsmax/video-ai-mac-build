"""Công Cụ Video: Ghép & dựng · Cắt · Tách khung hình · Chuyển đổi · Ảnh thành video."""
from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDoubleSpinBox, QFileDialog, QGridLayout, QHBoxLayout, QLineEdit,
                               QListWidget, QListWidgetItem, QPlainTextEdit, QSlider, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from .gen_page import open_path
from ..widgets import Card, GradientBar, PathPicker, button, combo, field, label
from ..workers import run_bg
from ...core.i18n import tr
from ...core.paths import default_output_dir
from ...media import capcut, ffmpeg, srt

VID = "Video (*.mp4 *.mov *.webm *.mkv)"
SIZES = {"16:9 (1920×1080)": (1920, 1080), "9:16 (1080×1920)": (1080, 1920), "1:1 (1080×1080)": (1080, 1080)}


class FileList(QWidget):
    """Danh sách tệp có thêm / lên / xuống / xóa, kéo-thả."""

    def __init__(self, filt=VID):
        super().__init__()
        self.filt = filt
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.InternalMove)
        self.list.setAcceptDrops(True)
        v.addWidget(self.list, 1)
        r = QHBoxLayout()
        for text, ic, fn in (("Thêm", "plus", self.add), ("Lên", "chev_right", lambda: self.move(-1)),
                             ("Xuống", "chev_down", lambda: self.move(1)), ("Bỏ", "x", self.remove),
                             ("Xóa hết", "trash", self.list.clear)):
            b = button(text, "chip", ic, "#67e8f9")
            b.clicked.connect(fn)
            r.addWidget(b)
        r.addStretch()
        v.addLayout(r)

    def add(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Chọn tệp"), "", self.filt)
        for f in fs:
            it = QListWidgetItem(Path(f).name)
            it.setToolTip(f)
            it.setData(Qt.UserRole, f)
            self.list.addItem(it)

    def move(self, d):
        r = self.list.currentRow()
        if r < 0 or not (0 <= r + d < self.list.count()):
            return
        it = self.list.takeItem(r)
        self.list.insertItem(r + d, it)
        self.list.setCurrentRow(r + d)

    def remove(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def files(self):
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())]


class _Runner:
    def _runner_init(self, card):
        self.bar = GradientBar()
        self.state = label("", "faint")
        card.add(self.bar)
        card.add(self.state)

    def _go(self, fn, btn, done_msg, open_dir=None):
        btn.setEnabled(False)
        self.bar.set(0.05)
        self.state.setText(tr("Đang xử lý…"))

        def ok(res):
            btn.setEnabled(True)
            self.bar.set(1)
            self.state.setText(done_msg)
            self.ctx.toast("ok", done_msg)
            if open_dir:
                open_path(open_dir)

        def err(m):
            btn.setEnabled(True)
            self.bar.set(0)
            self.state.setText(tr("Lỗi") + ": " + m[-200:])
            self.ctx.toast("error", tr("Lỗi xử lý video. Xem chi tiết bên dưới thanh tiến độ."))

        run_bg(fn, on_done=ok, on_error=err, on_progress=lambda p, m: (self.bar.set(p / 100), self.state.setText(m)))


class JoinTab(QWidget, _Runner):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 12, 0, 0)
        h.setSpacing(14)
        lc = Card("Clip theo thứ tự (kéo để sắp xếp)", "film")
        self.clips = FileList()
        lc.add(self.clips)
        h.addWidget(lc, 1)
        c = Card("Dựng video", "sliders")
        c.setFixedWidth(460)
        g = QGridLayout()
        self.size = combo(list(SIZES))
        self.fade = QDoubleSpinBox()
        self.fade.setRange(0, 2)
        self.fade.setSingleStep(0.1)
        self.fade.setSuffix(" s")
        self.keep_audio = QCheckBox(tr("Giữ âm thanh của clip"))
        self.keep_audio.setChecked(True)
        self.music = PathPicker("", directory=False, filt="Âm thanh (*.mp3 *.wav *.m4a *.aac)")
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(30)
        self.srt_file = PathPicker("", directory=False, filt="Phụ đề (*.srt)")
        self.sub_lines = QPlainTextEdit()
        self.sub_lines.setPlaceholderText(tr("Hoặc gõ mỗi dòng một câu phụ đề (chia đều theo clip)"))
        self.sub_lines.setFixedHeight(70)
        self.out = PathPicker(str(default_output_dir() / "dung_video" / "video.mp4"), directory=False)
        g.addWidget(field("Khung hình", self.size), 0, 0)
        g.addWidget(field("Mờ dần đầu/cuối mỗi clip", self.fade), 0, 1)
        g.addWidget(self.keep_audio, 1, 0, 1, 2)
        g.addWidget(field("Nhạc nền", self.music), 2, 0, 1, 2)
        g.addWidget(field("Âm lượng nhạc", self.vol), 3, 0, 1, 2)
        g.addWidget(field("Phụ đề SRT", self.srt_file), 4, 0, 1, 2)
        g.addWidget(self.sub_lines, 5, 0, 1, 2)
        g.addWidget(field("Tệp xuất", self.out), 6, 0, 1, 2)
        c.add(g)
        self._runner_init(c)
        r = QHBoxLayout()
        self.b_render = button("Xuất video", "start", "play")
        self.b_render.clicked.connect(self.render)
        b_cc = button("Xuất sang CapCut", "primary", "upload")
        b_cc.clicked.connect(self.capcut)
        r.addWidget(self.b_render)
        r.addWidget(b_cc)
        c.add(r)
        b_fold = button("Xuất thư mục (clip đánh số + SRT)", "chip", "folder", "#67e8f9")
        b_fold.clicked.connect(self.folder)
        c.add(b_fold)
        h.addWidget(c)

    def _srt(self, clips) -> str | None:
        if self.srt_file.text():
            return self.srt_file.text()
        lines = [l for l in self.sub_lines.toPlainText().splitlines() if l.strip()]
        if not lines:
            return None
        durs = [ffmpeg.duration(c) for c in clips]
        cues, t = [], 0.0
        for i, l in enumerate(lines):
            d = durs[i] if i < len(durs) else (durs[-1] if durs else 3)
            cues.append({"start": t, "end": t + d, "text": l})
            t += d
        f = Path(tempfile.mkdtemp()) / "sub.srt"
        f.write_text(srt.build_srt(cues), encoding="utf-8")
        return str(f)

    def render(self):
        clips = self.clips.files()
        if not clips:
            return self.ctx.toast("warn", tr("Thêm ít nhất một clip."))
        out = self.out.text()
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        size, fade, keep = SIZES[self.size.currentText()], self.fade.value(), self.keep_audio.isChecked()
        music, vol = self.music.text() or None, self.vol.value() / 100

        def job(progress):
            progress(10, tr("Chuẩn bị phụ đề…"))
            sub = self._srt(clips)
            progress(30, tr("Đang ghép và mã hóa…"))
            return ffmpeg.concat(clips, out, size, 30, music, vol, keep, sub, fade)

        self._go(job, self.b_render, tr("Đã xuất") + f" {Path(out).name}", str(Path(out).parent))

    def capcut(self):
        clips = self.clips.files()
        if not clips:
            return self.ctx.toast("warn", tr("Thêm ít nhất một clip."))
        name = Path(self.out.text()).stem or "VideoAI"
        size = SIZES[self.size.currentText()]
        music = self.music.text() or None

        def job(progress):
            return capcut.export_draft(name, clips, self._srt(clips), music, canvas=size)

        self._go(job, self.b_render, tr("Đã tạo dự án CapCut. Mở CapCut để xem trong danh sách nháp."),
                 str(capcut.default_draft_root()))

    def folder(self):
        clips = self.clips.files()
        if not clips:
            return
        d = str(Path(self.out.text()).parent / (Path(self.out.text()).stem + "_clips"))
        self._go(lambda progress: capcut.export_folder(clips, d, self._srt(clips), self.music.text() or None),
                 self.b_render, tr("Đã xuất thư mục"), d)


class CutTab(QWidget, _Runner):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 12, 0, 0)
        c = Card("Cắt video", "scissors")
        self.src = PathPicker("", directory=False, filt=VID)
        self.mode = combo(["Chia đều mỗi đoạn N giây", "Cắt một đoạn (từ – đến)"])
        self.seg = QDoubleSpinBox()
        self.seg.setRange(0.5, 3600)
        self.seg.setValue(8)
        self.seg.setSuffix(" s")
        self.a = QDoubleSpinBox()
        self.a.setRange(0, 36000)
        self.a.setSuffix(" s")
        self.b = QDoubleSpinBox()
        self.b.setRange(0, 36000)
        self.b.setValue(5)
        self.b.setSuffix(" s")
        self.out = PathPicker(str(default_output_dir() / "cat_video"))
        g = QGridLayout()
        g.addWidget(field("Video", self.src), 0, 0, 1, 3)
        g.addWidget(field("Cách cắt", self.mode), 1, 0)
        g.addWidget(field("Mỗi đoạn", self.seg), 1, 1)
        g.addWidget(field("Từ", self.a), 2, 0)
        g.addWidget(field("Đến", self.b), 2, 1)
        g.addWidget(field("Thư mục lưu", self.out), 3, 0, 1, 3)
        c.add(g)
        self._runner_init(c)
        self.btn = button("Cắt", "start", "scissors")
        self.btn.clicked.connect(self.go)
        c.add(self.btn)
        v.addWidget(c)
        v.addStretch()

    def go(self):
        src, out = self.src.text(), self.out.text()
        if not src:
            return
        Path(out).mkdir(parents=True, exist_ok=True)
        if self.mode.currentIndex() == 0:
            fn = lambda progress: ffmpeg.cut_segments(src, out, self.seg.value())
        else:
            dst = str(Path(out) / f"{Path(src).stem}_{self.a.value():.1f}-{self.b.value():.1f}.mp4")
            fn = lambda progress: ffmpeg.cut_range(src, dst, self.a.value(), self.b.value())
        self._go(fn, self.btn, tr("Đã cắt xong"), out)


class FramesTab(QWidget, _Runner):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 12, 0, 0)
        h.setSpacing(14)
        lc = Card("Video", "film")
        self.files = FileList()
        lc.add(self.files)
        h.addWidget(lc, 1)
        c = Card("Tách khung hình", "image")
        c.setFixedWidth(420)
        self.which = combo(["Khung cuối (để nối cảnh tiếp)", "Khung đầu", "Mỗi N giây một ảnh"])
        self.every = QDoubleSpinBox()
        self.every.setRange(0.2, 600)
        self.every.setValue(1)
        self.every.setSuffix(" s")
        self.out = PathPicker(str(default_output_dir() / "khung_hinh"))
        c.add(field("Lấy", self.which))
        c.add(field("N giây", self.every))
        c.add(field("Thư mục lưu", self.out))
        self._runner_init(c)
        self.btn = button("Tách", "start", "image")
        self.btn.clicked.connect(self.go)
        c.add(self.btn)
        c.body_layout.addStretch()
        h.addWidget(c)

    def go(self):
        files, out, w, ev = self.files.files(), self.out.text(), self.which.currentIndex(), self.every.value()
        if not files:
            return
        Path(out).mkdir(parents=True, exist_ok=True)

        def job(progress):
            for i, f in enumerate(files):
                progress(int(100 * i / len(files)), Path(f).name)
                if w == 2:
                    ffmpeg.extract_every(f, out, ev)
                else:
                    which = "last" if w == 0 else "first"
                    ffmpeg.extract_frame(f, str(Path(out) / f"{Path(f).stem}_{which}.png"), which)

        self._go(job, self.btn, tr("Đã tách khung hình"), out)


class ConvertTab(QWidget, _Runner):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 12, 0, 0)
        h.setSpacing(14)
        lc = Card("Video", "film")
        self.files = FileList()
        lc.add(self.files)
        h.addWidget(lc, 1)
        c = Card("Chuyển đổi hàng loạt", "sliders")
        c.setFixedWidth(440)
        self.op = combo(["Đổi khung 9:16 (nền mờ)", "Đổi khung 9:16 (cắt giữa)", "Đổi khung 16:9 (nền mờ)",
                         "Đổi tốc độ", "Bỏ âm thanh", "Chèn logo của bạn"])
        self.speed = QDoubleSpinBox()
        self.speed.setRange(0.25, 4)
        self.speed.setValue(1.25)
        self.speed.setSingleStep(0.05)
        self.speed.setPrefix("× ")
        self.logo = PathPicker("", directory=False, filt="Ảnh (*.png)")
        self.corner = combo(["Dưới phải", "Dưới trái", "Trên phải", "Trên trái"])
        self.out = PathPicker(str(default_output_dir() / "chuyen_doi"))
        for t, w in (("Thao tác", self.op), ("Tốc độ", self.speed), ("Logo (PNG nền trong)", self.logo),
                     ("Vị trí logo", self.corner), ("Thư mục lưu", self.out)):
            c.add(field(t, w))
        self._runner_init(c)
        self.btn = button("Chạy", "start", "play")
        self.btn.clicked.connect(self.go)
        c.add(self.btn)
        c.body_layout.addStretch()
        h.addWidget(c)

    def go(self):
        files, out, op = self.files.files(), self.out.text(), self.op.currentIndex()
        if not files:
            return
        Path(out).mkdir(parents=True, exist_ok=True)
        sp, logo = self.speed.value(), self.logo.text()
        corner = ["br", "bl", "tr", "tl"][self.corner.currentIndex()]
        if op == 5 and not logo:
            return self.ctx.toast("warn", tr("Chọn tệp logo."))

        def job(progress):
            for i, f in enumerate(files):
                progress(int(100 * i / len(files)), Path(f).name)
                dst = str(Path(out) / (Path(f).stem + ["_9x16", "_9x16", "_16x9", f"_x{sp}", "_mute", "_logo"][op] + ".mp4"))
                if op in (0, 1, 2):
                    ffmpeg.reframe(f, dst, "9:16" if op < 2 else "16:9", "crop" if op == 1 else "blur")
                elif op == 3:
                    ffmpeg.speed(f, dst, sp)
                elif op == 4:
                    ffmpeg.remove_audio(f, dst)
                else:
                    ffmpeg.add_logo(f, logo, dst, corner)

        self._go(job, self.btn, tr("Đã xử lý") + f" {len(files)} video", out)


class SlideTab(QWidget, _Runner):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 12, 0, 0)
        h.setSpacing(14)
        lc = Card("Ảnh theo thứ tự", "image")
        self.files = FileList("Ảnh (*.png *.jpg *.jpeg *.webp)")
        lc.add(self.files)
        h.addWidget(lc, 1)
        c = Card("Ảnh thành video", "film")
        c.setFixedWidth(420)
        self.sec = QDoubleSpinBox()
        self.sec.setRange(0.5, 30)
        self.sec.setValue(3)
        self.sec.setSuffix(" s")
        self.size = combo(list(SIZES))
        self.out = PathPicker(str(default_output_dir() / "slideshow" / "slideshow.mp4"), directory=False)
        c.add(field("Mỗi ảnh", self.sec))
        c.add(field("Khung hình", self.size))
        c.add(field("Tệp xuất", self.out))
        self._runner_init(c)
        self.btn = button("Tạo video", "start", "play")
        self.btn.clicked.connect(self.go)
        c.add(self.btn)
        c.body_layout.addStretch()
        h.addWidget(c)

    def go(self):
        files, out = self.files.files(), self.out.text()
        if not files:
            return
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        sec, size = self.sec.value(), SIZES[self.size.currentText()]
        self._go(lambda progress: ffmpeg.images_to_video(files, out, sec, size), self.btn,
                 tr("Đã tạo") + f" {Path(out).name}", str(Path(out).parent))


class QuickToolsPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.addWidget(label("Công cụ nhanh", "h1"))
        t = QTabWidget()
        t.addTab(JoinTab(ctx), tr("Ghép nhanh"))
        t.addTab(CutTab(ctx), tr("Cắt video"))
        t.addTab(FramesTab(ctx), tr("Tách khung hình"))
        t.addTab(ConvertTab(ctx), tr("Chuyển đổi"))
        t.addTab(SlideTab(ctx), tr("Ảnh thành video"))
        v.addWidget(t, 1)
