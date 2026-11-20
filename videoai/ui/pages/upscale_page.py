"""Nâng Cấp Ảnh: Real-ESRGAN hàng loạt + so sánh trước/sau."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QFileDialog, QHBoxLayout, QListWidget, QListWidgetItem,
                               QVBoxLayout, QWidget)

from ..widgets import Card, GradientBar, PathPicker, button, combo, field, label
from ..workers import run_bg
from ...core.i18n import tr
from ...core.paths import default_output_dir
from ...media import upscale


class CompareView(QWidget):
    """Ảnh trước/sau chồng lên nhau, có thanh chia dọc: bấm/kéo chuột trái ngay trên ảnh để kéo thanh qua lại,
    lăn chuột để phóng to (quanh con trỏ), giữ chuột phải để di chuyển ảnh khi đang phóng to, bấm đúp để về vừa khung."""

    def __init__(self, before: str, after: str | None, parent=None):
        super().__init__(parent)
        self.a = QPixmap(before)
        self.b = QPixmap(after) if after else QPixmap()
        self.split = 0.5
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self._pan_from = None
        self.setMouseTracking(True)
        self.setMinimumSize(400, 300)
        self.setCursor(Qt.SplitHCursor if not self.b.isNull() else Qt.ArrowCursor)

    def _base(self) -> QPixmap:
        return self.b if not self.b.isNull() else self.a

    def _target(self) -> QRectF:
        """Khung ảnh trên màn hình (đã tính vừa khung × zoom + dịch chuyển)."""
        base = self._base()
        if base.isNull():
            return QRectF()
        k = min(self.width() / base.width(), self.height() / base.height()) * self.zoom
        w, h = base.width() * k, base.height() * k
        return QRectF((self.width() - w) / 2 + self.pan.x(), (self.height() - h) / 2 + self.pan.y(), w, h)

    def paintEvent(self, _e):
        from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPainterPath
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#05081c"))
        t = self._target()
        if t.isNull():
            return
        if self.b.isNull():
            p.drawPixmap(t, self.a, QRectF(self.a.rect()))
            return
        p.drawPixmap(t, self.b, QRectF(self.b.rect()))                     # SAU (toàn khung)
        x = t.left() + t.width() * self.split
        p.save()
        p.setClipRect(QRectF(t.left(), t.top(), max(0.0, x - t.left()), t.height()))
        p.drawPixmap(t, self.a, QRectF(self.a.rect()))                     # TRƯỚC (bên trái thanh chia)
        p.restore()
        top, bot = max(t.top(), 0), min(t.bottom(), self.height())
        p.setPen(QPen(QColor(255, 255, 255, 235), 2))
        p.drawLine(QPointF(x, top), QPointF(x, bot))
        cy = (top + bot) / 2                                               # tay nắm tròn giữa thanh
        p.setBrush(QColor("#22d3ee"))
        p.setPen(QPen(QColor("white"), 2))
        p.drawEllipse(QPointF(x, cy), 17, 17)
        p.setPen(QPen(QColor("#05081c"), 2.4))
        for d in (-1, 1):
            path = QPainterPath()
            path.moveTo(x + d * 4, cy - 6)
            path.lineTo(x + d * 10, cy)
            path.lineTo(x + d * 4, cy + 6)
            p.drawPath(path)
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        for txt, left in ((tr("TRƯỚC") + f"  {self.a.width()}×{self.a.height()}", True),
                          (tr("SAU") + f"  {self.b.width()}×{self.b.height()}", False)):
            w = p.fontMetrics().horizontalAdvance(txt) + 18
            r = QRectF(12 if left else self.width() - w - 12, 12, w, 26)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 160))
            p.drawRoundedRect(r, 13, 13)
            p.setPen(QColor("#e0e7ff" if left else "#67e8f9"))
            p.drawText(r, Qt.AlignCenter, txt)
        p.end()

    def _set_split(self, x: float):
        t = self._target()
        if t.width() > 0:
            self.split = max(0.0, min(1.0, (x - t.left()) / t.width()))
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._set_split(e.position().x())
        elif e.button() in (Qt.RightButton, Qt.MiddleButton):
            self._pan_from = (e.position(), QPointF(self.pan))
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self._set_split(e.position().x())
        elif self._pan_from is not None:
            start, pan0 = self._pan_from
            self.pan = pan0 + (e.position() - start)
            self.update()

    def mouseReleaseEvent(self, e):
        if self._pan_from is not None:
            self._pan_from = None
            self.setCursor(Qt.SplitHCursor if not self.b.isNull() else Qt.ArrowCursor)

    def mouseDoubleClickEvent(self, e):
        self.zoom, self.pan = 1.0, QPointF(0, 0)
        self.update()

    def wheelEvent(self, e):
        old = self._target()
        z = max(1.0, min(12.0, self.zoom * (1.25 if e.angleDelta().y() > 0 else 0.8)))
        if z == self.zoom or old.isNull():
            return
        pos = e.position()
        rx, ry = (pos.x() - old.left()) / old.width(), (pos.y() - old.top()) / old.height()
        self.zoom = z
        if z == 1.0:
            self.pan = QPointF(0, 0)
        else:                                                              # giữ điểm dưới con trỏ đứng yên
            t = self._target()
            self.pan += QPointF(pos.x() - (t.left() + rx * t.width()), pos.y() - (t.top() + ry * t.height()))
        self.update()


class CompareDialog(QDialog):
    """Popup xem lớn: so sánh trước / sau bằng thanh kéo ngay trên ảnh."""

    def __init__(self, before: str, after: str | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("So sánh trước / sau") + " – " + Path(before).name)
        scr = (parent.screen() if parent else QApplication.primaryScreen()).availableGeometry()
        self.resize(int(scr.width() * 0.9), int(scr.height() * 0.9))
        self.setStyleSheet("QDialog{background:#05081c;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.view = CompareView(before, after)
        v.addWidget(self.view, 1)
        bar = QHBoxLayout()
        bar.setContentsMargins(14, 8, 14, 10)
        hint = label(tr("Kéo chuột trên ảnh để so sánh · Lăn chuột để phóng to · Giữ chuột phải để di chuyển · "
                        "Bấm đúp để về vừa khung · Esc để đóng") if after else tr("Ảnh này chưa được nâng cấp"), "faint")
        bar.addWidget(hint, 1)
        if after:
            b_open = button("Mở thư mục", "chip", "folder", "#67e8f9")
            b_open.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(after).parent))))
            bar.addWidget(b_open)
        b_close = button("Đóng", "chip", "x", "#fb7185")
        b_close.clicked.connect(self.accept)
        bar.addWidget(b_close)
        v.addLayout(bar)


class DropList(QListWidget):
    """Danh sách ảnh nhận kéo-thả file từ máy."""

    def __init__(self, on_drop):
        super().__init__()
        self._on_drop = on_drop
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self._on_drop([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()


class UpscalePage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.files: list[str] = []
        self.results: dict[str, str] = {}
        self.busy = False
        self._cur: tuple[str, int] | None = None          # (ảnh đang nâng cấp, %)
        self._queue: set[str] = set()
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
        from .flow_page import Seg
        self.scale = Seg(["2x", "3x", "4x", "6x"], "4x")            # 4 nút trên 1 hàng ngang
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
        lst = Card("Danh sách ảnh (kéo thả ảnh vào đây · bấm vào ảnh đã xong để xem lớn và so sánh)", "image", icon_color="#f9a8d4")
        self.list = DropList(self._dropped)
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(150, 110))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setSpacing(8)
        self.list.itemClicked.connect(self.compare)
        lst.add(self.list)
        row.addWidget(lst, 1)

    def _refresh(self):
        self.list.clear()
        for f in self.files:
            name = Path(f).name[:22]
            if f in self.results:
                txt = "✓ " + name
            elif self._cur and self._cur[0] == f:
                txt = f"⏳ {self._cur[1]}%  " + name
            elif f in self._queue:
                txt = "… " + tr("Chờ") + "  " + name
            else:
                txt = name
            it = QListWidgetItem(QIcon(self._thumb(f)), txt)
            it.setToolTip(self.results.get(f, f))
            it.setData(Qt.UserRole, f)
            self.list.addItem(it)

    def _thumb(self, f: str) -> QPixmap:
        """Ảnh nhỏ trong danh sách; ảnh đang nâng cấp: phủ tối + vòng tiến độ %, ảnh xong: dấu ✓ xanh."""
        from PySide6.QtGui import QColor, QPainter, QPen, QFont
        cache = self.__dict__.setdefault("_thumbs", {})
        if f not in cache:
            cache[f] = QPixmap(f).scaled(300, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm = QPixmap(cache[f])
        if pm.isNull():
            return pm
        cur = self._cur[1] if (self._cur and self._cur[0] == f) else None
        done = f in self.results
        if cur is None and not done and f not in self._queue:
            return pm
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = pm.width(), pm.height()
        if cur is not None:
            p.fillRect(pm.rect(), QColor(5, 8, 28, 150))
            r = min(w, h) * 0.28
            rect = QRectF(w / 2 - r, h / 2 - r, 2 * r, 2 * r)
            p.setPen(QPen(QColor(255, 255, 255, 60), 9))
            p.drawEllipse(rect)
            p.setPen(QPen(QColor("#22d3ee"), 9, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, 90 * 16, -int(360 * 16 * max(0.02, cur / 100)))
            fnt = QFont(self.font())
            fnt.setBold(True)
            fnt.setPixelSize(int(r * 0.6))
            p.setFont(fnt)
            p.setPen(QColor("white"))
            p.drawText(rect, Qt.AlignCenter, f"{cur}%")
        elif done:
            r = 26
            p.setBrush(QColor("#22c55e"))
            p.setPen(QPen(QColor("white"), 3))
            p.drawEllipse(QRectF(w - 2 * r - 8, 8, 2 * r, 2 * r))
            p.setPen(QPen(QColor("white"), 6, Qt.SolidLine, Qt.RoundCap))
            cx, cy = w - r - 8, 8 + r
            p.drawLine(QPointF(cx - 11, cy), QPointF(cx - 3, cy + 9))
            p.drawLine(QPointF(cx - 3, cy + 9), QPointF(cx + 12, cy - 9))
        else:
            p.fillRect(pm.rect(), QColor(5, 8, 28, 110))
        p.end()
        return pm

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

    def _dropped(self, paths):
        fs = [p for p in paths if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        self.files += [f for f in fs if f not in self.files]
        self._refresh()

    def clear(self):
        if self.busy:
            return self.ctx.toast("info", tr("Đang nâng cấp, chờ xong rồi xóa danh sách."))
        self.files, self.results = [], {}
        self._refresh()

    def run(self):
        if self.busy:
            return
        todo = [f for f in self.files if f not in self.results]
        if not todo:
            return self.ctx.toast("info", tr("Thêm ảnh cần nâng cấp trước (bấm Thêm ảnh hoặc kéo thả ảnh vào danh sách)."))
        scale = int(self.scale.value().rstrip("x"))
        model = list(upscale.MODELS.values())[self.model.currentIndex()]
        fmt = self.fmt.currentText()
        out = Path(self.out.text())
        out.mkdir(parents=True, exist_ok=True)

        n = len(todo)

        def job(progress):
            res = {}
            for i, f in enumerate(todo):
                dst = out / f"{Path(f).stem}_x{scale}.{fmt}"
                last = [-1]

                def on_pct(x, i=i, f=f):
                    k = int(x * 100)
                    if k != last[0]:
                        last[0] = k
                        progress(int(100 * (i + x) / n), f"{i}\t{f}\t{k}")
                on_pct(0.0)
                upscale.upscale_to(f, str(dst), scale, model, fmt, on_pct=on_pct)
                res[f] = str(dst)
                progress(int(100 * (i + 1) / n), f"{i}\t{f}\t100\t{dst}")
            return res

        self.busy = True
        self._queue = set(todo)
        self._n = n
        self.b_run.setEnabled(False)
        self.b_run.setText(tr("Đang nâng cấp…"))
        self.bar.set(0.0)
        self.state.setText(tr("Đang nâng cấp") + f" 1/{n}…")
        self._refresh()
        run_bg(job, on_done=self._done, on_error=self._err, on_progress=self._progress)

    def _progress(self, p, msg):
        self.bar.set(p / 100)
        parts = str(msg).split("\t")
        if len(parts) < 3:
            return
        i, f, k = int(parts[0]), parts[1], int(parts[2])
        if len(parts) >= 4:                                   # xong 1 ảnh → hiện ngay dấu ✓, bấm xem được luôn
            self.results[f] = parts[3]
            self._queue.discard(f)
            self._cur = None
        else:
            self._cur = (f, k)
        self.state.setText(tr("Đang nâng cấp") + f" {min(i + 1, self._n)}/{self._n} · {k}% · {Path(f).name}  ·  "
                           + tr("Tổng") + f" {p}%")
        self._refresh()

    def _finish(self):
        self.busy = False
        self._cur = None
        self._queue = set()
        self.b_run.setEnabled(True)
        self.b_run.setText(tr("Bắt đầu nâng cấp"))

    def _done(self, res):
        self.results.update(res)
        self._finish()
        self.bar.set(1.0)
        self.state.setText(tr("Xong") + f" {len(res)} " + tr("ảnh"))
        self._refresh()
        self.ctx.toast("ok", tr("Đã nâng cấp") + f" {len(res)} " + tr("ảnh"))

    def _err(self, msg):
        self._finish()
        self.state.setText(tr("Lỗi") + ": " + str(msg)[:120])
        self._refresh()
        self.ctx.toast("error", msg)

    def compare(self, it):
        f = it.data(Qt.UserRole)
        if f in self.results:
            CompareDialog(f, self.results[f], self).exec()
        elif not (self._cur and self._cur[0] == f):
            CompareDialog(f, None, self).exec()               # chưa nâng cấp: xem lớn ảnh gốc
