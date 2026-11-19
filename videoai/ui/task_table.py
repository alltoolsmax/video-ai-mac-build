"""Bảng danh sách tác vụ: model + delegate vẽ ảnh xem trước và nhãn trạng thái."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QStyledItemDelegate, QTableView

from .theme import C, gradient, icon_pixmap
from ..core.errors import friendly
from ..core.i18n import tr
from ..core.paths import data_dir
from ..media.ffmpeg import ffmpeg, NOWIN

STATUS = {
    "queued": ("Chờ", "warning", "warning-bg"),
    "running": ("Đang tạo", "info", "info-bg"),
    "paused": ("Tạm dừng", "warning", "warning-bg"),
    "needs_user": ("Cần bạn xử lý", "violet", "violet-bg"),
    "done": ("Hoàn thành", "success", "success-bg"),
    "failed": ("Lỗi", "danger", "danger-bg"),
    "blocked": ("Bị chặn", "danger", "danger-bg"),
    "cancelled": ("Đã hủy", "text-faint", "surface-2"),
}
COLS = ["", "#", "Kết quả", "Prompt", "Trạng thái", "Tài khoản · ghi chú", ""]
THUMB = QSize(104, 58)


class _ThumbSig(QObject):
    ready = Signal(str)


class _ThumbJob(QRunnable):
    def __init__(self, src: str, out: str, sig: _ThumbSig):
        super().__init__()
        self.src, self.out, self.sig = src, out, sig

    def run(self):
        try:
            subprocess.run([ffmpeg(), "-y", "-ss", "0.5", "-i", self.src, "-frames:v", "1", "-vf", "scale=240:-1", self.out],
                           capture_output=True, creationflags=NOWIN, timeout=30)
        except Exception:
            pass
        self.sig.ready.emit(self.src)


class TaskModel(QAbstractTableModel):
    def __init__(self, db, page_key: str):
        super().__init__()
        self.db = db
        self.page_key = page_key
        self.rows: list[dict] = []
        self.filter: str | None = None
        self._pix: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._sig = _ThumbSig()
        self._sig.ready.connect(self._thumb_ready)
        self.checked: set[str] = set()
        self.thumb_dir = data_dir() / "thumbs"
        self.thumb_dir.mkdir(exist_ok=True)

    def reload(self):
        from ..core.platforms import PAGE_BY_KEY
        pdef = PAGE_BY_KEY[self.page_key]
        rows = self.db.jobs_for_platform(pdef.platform, self.page_key)
        if self.filter == "failed":
            rows = [r for r in rows if r["status"] in ("failed", "blocked")]
        elif self.filter:
            rows = [r for r in rows if r["status"] == self.filter]
        labels = {a["id"]: a["label"].split("@")[0] for a in self.db.accounts()}
        for r in rows:
            r["outputs"] = self.db.outputs(r["id"]) if r["status"] == "done" else []
            r["acc"] = labels.get(r.get("account_id"), "")
        ids = {r["id"] for r in rows}
        self.checked &= ids
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLS)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if o == Qt.Horizontal and role == Qt.DisplayRole:
            return tr(COLS[s])
        return None

    def flags(self, idx):
        f = super().flags(idx)
        if idx.column() == 0:
            f |= Qt.ItemIsUserCheckable
        return f

    def setData(self, idx, value, role=Qt.EditRole):
        if role == Qt.CheckStateRole and idx.column() == 0:
            rid = self.rows[idx.row()]["id"]
            if Qt.CheckState(value) == Qt.Checked:
                self.checked.add(rid)
            else:
                self.checked.discard(rid)
            self.dataChanged.emit(idx, idx)
            self.check_changed()
            return True
        return False

    def check_changed(self):
        pass   # được gán từ trang để cập nhật số đã chọn

    def set_all(self, on: bool):
        self.checked = {r["id"] for r in self.rows} if on else set()
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0))
        self.check_changed()

    def checked_rows(self) -> list[dict]:
        return [r for r in self.rows if r["id"] in self.checked]

    def data(self, idx, role=Qt.DisplayRole):
        r = self.rows[idx.row()]
        c = idx.column()
        if role == Qt.CheckStateRole and c == 0:
            return Qt.Checked if r["id"] in self.checked else Qt.Unchecked
        if role == Qt.DisplayRole:
            if c == 1:
                return str(r["row_no"])
            if c == 3:
                return r["prompt"].replace("\n", " ")
            if c == 5:
                acc = r.get("acc") or ""
                if r["status"] == "running":
                    return f"{acc} · {r['progress']}%" if acc else f"{r['progress']}%"
                if r["status"] in ("failed", "blocked"):
                    return friendly(r["error_code"])
                if r["status"] == "done":
                    return f"{acc} · {len(r['outputs'])} " + tr("tệp")
                if r["status"] == "queued" and r.get("error_code"):
                    return tr("Chờ chạy lại trên tài khoản khác")
                return acc
            if c == 6:
                return "⋯"
        if role == Qt.ToolTipRole:
            if c == 3:
                return r["prompt"]
            if c == 5 and r.get("error_text"):
                return f"{friendly(r['error_code'])}\n\n{r['error_text']}"
            if c == 2 and r["outputs"]:
                return "\n".join(o["path"] for o in r["outputs"])
        if role == Qt.TextAlignmentRole and c in (1, 6):
            return Qt.AlignCenter
        if role == Qt.ForegroundRole and c == 5:
            if r["status"] in ("failed", "blocked"):
                return QColor(C["danger"])
            return QColor(C["text-muted"])
        if role == Qt.UserRole:
            return r
        return None

    # ----- ảnh xem trước -----
    def thumb(self, r: dict) -> QPixmap | None:
        if not r["outputs"]:
            return None
        o = r["outputs"][0]
        p = o["path"]
        if p in self._pix:
            return self._pix[p]
        if o["kind"] == "image":
            pm = QPixmap(p)
            if not pm.isNull():
                pm = pm.scaled(THUMB * 2, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                self._pix[p] = pm
                return pm
            return None
        tf = self.thumb_dir / (hashlib.md5(p.encode()).hexdigest() + ".jpg")
        if tf.exists():
            pm = QPixmap(str(tf))
            self._pix[p] = pm
            return pm
        if p not in self._pending and Path(p).exists():
            self._pending.add(p)
            QThreadPool.globalInstance().start(_ThumbJob(p, str(tf), self._sig))
        return None

    def _thumb_ready(self, src):
        self._pending.discard(src)
        for i, r in enumerate(self.rows):
            if r["outputs"] and r["outputs"][0]["path"] == src:
                ix = self.index(i, 2)
                self.dataChanged.emit(ix, ix)


class TaskDelegate(QStyledItemDelegate):
    def paint(self, p: QPainter, opt, idx):
        c = idx.column()
        if c not in (2, 4):
            return super().paint(p, opt, idx)
        r = idx.data(Qt.UserRole)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(opt.rect)
        if c == 2:
            tr_ = QRectF(rect.left() + 6, rect.center().y() - THUMB.height() / 2, THUMB.width(), THUMB.height())
            path = QPainterPath()
            path.addRoundedRect(tr_, 8, 8)
            pm = idx.model().thumb(r)
            if pm is not None and not pm.isNull():
                p.setClipPath(path)
                sx = max(0, (pm.width() - tr_.width() * 2) / 2)
                sy = max(0, (pm.height() - tr_.height() * 2) / 2)
                p.drawPixmap(tr_, pm, QRectF(sx, sy, tr_.width() * 2, tr_.height() * 2))
                p.setClipping(False)
                if r["outputs"][0]["kind"] == "video":
                    p.drawPixmap(int(tr_.center().x() - 9), int(tr_.center().y() - 9), icon_pixmap("play", "#ffffff", 18))
            else:
                bg = {"failed": "#2a1426", "blocked": "#2a1426"}.get(r["status"], "#1a1f45")
                p.fillPath(path, QColor(bg))
                if r["status"] == "running":
                    p.setPen(QColor(C["info"]))
                    p.drawText(tr_, Qt.AlignCenter, f"{r['progress']}%")
                    bar = QRectF(tr_.left() + 10, tr_.bottom() - 10, (tr_.width() - 20) * r["progress"] / 100, 3)
                    bp = QPainterPath()
                    bp.addRoundedRect(bar, 1.5, 1.5)
                    p.fillPath(bp, gradient(tr_, ["#22d3ee", "#6366f1", "#d946ef"]))
                elif r["status"] == "done":
                    p.drawPixmap(int(tr_.center().x() - 9), int(tr_.center().y() - 9), icon_pixmap("film", C["text-faint"], 18))
        else:
            text, fg, bg = STATUS.get(r["status"], STATUS["queued"])
            text = tr(text)
            f = QFont(opt.font)
            f.setPointSizeF(8.6)
            f.setBold(True)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(text) + 20
            pr = QRectF(rect.left() + 6, rect.center().y() - 11, w, 22)
            pp = QPainterPath()
            pp.addRoundedRect(pr, 11, 11)
            p.fillPath(pp, QColor(C[bg]))
            p.setPen(QColor(C[fg]))
            p.drawText(pr, Qt.AlignCenter, text)
        p.restore()

    def sizeHint(self, opt, idx):
        return QSize(120, 70)


class TaskTable(QTableView):
    action = Signal(str, dict)   # (menu|open), row

    def __init__(self, model: TaskModel):
        super().__init__()
        self.setModel(model)
        self.setItemDelegate(TaskDelegate(self))
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(72)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        for i, w in enumerate([34, 34, 120, 0, 120, 180, 40]):
            if w:
                h.resizeSection(i, w)
                h.setSectionResizeMode(i, QHeaderView.Interactive if i == 5 else QHeaderView.Fixed)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self._emit_menu(self.indexAt(pos)))
        self.clicked.connect(self._clicked)
        self.doubleClicked.connect(lambda ix: ix.isValid() and self.action.emit("open", ix.data(Qt.UserRole)))
        self.setAccessibleName(tr("Danh sách tác vụ"))

    def _clicked(self, ix):
        if ix.column() == 6:
            self._emit_menu(ix)
        elif ix.column() != 0 and ix.isValid():   # bấm vào dòng cũng tick/bỏ tick
            m = self.model()
            cur = m.data(m.index(ix.row(), 0), Qt.CheckStateRole)
            m.setData(m.index(ix.row(), 0), Qt.Unchecked if cur == Qt.Checked else Qt.Checked, Qt.CheckStateRole)

    def _emit_menu(self, ix):
        if ix.isValid():
            self.action.emit("menu", ix.data(Qt.UserRole))

    def selected_rows(self) -> list[dict]:
        m = self.model()
        return [m.rows[i.row()] for i in self.selectionModel().selectedRows()]
