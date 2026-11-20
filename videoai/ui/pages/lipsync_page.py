"""Video Lip-Sync: video gốc + ảnh nhân vật → nhân vật trong ảnh nói / cử động y chang video gốc.

Chạy trên Google Flow (Video › Thành phần, model Omni 1.2 Flash) với prompt cố định (adapters/lipsync_prompt.py).
- Mỗi tác vụ = 1 video gốc + 1 ảnh nhân vật. Kéo thả nhiều tệp: tự ghép theo tên trùng nhau, còn lại theo thứ tự.
- Thời lượng 3–15 giây (mặc định 10): lấy đoạn 0 → N giây của video gốc.
- Giữ tiếng gốc: ghép lại tiếng của video gốc vào kết quả.
- Gói Miễn phí: mỗi lần 1 tác vụ; chạy xong phải chờ 10 phút mới chạy tiếp (có thông báo nâng cấp PRO).
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .flow_page import DELAY, Seg
from .gen_page import open_path, reveal
from ..theme import C, icon_pixmap
from ..widgets import Card, GradientBar, PathPicker, StatCard, button, field, icon_button, label
from ...core.errors import friendly
from ...core.i18n import tr
from ...core.paths import default_output_dir
from ...core.platforms import PageDef
from ...media import lipsync as LS

FREE_COOLDOWN = 10 * 60          # gói Miễn phí: chờ 10 phút sau mỗi tác vụ Lip-Sync đã chạy xong
TICKS = (3, 5, 8, 10, 12, 15)
VID_FILTER = "Video (*.mp4 *.mov *.webm *.mkv *.m4v *.avi)"
IMG_FILTER = "Ảnh (*.png *.jpg *.jpeg *.webp)"
TH_W, TH_H = 150, 96
STATUS = {"draft": ("Chưa chạy", "#a5b4fc", "#1c2453"), "queued": ("Đang chờ", "#fbbf24", "#2e2410"),
          "running": ("Đang chạy", "#60a5fa", "#0f2547"), "needs_user": ("Cần xác minh", "#fbbf24", "#2e2410"),
          "done": ("Hoàn thành", "#4ade80", "#0f2e24"), "failed": ("Lỗi", "#fb7185", "#3a1520"),
          "blocked": ("Bị chặn", "#fb7185", "#3a1520"), "cancelled": ("Đã hủy", "#94a3b8", "#1c2453"),
          "paused": ("Tạm dừng", "#fbbf24", "#2e2410")}


def _fmt(sec: float) -> str:
    sec = max(0, int(round(sec)))
    return f"{sec // 60}:{sec % 60:02d}"


class Ticks(QWidget):
    """Các mốc thời gian dưới thanh trượt, đặt đúng vị trí trên thanh; mốc đang chọn sáng màu."""

    def __init__(self, lo: int, hi: int, marks=TICKS):
        super().__init__()
        self.lo, self.hi, self.marks, self.cur = lo, hi, marks, None
        self.setFixedHeight(16)

    def set_current(self, v):
        self.cur = v
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        f = QFont(self.font())
        f.setPixelSize(10)
        hw = 9
        for v in self.marks:
            x = hw + (self.width() - 2 * hw) * (v - self.lo) / (self.hi - self.lo)
            f.setBold(v == self.cur)
            p.setFont(f)
            p.setPen(QColor("#67e8f9" if v == self.cur else "#7f8bc4"))
            p.drawText(QRectF(x - 14, 0, 28, 16), Qt.AlignCenter, f"{v}s")
        p.end()


class LipSyncPage(QWidget):
    def __init__(self, ctx, pdef: PageDef):
        super().__init__()
        self.ctx, self.db, self.pdef, self.key = ctx, ctx.db, pdef, pdef.key
        st = self.db.get_setting(f"page_{self.key}", {}) or {}
        self.drafts: list[dict] = [d for d in st.get("drafts", []) if isinstance(d, dict)]
        self.rows: list[dict] = []
        self.checked: set[str] = set()
        self._thumbs: dict[str, QPixmap] = {}
        self._durs: dict[str, float] = {}
        self._dirty = True
        self._build(st)
        ctx.engine.job_updated.connect(lambda _: setattr(self, "_dirty", True))
        self._timer = QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ================================================================ giao diện
    def _build(self, st: dict):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(12)
        sr = QHBoxLayout()
        sr.setSpacing(10)
        self.cards = {k: StatCard(k) for k in ("running", "queued", "done", "failed", "accounts")}
        self.cards["accounts"].findChildren(QLabel)[-1].setText(tr("Tài khoản sẵn sàng"))
        for k, cw in self.cards.items():
            cw.clicked.connect(self._stat_click)
            sr.addWidget(cw)
        root.addLayout(sr)
        pr = QHBoxLayout()
        self.bar = GradientBar()
        self.bar_lbl = label("0 / 0", "faint")
        pr.addWidget(self.bar, 1)
        pr.addWidget(self.bar_lbl)
        root.addLayout(pr)
        cols = QHBoxLayout()
        cols.setSpacing(14)
        root.addLayout(cols, 1)

        # ---------- trái
        lw = QWidget()
        lw.setFixedWidth(420)
        left = QVBoxLayout(lw)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)
        cfg = Card("Cấu hình Lip-sync", "sliders")
        lo, hi, dv = self.pdef.extra.get("lipsync_secs", (3, 15, 10))
        dbox = QWidget()
        dl = QVBoxLayout(dbox)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(4)
        self.dur_lbl = QLabel()
        self.dur_lbl.setObjectName("fieldLabel")
        self.dur = QSlider(Qt.Horizontal)
        self.dur.setRange(lo, hi)
        self.dur.setTickPosition(QSlider.TicksBelow)
        self.dur.setTickInterval(1)
        self.ticks = Ticks(lo, hi)
        self.dur.valueChanged.connect(self._dur_changed)
        dl.addWidget(self.dur_lbl)
        dl.addWidget(self.dur)
        dl.addWidget(self.ticks)
        cfg.add(dbox)
        self.ratio = Seg([tr(r) for r in self.pdef.ratios], tr(st.get("ratio") or self.pdef.ratios[0]))
        cfg.add(field("Tỷ lệ khung hình", self.ratio))
        self.quality = Seg(self.pdef.extra["quality"], st.get("quality") or "1080p")
        cfg.add(field("Chất lượng tải về", self.quality))
        self.count = Seg(["1", "2", "3", "4"], str(st.get("count") or 1))
        cfg.add(field("Số lượng kết quả", self.count))
        self.keep_audio = QCheckBox(tr("Giữ nguyên tiếng gốc của video (ghép lại sau khi tạo)"))
        self.keep_audio.setChecked(bool(st.get("keep_audio", True)))
        cfg.add(self.keep_audio)
        self.out = PathPicker(st.get("save_dir") or str(default_output_dir() / "lipsync"))
        cfg.add(field("Thư mục lưu kết quả", self.out))
        left.addWidget(cfg)
        self.dur.setValue(int(st.get("secs") or dv))
        self._dur_changed(self.dur.value())

        add = Card("Thêm Video gốc + Ảnh nhân vật", "upload", icon_color="#86efac")
        r1 = QHBoxLayout()
        b_v = button("Video gốc", "primary", "video")
        b_v.clicked.connect(self.add_videos)
        b_i = button("Ảnh nhân vật", "primary", "image")
        b_i.clicked.connect(self.add_images)
        r1.addWidget(b_v)
        r1.addWidget(b_i)
        add.add(r1)
        r2 = QHBoxLayout()
        b_lib = button("Ảnh từ Kho tham chiếu", "chip", "library", "#f9a8d4")
        b_lib.clicked.connect(self.add_from_library)
        b_dir = button("Thêm cả thư mục", "chip", "folder", "#67e8f9")
        b_dir.clicked.connect(self.add_folder)
        r2.addWidget(b_lib)
        r2.addWidget(b_dir)
        add.add(r2)
        n = label("Kéo thả nhiều video + ảnh vào danh sách: tools tự ghép cặp theo thứ tự (hoặc theo tên tệp trùng nhau). "
                  "Video gốc dài hơn thời lượng đã chọn sẽ lấy đúng đoạn đó; ngắn hơn thì dùng hết video.", "faint")
        n.setWordWrap(True)
        add.add(n)
        left.addWidget(add)
        left.addStretch()
        # banner gói Miễn phí (chờ 10 phút + mời nâng cấp)
        self.free_box = QFrame()
        self.free_box.setStyleSheet("QFrame{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #3b1d0a,stop:1 #3a1240);"
                                    "border:1px solid #f59e0b;border-radius:8px;}QLabel{background:transparent;border:none;}")
        fv = QVBoxLayout(self.free_box)
        fv.setContentsMargins(12, 10, 12, 10)
        fv.setSpacing(6)
        self.free_t1 = QLabel()
        self.free_t1.setWordWrap(True)
        self.free_t1.setStyleSheet("color:#fbbf24;font-weight:800;font-size:13px;")
        self.free_t2 = QLabel(tr("Bản PRO chạy Lip-Sync hàng loạt, song song nhiều tài khoản – không phải chờ. "
                                 "Nâng cấp ngay để dùng Full tính năng!"))
        self.free_t2.setWordWrap(True)
        self.free_t2.setStyleSheet("color:#fde68a;font-size:11.5px;")
        b_up = button("Nâng cấp PRO – dùng Full tính năng", "primary", "shield")
        b_up.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #f59e0b,stop:1 #db2777);"
                           "color:white;font-weight:800;padding:8px;border-radius:6px;}")
        b_up.clicked.connect(lambda: self.ctx.win.open_license())
        fv.addWidget(self.free_t1)
        fv.addWidget(self.free_t2)
        fv.addWidget(b_up)
        self.free_box.hide()
        left.addWidget(self.free_box)
        runr = QHBoxLayout()
        self.b_start = button("Bắt đầu", "start", "play")
        self.b_start.clicked.connect(self.start)
        b_pause = button("Tạm dừng", "pause", "pause", "#fbbf24")
        b_pause.clicked.connect(lambda: self.ctx.engine.pause_page(self.key))
        b_stop = button("Dừng", "stop", "stop", C["danger"])
        b_stop.clicked.connect(self._stop)
        runr.addWidget(self.b_start)
        runr.addWidget(b_pause)
        runr.addWidget(b_stop)
        left.addLayout(runr)
        cols.addWidget(lw)

        # ---------- phải: danh sách tác vụ
        right = QFrame()
        right.setObjectName("card")
        right.setAcceptDrops(True)
        right.dragEnterEvent = lambda e: e.acceptProposedAction() if e.mimeData().hasUrls() else None
        right.dragMoveEvent = lambda e: e.acceptProposedAction() if e.mimeData().hasUrls() else None
        right.dropEvent = self._drop
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        tb = QHBoxLayout()
        tb.setContentsMargins(10, 10, 10, 10)
        tb.setSpacing(5)
        self.all_cb = QCheckBox()
        self.all_cb.clicked.connect(self._check_all)
        tb.addWidget(self.all_cb)
        tb.addWidget(label("Tác vụ Lip-Sync", "h2"))
        self.sel_lbl = label("", "faint")
        tb.addWidget(self.sel_lbl)
        tb.addStretch()
        for text, kind, ic, col, fn in (("Đổi video", "chip", "video", "#67e8f9", lambda: self._swap("video")),
                                        ("Đổi ảnh", "chip", "image", "#f9a8d4", lambda: self._swap("image")),
                                        ("Xóa", "stop", "trash", C["danger"], self._delete_checked),
                                        ("Chạy", "chip", "play", "#4ade80", self.run_selected)):
            b = button(text, kind, ic, col)
            if kind == "stop":
                b.setStyleSheet(f"QPushButton{{padding:5px 9px;background:{C['danger-bg']};border:1px solid #62202f;"
                                f"color:{C['danger']};}}")
            b.clicked.connect(fn)
            tb.addWidget(b)
        for ic, tip, fn in (("retry", "Chạy lại tất cả tác vụ lỗi", self._retry),
                            ("folder", "Mở thư mục lưu", lambda: open_path(self._out_dir()))):
            b = icon_button(ic, tip, "#67e8f9")
            b.setFixedSize(32, 30)
            b.clicked.connect(fn)
            tb.addWidget(b)
        rv.addLayout(tb)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{C['border']};")
        rv.addWidget(line)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["", "#", tr("VIDEO GỐC"), tr("ẢNH NHÂN VẬT"), tr("KẾT QUẢ"), tr("THƯ MỤC"),
                                              tr("TRẠNG THÁI")])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(TH_H + 8)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.table.horizontalHeader()
        for c, w in enumerate((36, 40, TH_W + 20, TH_W + 4, TH_W + 20, 80)):
            self.table.setColumnWidth(c, w)
        h.setSectionResizeMode(6, QHeaderView.Stretch)
        self.table.cellClicked.connect(self._cell_clicked)
        rv.addWidget(self.table, 1)
        self.empty = label("Chưa có tác vụ nào.\nBấm \"Video gốc\" và \"Ảnh nhân vật\" (hoặc kéo thả tệp vào đây) – "
                           "mỗi video gốc + một ảnh nhân vật = 1 tác vụ.", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)
        rv.addWidget(self.empty, 1)
        cols.addWidget(right, 1)

    # ================================================================ tiện ích
    def _dur_changed(self, v):
        self.dur_lbl.setText(tr("Thời lượng") + f" · {v} " + tr("giây") + f"  ({tr('lấy')} 0:00 → {_fmt(v)} "
                             + tr("của video gốc") + ")")
        self.ticks.set_current(v if v in TICKS else None)
        self._save_state()
        self._dirty = True

    def _out_dir(self) -> str:
        d = self.out.text() or str(default_output_dir() / "lipsync")
        Path(d).mkdir(parents=True, exist_ok=True)
        return d

    def _ratio_key(self) -> str:
        i = [tr(r) for r in self.pdef.ratios].index(self.ratio.value()) if self.ratio.value() in [tr(r) for r in self.pdef.ratios] else 0
        return self.pdef.ratios[i]

    def _save_state(self):
        if not hasattr(self, "out"):
            return
        self.db.set_setting(f"page_{self.key}", {
            "drafts": self.drafts, "secs": self.dur.value(), "ratio": self._ratio_key(), "quality": self.quality.value(),
            "count": int(self.count.value()), "keep_audio": self.keep_audio.isChecked(), "save_dir": self.out.text()})

    def _is_free(self) -> bool:
        win = self.ctx.win
        return hasattr(win, "is_pro") and not win.is_pro()

    def _accounts(self) -> tuple[list[str], int]:
        accs = [a for a in self.db.accounts("flow") if a["enabled"]]
        ready = [a["id"] for a in accs if a["status"] in ("ok", "unknown", "needs_user")]
        return ready, sum(1 for a in accs if a["status"] == "ok")

    # ---- gói Miễn phí: 1 tác vụ, chờ 10 phút
    def cooldown_left(self) -> int:
        if not self._is_free():
            return 0
        row = self.db.one("SELECT MAX(j.finished_at) t FROM jobs j JOIN batches b ON b.id=j.batch_id"
                          " WHERE b.page=? AND j.status='done'", (self.key,))
        if not row or not row["t"]:
            return 0
        try:
            done = datetime.fromisoformat(str(row["t"]).replace("Z", "+00:00"))
            now = datetime.now(done.tzinfo) if done.tzinfo else datetime.now()
            return max(0, int(FREE_COOLDOWN - (now - done).total_seconds()))
        except Exception:
            return 0

    def _busy(self) -> int:
        row = self.db.one("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','running','needs_user')")
        return int(row["n"]) if row else 0

    def _free_guard(self, n_new: int) -> bool:
        if not self._is_free():
            return True
        detail = tr("Gói Miễn phí: Video Lip-Sync mỗi lần chỉ chạy 1 tác vụ, chạy xong phải chờ 10 phút mới chạy tiếp. "
                    "Bản PRO chạy hàng loạt, song song nhiều tài khoản – không phải chờ.")
        left = self.cooldown_left()
        if left:
            self.ctx.win.upsell(tr("Còn") + f" {_fmt(left)} " + tr("nữa mới chạy được tác vụ Lip-Sync tiếp theo."), detail)
            return False
        if self._busy():
            self.ctx.win.upsell(tr("Đang có 1 tác vụ chạy. Chờ tác vụ này xong rồi tạo tác vụ tiếp theo."), detail)
            return False
        if n_new > 1:
            self.ctx.win.upsell(tr("Gói Miễn phí chỉ tạo 1 tác vụ mỗi lần") + f" ({tr('đang có')} {n_new}).", detail)
            return False
        return True

    def _free_ui(self):
        free = self._is_free()
        left = self.cooldown_left() if free else 0
        self.free_box.setVisible(bool(left))
        if left:
            self.free_t1.setText("⏳  " + tr("Gói Miễn phí: chờ") + f" {_fmt(left)} " + tr("để chạy tác vụ Lip-Sync tiếp theo"))
            self.b_start.setText(tr("Chờ") + f" {_fmt(left)}")
        else:
            self.b_start.setText(tr("Bắt đầu"))

    # ================================================================ thêm tệp
    def _add_pairs(self, pairs: list[tuple[str | None, str | None]]):
        for v, i in pairs:
            if v and i is None:                     # chỉ có video: gắn vào dòng nháp đang thiếu video trước
                d = next((d for d in self.drafts if not d.get("video")), None)
                if d:
                    d["video"] = v
                    continue
            if i and v is None:                     # chỉ có ảnh: gắn vào dòng nháp đang thiếu ảnh trước
                d = next((d for d in self.drafts if not d.get("image")), None)
                if d:
                    d["image"] = i
                    continue
            self.drafts.append({"video": v, "image": i})
        self._save_state()
        self._dirty = True
        self.refresh()

    def add_paths(self, paths: list[str]):
        pairs, rest = LS.pair_files(paths)
        out: list[tuple[str | None, str | None]] = [(v, i) for v, i in pairs]
        out += [(None, i) for i in rest]
        if out:
            self._add_pairs(out)

    def add_videos(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Chọn video gốc"), "", VID_FILTER)
        if fs:
            self._add_pairs([(f, None) for f in fs])

    def add_images(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Chọn ảnh nhân vật"), "", IMG_FILTER)
        if fs:
            self._add_pairs([(None, f) for f in fs])

    def add_from_library(self):
        from ..refs_ui import RefPickerDialog
        d = RefPickerDialog(self, self.ctx.characters, [], max_count=50, title=tr("Ảnh nhân vật từ Kho ảnh tham chiếu"))
        if d.exec():
            paths = self.ctx.characters.paths(d.selected_ids())
            if paths:
                self._add_pairs([(None, p) for p in paths])

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("Chọn thư mục có video gốc + ảnh nhân vật"))
        if d:
            self.add_paths([str(p) for p in sorted(Path(d).iterdir()) if p.is_file()])

    def _drop(self, e):
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.add_paths(paths)
        e.acceptProposedAction()

    # ================================================================ danh sách
    def _jobs(self) -> list[dict]:
        rows = self.db.jobs_for_platform("flow", self.key)
        for r in rows:
            try:
                refs = json.loads(r.get("refs") or "[]")
            except Exception:
                refs = []
            r["video"] = refs[0] if refs else None
            r["image"] = refs[1] if len(refs) > 1 else None
            r["outputs"] = self.db.outputs(r["id"]) if r["status"] == "done" else []
            r["draft"] = False
        return rows

    def refresh(self):
        self._dirty = False
        drafts = [{"id": f"draft:{k}", "draft": True, "index": k, "status": "draft", "video": d.get("video"),
                   "image": d.get("image"), "outputs": [], "progress": 0} for k, d in enumerate(self.drafts)]
        self.rows = drafts + self._jobs()
        ids = {r["id"] for r in self.rows}
        self.checked &= ids
        t = self.table
        t.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            cb = QCheckBox()
            cb.setChecked(r["id"] in self.checked)
            cb.toggled.connect(lambda on, rid=r["id"]: self._check(rid, on))
            hold = QWidget()
            hl = QHBoxLayout(hold)
            hl.setContentsMargins(8, 0, 0, 0)
            hl.addWidget(cb)
            t.setCellWidget(i, 0, hold)
            it = QTableWidgetItem(str(i + 1))
            it.setTextAlignment(Qt.AlignCenter)
            t.setItem(i, 1, it)
            t.setCellWidget(i, 2, self._thumb_label(r.get("video"), "video", tr("Bấm để chọn video gốc")))
            t.setCellWidget(i, 3, self._thumb_label(r.get("image"), "image", tr("Bấm để chọn ảnh nhân vật")))
            t.setCellWidget(i, 4, self._result_cell(r))
            fold = QLabel()
            fold.setAlignment(Qt.AlignCenter)
            if r["outputs"]:
                fold.setPixmap(icon_pixmap("folder", "#67e8f9", 20))
                fold.setToolTip(tr("Mở thư mục chứa kết quả"))
            t.setCellWidget(i, 5, fold)
            t.setCellWidget(i, 6, self._status_cell(r))
        has = bool(self.rows)
        t.setVisible(has)
        self.empty.setVisible(not has)
        self.refresh_stats()
        self._sel_text()

    def _dur(self, path: str) -> float:
        if path not in self._durs:
            self._durs[path] = LS.duration(path)
        return self._durs[path]

    def _thumb(self, path: str | None, kind: str, w: int = TH_W, h: int = TH_H, badge: str | None = None,
               border: str | None = None) -> QPixmap:
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(4, 4, w - 8, h - 8)
        full = QRectF(r)
        src = None
        if path and Path(path).exists():
            key = f"{path}|{kind}"
            if key not in self._thumbs:
                if kind == "image":
                    self._thumbs[key] = QPixmap(path)
                else:
                    from ..task_table import video_thumb_file
                    tf = video_thumb_file(path)
                    if not tf.exists():
                        try:
                            from ...media import ffmpeg
                            ffmpeg.run(["-ss", "0.3", "-i", path, "-frames:v", "1", "-vf", "scale=320:-2", str(tf)])
                        except Exception:
                            pass
                    self._thumbs[key] = QPixmap(str(tf)) if tf.exists() else QPixmap()
            src = self._thumbs[key]
        if src is not None and not src.isNull():
            s = src.scaled(int(r.width()), int(r.height()), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            rr = QRectF(r.center().x() - s.width() / 2, r.center().y() - s.height() / 2, s.width(), s.height())
            path_ = QPainterPath()
            path_.addRoundedRect(rr, 5, 5)
            p.setClipPath(path_)
            p.drawPixmap(rr.topLeft(), s)
            p.setClipping(False)
            r = rr
            if kind == "video":
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 140))
                p.drawEllipse(r.center(), 11, 11)
                p.setBrush(QColor("white"))
                tri = QPainterPath()
                c = r.center()
                tri.moveTo(c.x() - 4, c.y() - 6)
                tri.lineTo(c.x() + 7, c.y())
                tri.lineTo(c.x() - 4, c.y() + 6)
                p.drawPath(tri)
        else:                                            # ô trống: khung nét đứt + dấu +
            p.setPen(QPen(QColor("#3b4fa8"), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(18, 4, -18, -4), 6, 6)
            p.setPen(QPen(QColor("#67e8f9"), 2))
            c = r.center()
            p.drawLine(int(c.x() - 7), int(c.y()), int(c.x() + 7), int(c.y()))
            p.drawLine(int(c.x()), int(c.y() - 7), int(c.x()), int(c.y() + 7))
        if badge:
            f = QFont()
            f.setPixelSize(10)
            f.setBold(True)
            p.setFont(f)
            bw = max(32, p.fontMetrics().horizontalAdvance(badge) + 8)
            br = QRectF(min(r.right() - bw - 2, full.right() - bw) if r.width() >= bw + 4 else full.center().x() - bw / 2,
                        r.bottom() - 16, bw, 14)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(br, 4, 4)
            p.setPen(QColor("white"))
            p.drawText(br, Qt.AlignCenter, badge)
        if border:
            p.setPen(QPen(QColor(border), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 5, 5)
        p.end()
        return pm

    def _thumb_label(self, path, kind, empty_tip):
        lab = QLabel()
        lab.setAlignment(Qt.AlignCenter)
        badge = None
        if kind == "video" and path and Path(path).exists():
            d = self._dur(path)
            secs = self.dur.value()
            badge = f"{_fmt(d)}✂{secs}s" if d > secs + 0.4 else _fmt(d)
        lab.setPixmap(self._thumb(path, kind, badge=badge))
        lab.setToolTip(path or empty_tip)
        lab.setCursor(Qt.PointingHandCursor)
        return lab

    def _result_cell(self, r):
        lab = QLabel()
        lab.setAlignment(Qt.AlignCenter)
        if r["outputs"]:
            o = r["outputs"][0]
            lab.setPixmap(self._thumb(o["path"], "video", badge=_fmt(self._dur(o["path"])), border="#22c55e"))
            lab.setToolTip(tr("Bấm để xem lớn"))
            lab.setCursor(Qt.PointingHandCursor)
        elif r["status"] in ("running", "needs_user"):
            pm = QPixmap(TH_W, TH_H)
            pm.fill(Qt.transparent)
            p = QPainter(pm)
            p.setRenderHint(QPainter.Antialiasing)
            rr = QRectF(TH_W / 2 - 20, TH_H / 2 - 20, 40, 40)
            p.setPen(QPen(QColor(255, 255, 255, 50), 6))
            p.drawEllipse(rr)
            p.setPen(QPen(QColor("#22d3ee"), 6, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rr, 90 * 16, -int(360 * 16 * max(0.03, (r.get("progress") or 0) / 100)))
            p.end()
            lab.setPixmap(pm)
        return lab

    def _status_cell(self, r):
        txt, fg, bg = STATUS.get(r["status"], (r["status"], "#94a3b8", "#1c2453"))
        txt = tr(txt)
        if r["status"] == "running":
            txt += f" {r.get('progress') or 0}%"
        if r["draft"] and not (r.get("video") and r.get("image")):
            txt, fg = tr("Thiếu video gốc") if not r.get("video") else tr("Thiếu ảnh nhân vật"), "#fbbf24"
        sl = QLabel(txt)
        sl.setAlignment(Qt.AlignCenter)
        sl.setStyleSheet(f"color:{fg};background:{bg};border-radius:4px;padding:5px 10px;font-weight:700;font-size:11px;")
        if r["status"] in ("failed", "blocked"):
            sl.setToolTip(friendly(r.get("error_code")) + (f"\n\n{r['error_text']}" if r.get("error_text") else ""))
        hold = QWidget()
        hh = QHBoxLayout(hold)
        hh.addStretch()
        hh.addWidget(sl)
        hh.addStretch()
        return hold

    def _cell_clicked(self, i, c):
        if not (0 <= i < len(self.rows)):
            return
        r = self.rows[i]
        if c in (2, 3) and r["draft"]:
            kind = "video" if c == 2 else "image"
            f, _ = QFileDialog.getOpenFileName(self, tr("Chọn video gốc") if kind == "video" else tr("Chọn ảnh nhân vật"),
                                               "", VID_FILTER if kind == "video" else IMG_FILTER)
            if f:
                self.drafts[r["index"]][kind] = f
                self._save_state()
                self.refresh()
        elif c == 4 and r["outputs"]:
            from ..viewer import MediaViewer
            MediaViewer(self, r["outputs"], Path(r.get("video") or "").name).exec()
        elif c == 5 and r["outputs"]:
            reveal(r["outputs"][0]["path"])

    def _check(self, rid, on):
        (self.checked.add if on else self.checked.discard)(rid)
        self._sel_text()

    def _check_all(self, on):
        self.checked = {r["id"] for r in self.rows} if on else set()
        self.refresh()

    def _sel_text(self):
        n = len(self.checked)
        self.sel_lbl.setText(f"· {tr('đã chọn')} {n}" if n else "")
        self.all_cb.setChecked(bool(self.rows) and n == len(self.rows))

    def _checked_rows(self) -> list[dict]:
        return [r for r in self.rows if r["id"] in self.checked]

    def _swap(self, kind):
        rows = [r for r in self._checked_rows() if r["draft"]]
        if not rows:
            return self.ctx.toast("info", tr("Tick chọn tác vụ chưa chạy để đổi") + " " +
                                  (tr("video gốc") if kind == "video" else tr("ảnh nhân vật")) + ".")
        f, _ = QFileDialog.getOpenFileName(self, tr("Chọn video gốc") if kind == "video" else tr("Chọn ảnh nhân vật"),
                                           "", VID_FILTER if kind == "video" else IMG_FILTER)
        if f:
            for r in rows:
                self.drafts[r["index"]][kind] = f
            self._save_state()
            self.refresh()

    def _delete_checked(self):
        rows = self._checked_rows()
        if not rows:
            return self.ctx.toast("info", tr("Tick chọn tác vụ cần xóa (hoặc ô chọn tất cả ở đầu danh sách)."))
        running = [r for r in rows if r["status"] in ("running", "needs_user")]
        if QMessageBox.question(self, tr("Xóa tác vụ"), tr("Xóa") + f" {len(rows) - len(running)} " + tr("tác vụ khỏi danh sách?") +
                                ("\n" + tr("(Tác vụ đang chạy sẽ không bị xóa.)") if running else "") +
                                "\n" + tr("Tệp kết quả đã tải về vẫn được giữ.")) != QMessageBox.Yes:
            return
        drop = {r["index"] for r in rows if r["draft"]}
        self.drafts = [d for k, d in enumerate(self.drafts) if k not in drop]
        for r in rows:
            if not r["draft"] and r["status"] not in ("running", "needs_user"):
                self.db.execute("DELETE FROM jobs WHERE id=?", (r["id"],))
        self.checked.clear()
        self._save_state()
        self.refresh()

    # ================================================================ chạy
    def _params(self) -> dict:
        return {"ratio": self._ratio_key(), "quality": self.quality.value(), "lipsync_secs": self.dur.value(),
                "keep_audio": self.keep_audio.isChecked(), "model": "Omni 1.2 Flash", "resolutions": "720p",
                "timeout_s": 1200}

    def _enqueue(self, drafts: list[dict]) -> int:
        todo = [d for d in drafts if d.get("video") and d.get("image") and Path(d["video"]).exists() and Path(d["image"]).exists()]
        if not todo:
            self.ctx.toast("warn", tr("Mỗi tác vụ cần đủ 1 video gốc và 1 ảnh nhân vật."))
            return 0
        if not self._free_guard(len(todo)):
            return 0
        if not self.ctx.win.ensure_flow_rights():
            return 0
        ready, _ = self._accounts()
        if not ready:
            QMessageBox.information(self, tr("Chưa có tài khoản"),
                                    tr("Chưa có tài khoản Google Flow nào đăng nhập.\nVào Cài Đặt › Tài khoản › Thêm tài khoản "
                                       "rồi đăng nhập trong cửa sổ Chrome hiện ra."))
            return 0
        n_want = int(self.count.value())
        rows = [{"mode": "lipsync", "prompt": f"{Path(d['video']).stem} + {Path(d['image']).stem}",
                 "refs": [d["video"], d["image"]], "count": n_want} for d in todo]
        self.db.create_batch("flow", self.key, self._params(), self._out_dir(), "flat", rows)
        self.ctx.engine.start_page(self.key, ready, 1, DELAY, True)
        self.ctx.toast("info", tr("Đã chạy") + f" {len(rows)} " + tr("tác vụ Lip-Sync"))
        return len(todo)

    def start(self):
        complete = [d for d in self.drafts if d.get("video") and d.get("image")]
        if not complete:
            if not self.drafts:
                self.ctx.toast("warn", tr("Chưa có tác vụ nào. Thêm video gốc + ảnh nhân vật."))
            else:
                self.ctx.toast("warn", tr("Mỗi tác vụ cần đủ 1 video gốc và 1 ảnh nhân vật."))
            return
        if self._enqueue(complete):
            self.drafts = [d for d in self.drafts if d not in complete]
            self._save_state()
            self.refresh()

    def run_selected(self):
        rows = self._checked_rows()
        if not rows:
            return self.ctx.toast("info", tr("Tick chọn các tác vụ muốn chạy."))
        drafts = [self.drafts[r["index"]] for r in rows if r["draft"]]
        if drafts and self._enqueue(drafts):
            self.drafts = [d for d in self.drafts if not any(d is x for x in drafts)]
            self._save_state()
        others = [r for r in rows if not r["draft"]]
        if others:
            self._requeue(others)
        self.checked.clear()
        self.refresh()

    def _requeue(self, rows) -> int:
        todo = [r for r in rows if r["status"] not in ("running", "queued", "needs_user")]
        if not todo or not self._free_guard(len(todo)) or not self.ctx.win.ensure_flow_rights():
            return 0
        for r in todo:
            self.db.update_job(r["id"], status="queued", progress=0, error_code=None, error_text=None, attempts=0)
        ready, _ = self._accounts()
        if ready:
            self.ctx.engine.start_page(self.key, ready, 1, DELAY, True)
        self.refresh()
        return len(todo)

    def _retry(self):
        rows = [r for r in self.rows if r["status"] in ("failed", "blocked", "cancelled")]
        n = self._requeue(rows)
        self.ctx.toast("info", tr("Chạy lại") + f" {n} " + tr("tác vụ"))

    def _stop(self):
        if QMessageBox.question(self, tr("Dừng"), tr("Hủy tất cả tác vụ đang chờ và đang chạy?")) == QMessageBox.Yes:
            self.ctx.engine.stop_page(self.key)

    # ================================================================ cập nhật
    def _stat_click(self, key):
        if key == "accounts":
            self.ctx.win.open_settings()

    def refresh_stats(self):
        c = self.db.counts("flow", self.key)
        g = self.db.counts_all()
        self.cards["running"].set(g.get("running", 0) + g.get("needs_user", 0))
        self.cards["queued"].set(g.get("queued", 0))
        self.cards["done"].set(g.get("done", 0))
        self.cards["failed"].set(g.get("failed", 0) + g.get("blocked", 0))
        self.cards["accounts"].set(self._accounts()[1])
        total = sum(v for k, v in c.items() if k != "cancelled")
        finished = c.get("done", 0) + c.get("failed", 0) + c.get("blocked", 0)
        self.bar.set(finished / total if total else 0)
        self.bar_lbl.setText(f"{finished} / {total}" + (f" · {int(100 * finished / total)}%" if total else ""))
        self.ctx.set_badge(self.key, c.get("running", 0) + c.get("needs_user", 0) + c.get("queued", 0))

    def apply_tier(self):
        self._free_ui()

    def _tick(self):
        if not self.isVisible():
            return
        if self._dirty:
            self.refresh()
        self._free_ui()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()
        self._free_ui()

    def hideEvent(self, e):
        self._save_state()
        super().hideEvent(e)
