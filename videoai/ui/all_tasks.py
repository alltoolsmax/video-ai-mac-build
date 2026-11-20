"""Bấm vào 4 ô đếm (Đang chạy / Hàng đợi / Hoàn thành / Lỗi): xem đúng các tác vụ đó trên MỌI nền tảng."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from .theme import C
from .widgets import button, label
from ..core.errors import friendly
from ..core.i18n import tr
from ..core.platforms import PAGE_BY_KEY

GROUPS = {   # ô đếm → các trạng thái trong CSDL (giống cách ô đếm cộng)
    "running": ("running", "needs_user"),
    "queued": ("queued",),
    "done": ("done",),
    "failed": ("failed", "blocked"),
}
TITLES = {"running": "Tác vụ đang chạy", "queued": "Tác vụ trong hàng đợi", "done": "Tác vụ hoàn thành",
          "failed": "Tác vụ lỗi"}
COLOR = {"running": "#60a5fa", "queued": "#fbbf24", "done": "#4ade80", "failed": "#fb7185"}


def jobs_by_group(db, key: str, limit: int = 2000) -> list[dict]:
    st = GROUPS[key]
    q = ",".join("?" * len(st))
    return db.query(
        "SELECT j.*, b.platform, b.page FROM jobs j JOIN batches b ON b.id=j.batch_id"
        f" WHERE j.status IN ({q}) ORDER BY j.updated_at DESC LIMIT ?", (*st, limit))


def _when(s: str | None) -> str:
    try:
        return datetime.fromisoformat(s).strftime("%d/%m %H:%M")
    except Exception:
        return s or ""


class AllTasksDialog(QDialog):
    def __init__(self, win, key: str):
        super().__init__(win)
        self.win, self.db, self.key = win, win.db, key
        self.setWindowTitle(tr(TITLES[key]) + " · " + tr("tất cả nền tảng"))
        self.resize(1080, 620)
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        head = QHBoxLayout()
        self.title = label("", "h2")
        self.title.setStyleSheet(f"color:{COLOR[key]};")
        head.addWidget(self.title)
        head.addStretch()
        v.addLayout(head)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr("Chức năng"), "#", tr("Prompt"), tr("Trạng thái"), tr("Cập nhật"),
                                              tr("Kết quả")])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setWordWrap(False)
        h = self.table.horizontalHeader()
        for c, mode in enumerate((QHeaderView.ResizeToContents, QHeaderView.ResizeToContents, QHeaderView.Stretch,
                                  QHeaderView.Interactive, QHeaderView.ResizeToContents, QHeaderView.ResizeToContents)):
            h.setSectionResizeMode(c, mode)
        self.table.setColumnWidth(3, 260)
        self.table.cellDoubleClicked.connect(self._open_row)
        v.addWidget(self.table, 1)
        self.hint = label("", "faint")
        v.addWidget(self.hint)
        bar = QHBoxLayout()
        self.b_go = button("Mở ở trang của tác vụ", "chip", "chev_right", "#67e8f9")
        self.b_go.clicked.connect(lambda: self._open_row(self.table.currentRow(), 0, go=True))
        bar.addWidget(self.b_go)
        if key == "done":
            b_view = button("Xem kết quả", "chip", "eye", "#4ade80")
            b_view.clicked.connect(lambda: self._open_row(self.table.currentRow(), 0))
            bar.addWidget(b_view)
        if key == "failed":
            b_retry = button("Chạy lại tác vụ đã chọn", "chip", "retry", "#fbbf24")
            b_retry.clicked.connect(self._retry_selected)
            b_all = button("Chạy lại tất cả tác vụ lỗi", "primary", "retry")
            b_all.clicked.connect(lambda: self._retry(self.rows))
            bar.addWidget(b_retry)
            bar.addWidget(b_all)
        bar.addStretch()
        b_close = button("Đóng", "chip", "x", "#fb7185")
        b_close.clicked.connect(self.accept)
        bar.addWidget(b_close)
        v.addLayout(bar)
        self.reload()

    def reload(self):
        self.rows = jobs_by_group(self.db, self.key)
        self.title.setText(f"{tr(TITLES[self.key])}: {len(self.rows)}")
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            pdef = PAGE_BY_KEY.get(r["page"])
            if r["status"] in ("failed", "blocked"):
                st = friendly(r.get("error_code") or "") if r.get("error_code") else (r.get("error_text") or tr("Lỗi"))
            else:
                st = {"running": tr("Đang chạy") + f" {r.get('progress') or 0}%", "needs_user": tr("Cần xác minh"),
                      "queued": tr("Đang chờ"), "done": tr("Hoàn thành")}.get(r["status"], r["status"])
            n_out = len(self.db.outputs(r["id"])) if r["status"] == "done" else 0
            cells = [tr(pdef.label) if pdef else r["page"], str(r["row_no"]), r["prompt"].replace("\n", " "), st,
                     _when(r.get("updated_at")), str(n_out) if n_out else ""]
            for c, txt in enumerate(cells):
                it = QTableWidgetItem(txt)
                if c in (2, 3):
                    it.setToolTip(r.get("error_text") or txt if c == 3 else txt)
                if c == 3:
                    it.setForeground(QColor(COLOR[self.key]))
                self.table.setItem(i, c, it)
        self.hint.setText(tr("Bấm đúp một dòng để mở") + (" " + tr("kết quả") if self.key == "done" else " " + tr("ở trang của tác vụ"))
                          if self.rows else tr("Không có tác vụ nào."))
        if self.rows:
            self.table.selectRow(0)

    def _selected(self) -> list[dict]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.rows[i] for i in rows if 0 <= i < len(self.rows)]

    def _open_row(self, i: int, _c=0, go: bool = False):
        if not (0 <= i < len(self.rows)):
            return
        r = self.rows[i]
        if self.key == "done" and not go:
            outs = self.db.outputs(r["id"])
            if outs:
                from .viewer import MediaViewer
                MediaViewer(self, outs, r["prompt"]).exec()
                return
        self.accept()
        self.win.show_task(r["page"], r["id"], self.key)

    def _retry_selected(self):
        self._retry(self._selected())

    def _retry(self, rows: list[dict]):
        by_page: dict[str, list[dict]] = {}
        for r in rows:
            by_page.setdefault(r["page"], []).append(r)
        n = 0
        for page, rs in by_page.items():
            pg = self.win.page(page)
            if hasattr(pg, "_requeue"):
                n += pg._requeue(rs)
        self.win.ctx.toast("info", tr("Chạy lại") + f" {n} " + tr("tác vụ"))
        self.reload()
