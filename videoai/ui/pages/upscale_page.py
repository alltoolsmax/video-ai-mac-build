"""Nâng Cấp Ảnh: Real-ESRGAN hàng loạt + so sánh trước/sau."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QSlider,
                               QVBoxLayout, QWidget)

from ..widgets import Card, GradientBar, PathPicker, button, combo, field, label
from ..workers import run_bg
from ...core.i18n import tr
from ...core.paths import default_output_dir
from ...media import upscale


class CompareDialog(QDialog):
    def __init__(self, before: str, after: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("So sánh trước / sau"))
        self.resize(1100, 720)
        self.a = QPixmap(before)
        self.b = QPixmap(after)
        v = QVBoxLayout(self)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        v.addWidget(self.view, 1)
        self.s = QSlider(Qt.Horizontal)
        self.s.setRange(0, 100)
        self.s.setValue(50)
        self.s.valueChanged.connect(self._draw)
        v.addWidget(self.s)
        self._draw()

    def _draw(self):
        from PySide6.QtGui import QPainter, QPen, QColor
        size = QSize(1060, 640)
        b = self.b.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        a = self.a.scaled(b.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        out = QPixmap(b.size())
        p = QPainter(out)
        p.drawPixmap(0, 0, b)
        x = int(b.width() * self.s.value() / 100)
        p.drawPixmap(0, 0, a, 0, 0, x, a.height())
        p.setPen(QPen(QColor("#22d3ee"), 2))
        p.drawLine(x, 0, x, b.height())
        p.end()
        self.view.setPixmap(out)


class UpscalePage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.files: list[str] = []
        self.results: dict[str, str] = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(12)
        v.addWidget(label("Nâng cấp ảnh", "h1"))
        if not upscale.available():
            w = label("Chưa có Real-ESRGAN trong thư mục bin/realesrgan – ứng dụng sẽ dùng chế độ phóng to Lanczos "
                      "(chất lượng thấp hơn). Chạy build/fetch_tools.ps1 để tải Real-ESRGAN.", "muted")
            w.setWordWrap(True)
            w.setStyleSheet("color:#fbbf24;")
            v.addWidget(w)
        row = QHBoxLayout()
        row.setSpacing(14)
        v.addLayout(row, 1)
        cfg = Card("Cấu hình", "sliders")
        cfg.setFixedWidth(420)
        self.model = combo(list(upscale.MODELS))
        self.scale = combo(["×2", "×3", "×4"], "×4")
        self.fmt = combo(["png", "jpg", "webp"])
        self.out = PathPicker(str(default_output_dir() / "upscale"))
        cfg.add(field("Model", self.model))
        cfg.add(field("Phóng to", self.scale))
        cfg.add(field("Định dạng", self.fmt))
        cfg.add(field("Thư mục lưu", self.out))
        b_add = button("Thêm ảnh", "primary", "plus")
        b_add.clicked.connect(self.add)
        b_dir = button("Thêm cả thư mục", "chip", "folder", "#67e8f9")
        b_dir.clicked.connect(self.add_dir)
        b_clr = button("Xóa danh sách", "chip", "trash", "#fb7185")
        b_clr.clicked.connect(self.clear)
        cfg.add(b_add)
        r = QHBoxLayout()
        r.addWidget(b_dir)
        r.addWidget(b_clr)
        cfg.add(r)
        cfg.body_layout.addStretch()
        self.bar = GradientBar()
        self.state = label("", "faint")
        cfg.add(self.bar)
        cfg.add(self.state)
        self.b_run = button("Bắt đầu nâng cấp", "start", "play")
        self.b_run.clicked.connect(self.run)
        cfg.add(self.b_run)
        row.addWidget(cfg)
        lst = Card("Danh sách ảnh (bấm đúp ảnh đã xong để so sánh)", "image", icon_color="#f9a8d4")
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(150, 110))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setSpacing(8)
        self.list.itemDoubleClicked.connect(self.compare)
        lst.add(self.list)
        row.addWidget(lst, 1)

    def _refresh(self):
        self.list.clear()
        for f in self.files:
            done = f in self.results
            it = QListWidgetItem(QIcon(QPixmap(f)), ("✓ " if done else "") + Path(f).name[:22])
            it.setToolTip(self.results.get(f, f))
            it.setData(Qt.UserRole, f)
            self.list.addItem(it)

    def add(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Chọn ảnh"), "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
        self.files += [f for f in fs if f not in self.files]
        self._refresh()

    def add_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Chọn thư mục"))
        if d:
            fs = [str(p) for p in sorted(Path(d).iterdir()) if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
            self.files += [f for f in fs if f not in self.files]
            self._refresh()

    def clear(self):
        self.files, self.results = [], {}
        self._refresh()

    def run(self):
        todo = [f for f in self.files if f not in self.results]
        if not todo:
            return
        scale = int(self.scale.currentText()[1:])
        model = upscale.MODELS[self.model.currentText()]
        fmt = self.fmt.currentText()
        out = Path(self.out.text())
        out.mkdir(parents=True, exist_ok=True)
        use_esr = upscale.available()

        def job(progress):
            res = {}
            for i, f in enumerate(todo):
                dst = out / f"{Path(f).stem}_x{scale}.{fmt}"
                progress(int(100 * i / len(todo)), Path(f).name)
                if use_esr:
                    upscale.upscale(f, str(dst), scale, model, fmt)
                else:
                    upscale.upscale_ffmpeg(f, str(dst), scale)
                res[f] = str(dst)
            progress(100, "")
            return res

        self.b_run.setEnabled(False)
        run_bg(job, on_done=self._done, on_error=self._err,
               on_progress=lambda p, m: (self.bar.set(p / 100), self.state.setText(f"{p}%  {m}")))

    def _done(self, res):
        self.results.update(res)
        self.b_run.setEnabled(True)
        self.state.setText(tr("Xong") + f" {len(res)} " + tr("ảnh"))
        self._refresh()
        self.ctx.toast("ok", tr("Đã nâng cấp") + f" {len(res)} " + tr("ảnh"))

    def _err(self, msg):
        self.b_run.setEnabled(True)
        self.ctx.toast("error", msg)

    def compare(self, it):
        f = it.data(Qt.UserRole)
        if f in self.results:
            CompareDialog(f, self.results[f], self).exec()
