"""Bảng danh sách tác vụ.

Cột: ☐ · # · Kết quả (đủ số ảnh/video đã tạo) · Prompt (bấm để sửa) · Ảnh tham chiếu riêng của tác vụ · Thư mục · Trạng thái.
Các dòng "Chưa chạy" là prompt vừa nhập trong ô bên trái (chưa bấm Bắt đầu).
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QRectF, QRunnable, QSize, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QLineEdit, QStyledItemDelegate, QTableView

from .theme import C, gradient, icon_pixmap
from ..core.errors import friendly
from ..core.i18n import tr
from ..core.paths import data_dir
from ..media.ffmpeg import NOWIN, ffmpeg

STATUS = {
    "draft": ("Chưa chạy", "text-faint", "surface-2"),
    "queued": ("Chờ", "warning", "warning-bg"),
    "running": ("Đang tạo", "info", "info-bg"),
    "paused": ("Tạm dừng", "warning", "warning-bg"),
    "needs_user": ("Cần bạn xử lý", "violet", "violet-bg"),
    "done": ("Hoàn thành", "success", "success-bg"),
    "failed": ("Lỗi", "danger", "danger-bg"),
    "blocked": ("Bị chặn", "danger", "danger-bg"),
    "cancelled": ("Đã hủy", "text-faint", "surface-2"),
}
COLS = ["", "#", "Kết quả", "Prompt", "Ảnh tham chiếu", "Thư mục", "Trạng thái"]
C_CHECK, C_NO, C_RES, C_PROMPT, C_REFS, C_DIR, C_STATUS = range(7)
REFS_W = 128
C_ACC = -1   # cột tài khoản đã bỏ: tài khoản do hệ thống tự quản lý, chỉ xem trong Cài Đặt
RES_W, ROW_H = 132, 78


class _ThumbSig(QObject):
    ready = Signal(str)


class _ThumbJob(QRunnable):
    def __init__(self, src: str, out: str, sig: _ThumbSig):
        super().__init__()
        self.src, self.out, self.sig = src, out, sig

    def run(self):
        try:
            subprocess.run([ffmpeg(), "-y", "-ss", "0.5", "-i", self.src, "-frames:v", "1", "-vf", "scale=320:-1", self.out],
                           capture_output=True, creationflags=NOWIN, timeout=30)
        except Exception:
            pass
        self.sig.ready.emit(self.src)


def video_thumb_file(path: str) -> Path:
    d = data_dir() / "thumbs"
    d.mkdir(exist_ok=True)
    return d / (hashlib.md5(path.encode()).hexdigest() + ".jpg")


class TaskModel(QAbstractTableModel):
    def __init__(self, db, page_key: str):
        super().__init__()
        self.db = db
        self.page_key = page_key
        self.rows: list[dict] = []
        self.drafts: list[str] = []
        self.filter: str | None = None
        self._pix: dict[str, QPixmap] = {}
        self._pending: set[str] = set()
        self._sig = _ThumbSig()
        self._sig.ready.connect(self._thumb_ready)
        self.checked: set[str] = set()
        self.on_draft_edit = None        # gán từ trang: (chỉ số, prompt mới)
        self.draft_refs: dict[str, list[str]] = {}   # prompt nháp → ảnh tham chiếu riêng của tác vụ đó

    def set_drafts(self, prompts: list[str]):
        self.drafts = list(prompts)
        self.reload()

    def reload(self):
        from ..core.platforms import PAGE_BY_KEY
        pdef = PAGE_BY_KEY[self.page_key]
        rows = self.db.jobs_for_platform(pdef.platform, self.page_key)
        if self.filter == "draft":
            rows = []
        elif self.filter == "failed":
            rows = [r for r in rows if r["status"] in ("failed", "blocked")]
        elif self.filter:
            rows = [r for r in rows if r["status"] == self.filter]
        labels = {a["id"]: a["label"].split("@")[0] for a in self.db.accounts()}
        import json as _json
        for r in rows:
            try:
                r["refs_list"] = [x for x in _json.loads(r.get("refs") or "[]") if x]
            except Exception:
                r["refs_list"] = []
            r["outputs"] = self.db.outputs(r["id"]) if r["status"] == "done" else []
            r["acc"] = labels.get(r.get("account_id"), "")
            r["draft"] = False
        drafts = []
        if self.filter in (None, "draft"):
            drafts = [{"id": f"draft:{i}", "row_no": i + 1, "prompt": p, "status": "draft", "outputs": [], "acc": "",
                       "progress": 0, "draft": True, "index": i, "error_code": None, "error_text": None,
                       "refs_list": list(self.draft_refs.get(p, []))}
                      for i, p in enumerate(self.drafts)]
        rows = drafts + rows
        ids = {r["id"] for r in rows}
        self.checked &= ids
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()
        self.check_changed()

    def rowCount(self, parent=QModelIndex()):
        return len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLS)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if o == Qt.Horizontal and role == Qt.DisplayRole:
            return tr(COLS[s])
        if o == Qt.Horizontal and role == Qt.TextAlignmentRole and s == C_PROMPT:
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    def flags(self, idx):
        f = super().flags(idx)
        if idx.column() == C_CHECK:
            f |= Qt.ItemIsUserCheckable
        if idx.column() == C_PROMPT and self.rows[idx.row()]["status"] not in ("running", "needs_user"):
            f |= Qt.ItemIsEditable
        return f

    def setData(self, idx, value, role=Qt.EditRole):
        r = self.rows[idx.row()]
        if role == Qt.CheckStateRole and idx.column() == C_CHECK:
            if Qt.CheckState(value) == Qt.Checked:
                self.checked.add(r["id"])
            else:
                self.checked.discard(r["id"])
            self.dataChanged.emit(idx, idx)
            self.check_changed()
            return True
        if role == Qt.EditRole and idx.column() == C_PROMPT:
            text = " ".join(str(value).split())
            if not text or text == r["prompt"]:
                return False
            if r["draft"]:
                if self.on_draft_edit:
                    self.on_draft_edit(r["index"], text)
                self.drafts[r["index"]] = text
            else:
                self.db.update_job(r["id"], prompt=text)
            r["prompt"] = text
            self.dataChanged.emit(idx, idx)
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
        if role == Qt.CheckStateRole and c == C_CHECK:
            return Qt.Checked if r["id"] in self.checked else Qt.Unchecked
        if role in (Qt.DisplayRole, Qt.EditRole):
            if c == C_NO:
                return str(idx.row() + 1)
            if c == C_PROMPT:
                return r["prompt"].replace("\n", " ")

        if role == Qt.ToolTipRole:
            if c == C_PROMPT:
                return r["prompt"] + ("\n\n" + tr("Bấm để sửa prompt của riêng tác vụ này") if c == C_PROMPT else "")
            if c == C_STATUS:
                if r["status"] in ("failed", "blocked"):
                    return friendly(r["error_code"]) + (f"\n\n{r['error_text']}" if r.get("error_text") else "")
                if r["status"] == "queued" and r.get("error_code"):
                    return tr("Đang chờ chạy lại (tự chuyển sang tài khoản khác)")
                if r["status"] == "running":
                    return f"{r['progress']}%"
            if c == C_RES and r["outputs"]:
                return tr("Bấm để xem lớn") + "\n" + "\n".join(o["path"] for o in r["outputs"])
            if c == C_REFS:
                n = len(r.get("refs_list") or [])
                base = (tr("Ảnh tham chiếu của riêng tác vụ này") + f" ({n})") if n else tr("Chưa có ảnh tham chiếu riêng")
                if r["status"] not in ("running", "needs_user"):
                    base += "\n" + tr("Bấm để thêm / đổi ảnh cho tác vụ này")
                return base
            if c == C_DIR and r["outputs"]:
                return tr("Mở thư mục chứa kết quả") + "\n" + str(Path(r["outputs"][0]["path"]).parent)
        if role == Qt.TextAlignmentRole and c in (C_NO,):
            return Qt.AlignCenter

        if role == Qt.ForegroundRole and c == C_PROMPT and r["draft"]:
            return QColor("#c7d2fe")
        if role == Qt.UserRole:
            return r
        return None

    # ----- ảnh xem trước -----
    def thumbs(self, r: dict) -> list[tuple[QPixmap | None, str]]:
        out = []
        for o in r["outputs"][:4]:
            p = o["path"]
            if p in self._pix:
                out.append((self._pix[p], o["kind"]))
                continue
            pm = None
            if o["kind"] == "image":
                q = QPixmap(p)
                if not q.isNull():
                    pm = q.scaled(QSize(RES_W * 2, ROW_H * 2), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    self._pix[p] = pm
            else:
                tf = video_thumb_file(p)
                if tf.exists():
                    pm = QPixmap(str(tf))
                    self._pix[p] = pm
                elif p not in self._pending and Path(p).exists():
                    self._pending.add(p)
                    QThreadPool.globalInstance().start(_ThumbJob(p, str(tf), self._sig))
            out.append((pm, o["kind"]))
        return out

    def ref_pix(self, path: str, size: int) -> QPixmap | None:
        key = f"ref:{size}:{path}"
        if key not in self._pix:
            q = QPixmap(path)
            if q.isNull():
                return None
            self._pix[key] = q.scaled(QSize(size * 2, size * 2), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        return self._pix[key]

    def _thumb_ready(self, src):
        self._pending.discard(src)
        for i, r in enumerate(self.rows):
            if any(o["path"] == src for o in r["outputs"]):
                ix = self.index(i, C_RES)
                self.dataChanged.emit(ix, ix)


def _cover(pm: QPixmap, w: float, h: float) -> QRectF:
    sw, sh = pm.width(), pm.width() * h / max(1, w)
    if sh > pm.height():
        sh = pm.height()
        sw = sh * w / max(1, h)
    return QRectF((pm.width() - sw) / 2, (pm.height() - sh) / 2, sw, sh)


class TaskDelegate(QStyledItemDelegate):
    def createEditor(self, parent, opt, idx):
        e = QLineEdit(parent)
        e.setStyleSheet(f"QLineEdit{{background:{C['input-bg']};border:1px solid {C['accent']};border-radius:3px;padding:4px 6px;}}")
        return e

    def paint(self, p: QPainter, opt, idx):
        c = idx.column()
        if c not in (C_RES, C_STATUS, C_DIR, C_REFS):
            return super().paint(p, opt, idx)
        r = idx.data(Qt.UserRole)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(opt.rect)
        if c == C_RES:
            box = QRectF(rect.left() + 4, rect.top() + 5, rect.width() - 8, rect.height() - 10)
            thumbs = idx.model().thumbs(r) if r["outputs"] else []
            if thumbs:
                n = len(thumbs)
                cells = []
                if n == 1:
                    cells = [box]
                elif n == 2:
                    w = (box.width() - 3) / 2
                    cells = [QRectF(box.left(), box.top(), w, box.height()), QRectF(box.left() + w + 3, box.top(), w, box.height())]
                else:
                    w, h = (box.width() - 3) / 2, (box.height() - 3) / 2
                    cells = [QRectF(box.left() + (k % 2) * (w + 3), box.top() + (k // 2) * (h + 3), w, h) for k in range(n)]
                for (pm, kind), cell in zip(thumbs, cells):
                    path = QPainterPath()
                    path.addRoundedRect(cell, 3, 3)
                    if pm is not None and not pm.isNull():
                        p.setClipPath(path)
                        p.drawPixmap(cell, pm, _cover(pm, cell.width(), cell.height()))
                        p.setClipping(False)
                    else:
                        p.fillPath(path, QColor("#1a1f45"))
                    if kind == "video":
                        s = 14 if n > 1 else 18
                        p.drawPixmap(int(cell.center().x() - s / 2), int(cell.center().y() - s / 2), icon_pixmap("play", "#ffffff", s))
                if len(r["outputs"]) > 4:
                    p.setPen(QColor("white"))
                    p.drawText(box, Qt.AlignRight | Qt.AlignBottom, f"+{len(r['outputs']) - 4} ")
            else:
                path = QPainterPath()
                path.addRoundedRect(box, 4, 4)
                bg = {"failed": "#2a1426", "blocked": "#2a1426"}.get(r["status"], "#141a4a" if r["draft"] else "#1a1f45")
                p.fillPath(path, QColor(bg))
                if r["status"] == "running":
                    p.setPen(QColor(C["info"]))
                    p.drawText(box, Qt.AlignCenter, f"{r['progress']}%")
                    bar = QRectF(box.left() + 10, box.bottom() - 10, (box.width() - 20) * r["progress"] / 100, 3)
                    bp = QPainterPath()
                    bp.addRoundedRect(bar, 1.5, 1.5)
                    p.fillPath(bp, gradient(box, ["#22d3ee", "#6366f1", "#d946ef"]))
        elif c == C_REFS:
            refs = r.get("refs_list") or []
            editable = r["status"] not in ("running", "needs_user")
            sz = 30
            n_show = min(len(refs), 3 if editable else 4)
            total_w = n_show * (sz + 3) + ((sz) if editable else 0)
            x = rect.center().x() - total_w / 2
            y = rect.center().y() - sz / 2
            for k in range(n_show):
                cell = QRectF(x + k * (sz + 3), y, sz, sz)
                path = QPainterPath()
                path.addRoundedRect(cell, 3, 3)
                pm = idx.model().ref_pix(refs[k], sz)
                if pm is not None:
                    p.setClipPath(path)
                    p.drawPixmap(cell, pm, _cover(pm, sz, sz))
                    p.setClipping(False)
                else:
                    p.fillPath(path, QColor("#1a1f45"))
                p.setPen(QColor(255, 255, 255, 60))
                p.drawPath(path)
            if len(refs) > n_show:
                f = QFont(opt.font)
                f.setPointSizeF(7.5)
                f.setBold(True)
                p.setFont(f)
                p.setPen(QColor("white"))
                last = QRectF(x + (n_show - 1) * (sz + 3), y, sz, sz)
                p.fillRect(last, QColor(0, 0, 0, 120))
                p.drawText(last, Qt.AlignCenter, f"+{len(refs) - n_show + 1}")
            if editable:
                cell = QRectF(x + n_show * (sz + 3), y, sz, sz)
                path = QPainterPath()
                path.addRoundedRect(cell, 3, 3)
                pen = QColor("#67e8f9")
                pen.setAlpha(170)
                from PySide6.QtGui import QPen
                p.setPen(QPen(pen, 1.2, Qt.DashLine))
                p.drawPath(path)
                p.drawPixmap(int(cell.center().x() - 8), int(cell.center().y() - 8), icon_pixmap("plus", "#67e8f9", 16))
        elif c == C_DIR:
            if r["outputs"]:
                ic = icon_pixmap("folder", "#67e8f9", 20)
                p.drawPixmap(int(rect.center().x() - 10), int(rect.center().y() - 10), ic)
        else:
            text, fg, bg = STATUS.get(r["status"], STATUS["queued"])
            text = tr(text)
            f = QFont(opt.font)
            f.setPointSizeF(8.4)
            f.setBold(True)
            p.setFont(f)
            w = p.fontMetrics().horizontalAdvance(text) + 18
            pr = QRectF(rect.right() - w - 8, rect.center().y() - 11, w, 22)
            pp = QPainterPath()
            pp.addRoundedRect(pr, 5.5, 5.5)
            p.fillPath(pp, QColor(C[bg]))
            p.setPen(QColor(C[fg]))
            p.drawText(pr, Qt.AlignCenter, text)
        p.restore()

    def sizeHint(self, opt, idx):
        return QSize(120, ROW_H)


class TaskTable(QTableView):
    action = Signal(str, dict)   # menu | view | folder | refs

    def __init__(self, model: TaskModel):
        super().__init__()
        self.setModel(model)
        self.setItemDelegate(TaskDelegate(self))
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ROW_H)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.ElideRight)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed)
        h = self.horizontalHeader()
        h.setHighlightSections(False)
        for i, w in enumerate([32, 34, RES_W + 8, 0, REFS_W, 64, 118]):
            if w:
                h.resizeSection(i, w)
                h.setSectionResizeMode(i, QHeaderView.Fixed)
        h.setSectionResizeMode(C_PROMPT, QHeaderView.Stretch)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda pos: self._emit("menu", self.indexAt(pos)))
        self.clicked.connect(self._clicked)
        self.setAccessibleName(tr("Danh sách tác vụ"))
        self.setMouseTracking(True)

    def mouseMoveEvent(self, e):
        ix = self.indexAt(e.position().toPoint())
        r = ix.data(Qt.UserRole) if ix.isValid() else None
        clickable = ix.isValid() and ((ix.column() in (C_RES, C_DIR) and r and r["outputs"]) or
                                      (ix.column() == C_REFS and r and r["status"] not in ("running", "needs_user")) or
                                      (ix.column() == C_PROMPT and r and r["status"] not in ("running", "needs_user")))
        self.viewport().setCursor(Qt.IBeamCursor if clickable and ix.column() == C_PROMPT else
                                  Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        super().mouseMoveEvent(e)

    def _clicked(self, ix):
        if not ix.isValid():
            return
        r = ix.data(Qt.UserRole)
        col = ix.column()
        if col == C_PROMPT:
            if self.model().flags(ix) & Qt.ItemIsEditable:
                self.edit(ix)
            return
        if col == C_RES and r["outputs"]:
            self.action.emit("view", r)
            return
        if col == C_DIR and r["outputs"]:
            self.action.emit("folder", r)
            return
        if col == C_REFS:
            if r["status"] not in ("running", "needs_user"):
                self.action.emit("refs", r)
            return
        if col != C_CHECK:   # bấm vào phần còn lại của dòng: tick / bỏ tick
            m = self.model()
            cur = m.data(m.index(ix.row(), 0), Qt.CheckStateRole)
            m.setData(m.index(ix.row(), 0), Qt.Unchecked if cur == Qt.Checked else Qt.Checked, Qt.CheckStateRole)

    def _emit(self, kind, ix):
        if ix.isValid():
            self.action.emit(kind, ix.data(Qt.UserRole))
