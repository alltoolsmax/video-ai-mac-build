"""Xóa Watermark (Logo): chọn ảnh / video đã tạo trong tools (2 mục riêng) hoặc thêm từ máy, kéo vào danh sách,
khoanh vùng logo (mặc định logo Flow góc phải dưới) → "Thực hiện xóa Logo" → lưu tệp mới vào thư mục đã chọn."""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from PySide6.QtCore import QMimeData, QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .gen_page import open_path, reveal
from ..theme import C, icon
from ..widgets import Card, GradientBar, ShineButton, button, combo, field, icon_button, label
from ..workers import run_bg
from ...core.i18n import tr
from ...core.paths import data_dir, default_output_dir
from ...media import delogo as D

POSITIONS = [("auto", "Tự động (logo Flow – góc phải dưới)"), ("br", "Góc phải dưới"), ("bl", "Góc trái dưới"),
             ("tr", "Góc phải trên"), ("tl", "Góc trái trên"), ("custom", "Tự khoanh vùng trên ảnh")]
METHOD_LABELS = [("fill", "Làm liền nền (đẹp, khuyên dùng)"), ("blur", "Làm mờ vùng logo"),
                 ("crop", "Cắt viền (cắt bỏ phần chứa logo)")]
MEDIA_FILTER = "Ảnh / Video (*.mp4 *.mov *.webm *.mkv *.m4v *.jpg *.jpeg *.png *.webp *.bmp)"


def thumb_path(src: str) -> Path:
    d = data_dir() / "thumbs"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(src.encode("utf-8")).hexdigest()[:16] + ".jpg")


def make_thumb(src: str) -> str | None:
    """Ảnh nhỏ: ảnh gốc, hoặc khung giữa của video (lưu sẵn để lần sau mở nhanh)."""
    if not D.is_video(src):
        return src
    t = thumb_path(src)
    if not t.exists():
        try:
            from ...media import ffmpeg as F
            F.run(["-ss", f"{max(0.0, F.duration(src) / 2):.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=360:-2",
                   "-q:v", "4", str(t)])
        except Exception:
            return None
    return str(t)


class LibGrid(QListWidget):
    """Lưới media đã tạo: chọn nhiều, kéo sang danh sách xóa logo."""

    def __init__(self):
        super().__init__()
        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(122, 76))
        self.setGridSize(QSize(136, 108))
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideMiddle)
        self.setStyleSheet("QListWidget{background:#0b1030;border:none;}"
                           "QListWidget::item{color:#9aa6d6;font-size:10px;border-radius:6px;padding:2px;}"
                           "QListWidget::item:selected{background:#123a5c;border:1px solid #22d3ee;}")

    def mimeData(self, items):
        m = QMimeData()
        m.setUrls([QUrl.fromLocalFile(i.data(Qt.UserRole)) for i in items])
        return m

    def selected_paths(self) -> list[str]:
        return [i.data(Qt.UserRole) for i in self.selectedItems()]


class QueueList(QListWidget):
    dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DropOnly)
        self.setSpacing(3)
        self.setStyleSheet("QListWidget{background:#0b1030;border:1.5px dashed #4a5fb0;border-radius:10px;}"
                           "QListWidget::item{border:none;}QListWidget::item:selected{background:transparent;}")

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.dropped.emit([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0:
            p = QPainter(self.viewport())
            p.setPen(QColor("#7f8bc4"))
            p.drawText(self.viewport().rect(), Qt.AlignCenter,
                       tr("Kéo thả ảnh / video vào đây\n(từ thư viện bên trái hoặc từ máy tính)"))
            p.end()


class Row(QFrame):
    def __init__(self, page, path: str):
        super().__init__()
        self.page, self.path = page, path
        self.out: str | None = None
        self.setObjectName("r")
        self.setStyleSheet("QFrame#r{background:#0d1442;border:1px solid #22357a;border-radius:8px;}")
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 5, 8, 5)
        self.th = QLabel()
        self.th.setFixedSize(96, 54)
        self.th.setStyleSheet("background:#05081c;border-radius:4px;")
        self.th.setAlignment(Qt.AlignCenter)
        h.addWidget(self.th)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        name = QLabel(Path(path).name)
        name.setStyleSheet("color:#eaf0ff;font-weight:700;")
        tv.addWidget(name)
        self.meta = QLabel(tr("Video") if D.is_video(path) else tr("Ảnh"))
        self.meta.setStyleSheet("color:#7f8bc4;font-size:11px;")
        tv.addWidget(self.meta)
        h.addLayout(tv, 1)
        self.st = QLabel(tr("Chờ"))
        self.st.setStyleSheet("color:#9aa6d6;font-weight:700;")
        h.addWidget(self.st)
        self.b_eye = icon_button("eye", "Xem trước / so sánh trước – sau")
        self.b_eye.clicked.connect(self.view)
        self.b_dir = icon_button("folder", "Mở thư mục chứa tệp đã xóa logo")
        self.b_dir.clicked.connect(lambda: reveal(self.out or self.path))
        b_x = icon_button("x", "Bỏ khỏi danh sách", "#fb7185")
        b_x.clicked.connect(lambda: page.remove_row(self))
        for b in (self.b_eye, self.b_dir, b_x):
            h.addWidget(b)

    def set_thumb(self, t: str | None):
        if t:
            pm = QPixmap(t)
            if not pm.isNull():
                self.th.setPixmap(pm.scaled(96, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def set_state(self, text: str, color: str):
        self.st.setText(text)
        self.st.setStyleSheet(f"color:{color};font-weight:700;")

    def view(self):
        if self.out and not D.is_video(self.path):
            from .upscale_page import CompareDialog
            CompareDialog(self.path, self.out, self.window()).exec()
        else:
            open_path(self.out or self.path)


class RegionView(QWidget):
    """Ảnh xem trước + ô đỏ = vùng logo sẽ xóa. Kéo ô để di chuyển, kéo góc phải dưới để đổi kích thước."""
    changed = Signal(tuple)

    def __init__(self):
        super().__init__()
        self.setMinimumSize(320, 180)
        self.pm: QPixmap | None = None
        self.box = D.PRESETS["auto"]
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def set_image(self, path: str | None):
        self.pm = QPixmap(path) if path else None
        self.update()

    def set_box(self, box):
        self.box = tuple(box)
        self.update()

    def _target(self) -> QRectF:
        r = QRectF(self.rect())
        if not self.pm or self.pm.isNull():
            return r.adjusted(0, 0, 0, 0)
        k = min(r.width() / self.pm.width(), r.height() / self.pm.height())
        w, h = self.pm.width() * k, self.pm.height() * k
        return QRectF((r.width() - w) / 2, (r.height() - h) / 2, w, h)

    def _box_rect(self) -> QRectF:
        t = self._target()
        x, y, w, h = self.box
        return QRectF(t.x() + x * t.width(), t.y() + y * t.height(), w * t.width(), h * t.height())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor("#05081c"))
        t = self._target()
        if self.pm and not self.pm.isNull():
            p.drawPixmap(t.toRect(), self.pm)
        else:
            p.setPen(QColor("#7f8bc4"))
            p.drawText(self.rect(), Qt.AlignCenter, tr("Chọn 1 tệp trong danh sách để xem vùng logo"))
        b = self._box_rect()
        p.setPen(QPen(QColor("#fb7185"), 2, Qt.DashLine))
        p.setBrush(QColor(251, 113, 133, 55))
        p.drawRect(b)
        p.setBrush(QColor("#fb7185"))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(b.right() - 5, b.bottom() - 5, 10, 10))
        p.end()

    def mousePressEvent(self, e):
        b = self._box_rect()
        pos = e.position()
        if QRectF(b.right() - 9, b.bottom() - 9, 18, 18).contains(pos):
            self._drag = ("size", pos, self.box)
        elif b.contains(pos):
            self._drag = ("move", pos, self.box)
        else:
            t = self._target()                          # bấm chỗ khác: đặt ô tại đó
            x, y, w, h = self.box
            nx = (pos.x() - t.x()) / max(1, t.width()) - w / 2
            ny = (pos.y() - t.y()) / max(1, t.height()) - h / 2
            self._set(nx, ny, w, h)
            self._drag = ("move", pos, self.box)

    def mouseMoveEvent(self, e):
        if not self._drag:
            return
        kind, start, box = self._drag
        t = self._target()
        dx = (e.position().x() - start.x()) / max(1, t.width())
        dy = (e.position().y() - start.y()) / max(1, t.height())
        x, y, w, h = box
        if kind == "move":
            self._set(x + dx, y + dy, w, h)
        else:
            self._set(x, y, w + dx, h + dy)

    def mouseReleaseEvent(self, _e):
        self._drag = None

    def _set(self, x, y, w, h):
        w = min(max(0.02, w), 1.0)
        h = min(max(0.02, h), 1.0)
        x = min(max(0.0, x), 1 - w)
        y = min(max(0.0, y), 1 - h)
        self.box = (x, y, w, h)
        self.update()
        self.changed.emit(self.box)


class WatermarkPage(QWidget):
    _thumb_ready = Signal(object, str)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.db = ctx.db
        self.st = self.db.get_setting("watermark", {}) or {}
        self.rows: list[Row] = []
        self.busy = False
        self._thumb_ready.connect(self._apply_thumb)
        root = QHBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(14)
        # ---------- thư viện
        lib = Card("Media đã tạo trong tools", "library")
        lib.setFixedWidth(470)
        self.tabs = QTabWidget()
        self.grid_v, self.grid_i = LibGrid(), LibGrid()
        self.tabs.addTab(self.grid_v, tr("Video"))
        self.tabs.addTab(self.grid_i, tr("Ảnh"))
        lib.add(self.tabs)
        hint = label("Kéo ảnh / video sang khung bên phải, hoặc chọn rồi bấm Thêm vào danh sách", "faint")
        hint.setWordWrap(True)
        lib.add(hint)
        lr = QHBoxLayout()
        b_re = button("Làm mới", "chip", "retry", "#67e8f9")
        b_re.clicked.connect(self.reload_library)
        self.b_add_sel = button("Thêm vào danh sách", "primary", "plus")
        self.b_add_sel.clicked.connect(self._add_selected)
        lr.addWidget(b_re)
        lr.addWidget(self.b_add_sel, 1)
        lib.add(lr)
        for g in (self.grid_v, self.grid_i):
            g.itemSelectionChanged.connect(self._sel_text)
            g.itemDoubleClicked.connect(lambda it: self.add_paths([it.data(Qt.UserRole)]))
        root.addWidget(lib)
        # ---------- danh sách + cài đặt
        R = QVBoxLayout()
        R.setSpacing(10)
        qc = Card("Danh sách xóa logo", "list")
        self.queue = QueueList()
        self.queue.dropped.connect(self.add_paths)
        self.queue.currentRowChanged.connect(self._preview_row)
        qc.add(self.queue)
        qr = QHBoxLayout()
        b_disk = button("Thêm file từ máy", "chip", "folder", "#67e8f9")
        b_disk.clicked.connect(self._from_disk)
        b_clear = button("Xóa danh sách", "chip", "trash", "#fb7185")
        b_clear.clicked.connect(self.clear)
        self.count_lbl = label("", "faint")
        qr.addWidget(b_disk)
        qr.addWidget(b_clear)
        qr.addStretch(1)
        qr.addWidget(self.count_lbl)
        qc.add(qr)
        R.addWidget(qc, 1)
        sc = Card("Vùng logo & nơi lưu", "sliders")
        sh = QHBoxLayout()
        sh.setSpacing(14)
        self.region = RegionView()
        self.region.setFixedSize(384, 216)
        self.region.changed.connect(self._region_moved)
        sh.addWidget(self.region)
        fv = QVBoxLayout()
        fv.setSpacing(8)
        self.pos = combo([t for _, t in POSITIONS])
        self.pos.setCurrentIndex(next((i for i, (k, _) in enumerate(POSITIONS) if k == self.st.get("pos")), 0))
        self.pos.currentIndexChanged.connect(self._pos_changed)
        self.method = combo([t for _, t in METHOD_LABELS])
        self.method.setCurrentIndex(next((i for i, (k, _) in enumerate(METHOD_LABELS) if k == self.st.get("method")), 0))
        self.method.currentIndexChanged.connect(lambda _: self._save())
        self.out_dir = self.st.get("out") or str(default_output_dir() / "da_xoa_logo")
        self.b_out = QPushButton()
        self.b_out.setCursor(Qt.PointingHandCursor)
        self.b_out.setIcon(icon("folder", "#67e8f9", 16))
        self.b_out.setStyleSheet(f"QPushButton{{text-align:left;padding:8px 10px;background:{C['input-bg']};"
                                 f"border:1px solid {C['border-input']};border-radius:4px;}}")
        self.b_out.clicked.connect(self._pick_out)
        fv.addWidget(field("Vị trí logo", self.pos))
        fv.addWidget(field("Cách xóa", self.method))
        fv.addWidget(field("Lưu vào (bấm để đổi)", self.b_out))
        note = label("Ô đỏ = vùng sẽ xóa. Kéo ô để di chuyển, kéo góc phải dưới của ô để đổi kích thước.", "faint")
        note.setWordWrap(True)
        fv.addWidget(note)
        fv.addStretch(1)
        sh.addLayout(fv, 1)
        sc.add(sh)
        R.addWidget(sc)
        br = QHBoxLayout()
        self.bar = GradientBar()
        self.bar_lbl = label("", "faint")
        br.addWidget(self.bar, 1)
        br.addWidget(self.bar_lbl)
        R.addLayout(br)
        self.b_go = ShineButton(tr("Thực hiện xóa Logo"), "eraser", ("#f43f5e", "#d946ef", "#6366f1"))
        self.b_go.setFixedHeight(44)
        self.b_go.clicked.connect(self.run)
        R.addWidget(self.b_go)
        root.addLayout(R, 1)
        box = self.st.get("box")
        self.region.set_box(box if box and len(box) == 4 else D.PRESETS.get(self._pos_key(), D.PRESETS["auto"]))
        self._show_out()
        self._update_count()
        self.reload_library()

    # ------------------------------------------------ thư viện
    def reload_library(self):
        rows = self.db.query("SELECT path, kind FROM outputs ORDER BY created_at DESC LIMIT 600")
        self.grid_v.clear()
        self.grid_i.clear()
        seen = set()
        todo = []
        for r in rows:
            p = r["path"]
            if p in seen or not Path(p).exists() or "_xoalogo" in Path(p).stem:
                continue
            seen.add(p)
            g = self.grid_v if D.is_video(p) else self.grid_i
            it = QListWidgetItem(Path(p).name)
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            g.addItem(it)
            todo.append(it)
        self.tabs.setTabText(0, tr("Video") + f" ({self.grid_v.count()})")
        self.tabs.setTabText(1, tr("Ảnh") + f" ({self.grid_i.count()})")
        self._load_thumbs(todo)

    def _load_thumbs(self, items):
        jobs = [(it, it.data(Qt.UserRole)) for it in items]

        def work():
            for it, p in jobs:
                t = make_thumb(p)
                if t:
                    self._thumb_ready.emit(it, t)
        threading.Thread(target=work, daemon=True).start()

    def _apply_thumb(self, target, t: str):
        try:
            if isinstance(target, Row):
                target.set_thumb(t)
            elif isinstance(target, RegionView):
                target.set_image(t or None)
            else:
                pm = QPixmap(t)
                if not pm.isNull():
                    target.setIcon(QIcon(pm.scaled(244, 152, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        except RuntimeError:
            pass          # ô đã bị xóa

    def _sel_text(self):
        n = len(self.grid_v.selected_paths()) + len(self.grid_i.selected_paths())
        self.b_add_sel.setText(tr("Thêm vào danh sách") + (f" ({n})" if n else ""))

    def _add_selected(self):
        ps = self.grid_v.selected_paths() + self.grid_i.selected_paths()
        if not ps:
            return self.ctx.toast("info", tr("Chọn ảnh / video ở thư viện trước (giữ Ctrl để chọn nhiều)."))
        self.add_paths(ps)
        self.grid_v.clearSelection()
        self.grid_i.clearSelection()

    # ------------------------------------------------ danh sách
    def add_paths(self, paths):
        have = {r.path for r in self.rows}
        new = []
        for p in paths:
            if not p or p in have or Path(p).suffix.lower() not in D.VIDEO_EXT + D.IMAGE_EXT or not Path(p).exists():
                continue
            row = Row(self, p)
            it = QListWidgetItem()
            it.setSizeHint(QSize(100, 66))
            self.queue.addItem(it)
            self.queue.setItemWidget(it, row)
            self.rows.append(row)
            have.add(p)
            new.append(row)
        if new:
            def work():
                for r in new:
                    t = make_thumb(r.path)
                    if t:
                        self._thumb_ready.emit(r, t)
            threading.Thread(target=work, daemon=True).start()
            if self.queue.currentRow() < 0:
                self.queue.setCurrentRow(0)
        self._update_count()

    def remove_row(self, row: Row):
        if self.busy:
            return
        i = self.rows.index(row)
        self.rows.pop(i)
        self.queue.takeItem(i)
        self._update_count()

    def clear(self):
        if self.busy:
            return
        self.rows.clear()
        self.queue.clear()
        self.region.set_image(None)
        self._update_count()

    def _from_disk(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Chọn ảnh / video"), "", MEDIA_FILTER)
        self.add_paths(fs)

    def _update_count(self):
        n = len(self.rows)
        self.count_lbl.setText(f"{n} " + tr("tệp") if n else "")
        self.b_go.setText(tr("Thực hiện xóa Logo") + (f" ({n})" if n else ""))
        self.b_go.update()

    def _preview_row(self, i: int):
        if not (0 <= i < len(self.rows)):
            return
        p = self.rows[i].path
        if not D.is_video(p):
            return self.region.set_image(p)

        def work():
            t = make_thumb(p)
            self._thumb_ready.emit(self.region, t or "")
        threading.Thread(target=work, daemon=True).start()

    # ------------------------------------------------ cài đặt
    def _pos_key(self) -> str:
        return POSITIONS[self.pos.currentIndex()][0]

    def _pos_changed(self, _i):
        k = self._pos_key()
        if k in D.PRESETS:
            self.region.set_box(D.PRESETS[k])
        self._save()

    def _region_moved(self, _box):
        if self._pos_key() != "custom":
            self.pos.blockSignals(True)
            self.pos.setCurrentIndex(len(POSITIONS) - 1)
            self.pos.blockSignals(False)
        self._save()

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, tr("Thư mục lưu tệp đã xóa logo"), self.out_dir)
        if d:
            self.out_dir = d
            self._show_out()
            self._save()

    def _show_out(self):
        self.b_out.setText("  " + self.out_dir)
        self.b_out.setToolTip(self.out_dir)

    def _save(self):
        self.db.set_setting("watermark", {"pos": self._pos_key(), "method": METHOD_LABELS[self.method.currentIndex()][0],
                                          "out": self.out_dir, "box": list(self.region.box)})

    # ------------------------------------------------ chạy
    def run(self):
        if self.busy:
            return
        todo = [r for r in self.rows if not r.out]
        if not todo:
            return self.ctx.toast("info", tr("Thêm ảnh / video vào danh sách trước."))
        self.busy = True
        self.b_go.setEnabled(False)
        box, method, out = tuple(self.region.box), METHOD_LABELS[self.method.currentIndex()][0], self.out_dir
        self._save()
        paths = [r.path for r in todo]
        for r in todo:
            r.set_state(tr("Chờ"), "#9aa6d6")

        def job(progress):
            res = []
            for i, p in enumerate(paths):
                progress(0, f"{i}|0")
                try:
                    o = D.remove(p, out, box, method, on_pct=lambda x, i=i: progress(0, f"{i}|{x}"))
                    res.append(str(o))
                    progress(0, f"{i}|done|{o}")
                except Exception as e:
                    res.append(None)
                    progress(0, f"{i}|err|{str(e)[-200:]}")
            return res

        def prog(_p, m):
            try:
                i, rest = m.split("|", 1)
                row = todo[int(i)]
            except Exception:
                return
            if rest.startswith("done|"):
                row.out = rest[5:]
                row.set_state(tr("Đã xong"), "#4ade80")
                row.meta.setText(Path(row.out).name)
            elif rest.startswith("err|"):
                row.set_state(tr("Lỗi"), "#fb7185")
                row.st.setToolTip(rest[4:])
            else:
                row.set_state(tr("Đang xử lý") + f" {rest}%", "#22d3ee")
            n_done = sum(1 for r in todo if r.out or r.st.text() == tr("Lỗi"))
            self.bar.set(n_done / len(todo))
            self.bar_lbl.setText(f"{n_done} / {len(todo)}")

        def done(res):
            self.busy = False
            self.b_go.setEnabled(True)
            ok = sum(1 for x in res if x)
            self.ctx.toast("ok" if ok == len(res) else "warn",
                           tr("Đã xóa logo") + f" {ok}/{len(res)} " + tr("tệp") + " · " + tr("lưu tại") + f" {out}")

        def err(m):
            self.busy = False
            self.b_go.setEnabled(True)
            self.ctx.toast("error", m)
        self.bar.set(0)
        self.bar_lbl.setText(f"0 / {len(todo)}")
        run_bg(job, on_done=done, on_error=err, on_progress=prog)
