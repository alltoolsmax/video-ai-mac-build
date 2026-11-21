"""Trang Tạo ảnh Flow / Tạo Video Flow.

- Mỗi dòng prompt = 1 tác vụ.
- Tài khoản: tự dùng mọi tài khoản Flow đã đăng nhập; số tác vụ chạy cùng lúc = số tài khoản (mỗi tài khoản
  một trình duyệt); tài khoản hết tín dụng / bị đăng xuất / lỗi kỹ thuật thì tự chuyển sang tài khoản khác.
- Ảnh tham chiếu chọn từ Kho ảnh tham chiếu, hoặc gõ @Tên trong prompt.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QMenu, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget)

from .gen_page import open_path, reveal
from ..refs_ui import RefStrip
from ..task_table import TaskModel, TaskTable
from ..theme import C, icon
from ..widgets import Card, GradientBar, PromptEditor, StatCard, button, combo, field, icon_button, label
from ..workers import run_bg
from ...core.i18n import tr
from ...core.paths import default_output_dir
from ...core.platforms import PLATFORM_LABELS, PageDef
from ...services import prompt_io

DELAY = (10, 15)   # tài khoản chạy xong 1 tác vụ thì nghỉ 10–15 giây (ngẫu nhiên) rồi mới nhận tác vụ kế tiếp


AI_TIP = "AI Agent: tự động sửa các prompt có sẵn trong ô nhập (mỗi dòng một prompt)"

class Seg(QWidget):
    """Nhóm nút chọn trực quan (1 2 3 4, 16:9 / 9:16, 360p / 720p...)."""

    def __init__(self, items: list[str], current: str | None = None, on_change=None):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.group = QButtonGroup(self)
        self.btns = {}
        for it in items:
            b = QPushButton(tr(it))
            b.setProperty("kind", "seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(34)
            self.group.addButton(b)
            self.btns[it] = b
            h.addWidget(b, 1)
        (self.btns.get(current) or next(iter(self.btns.values()))).setChecked(True)
        if on_change:
            self.group.buttonClicked.connect(lambda _: on_change(self.value()))

    def value(self) -> str:
        for k, b in self.btns.items():
            if b.isChecked():
                return k
        return next(iter(self.btns))

    def set_value(self, v: str):
        if v in self.btns:
            self.btns[v].setChecked(True)


PROMPT_HINT = "Mỗi dòng là một prompt = một tác vụ.\nGõ @Tên để dùng ảnh trong Kho ảnh tham chiếu cho dòng đó."
EXTEND_HINT = ("Mỗi dòng = 1 video: cảnh đầu || đoạn kéo dài 1 || đoạn kéo dài 2 …\n"
               "Ví dụ: Cô gái ngồi uống trà trước hiên nhà || Cô đứng dậy đi vào nhà")


class FlowPage(QWidget):
    def __init__(self, ctx, pdef: PageDef):
        super().__init__()
        self.ctx = ctx
        self.pdef = pdef
        self.db = ctx.db
        self.lib = ctx.characters
        self.key = pdef.key
        self.video = pdef.kind == "video"
        self.st = self.db.get_setting(f"page_{self.key}", {}) or {}
        mk = [m.key for m in pdef.modes]
        self.mode = self.st.get("mode") if self.st.get("mode") in mk else mk[0]
        self._build()
        self.model.check_changed = self._checked_changed
        self.model.on_draft_edit = self._edit_draft_line
        self.model.drafts = self._prompts()
        self.model.reload()
        self.refresh_stats()
        self._dirty = False
        t = QTimer(self)
        t.setInterval(400)
        t.timeout.connect(self._flush)
        t.start()
        ctx.engine.job_updated.connect(lambda _: setattr(self, "_dirty", True))
        ctx.engine.page_state.connect(self._on_state)
        ctx.engine.account_updated.connect(lambda _: self.refresh_stats())

    # ================================================================ giao diện
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)
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

        # ---------- cột trái
        lw = QWidget()
        lw.setFixedWidth(362)
        left = QVBoxLayout(lw)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)
        cfg = Card("Cấu hình tạo video" if self.video else "Cấu hình tạo ảnh", "sliders")
        self.mode_seg = Seg([m.label for m in self.pdef.modes],
                            next(m.label for m in self.pdef.modes if m.key == self.mode), self._mode_changed)
        cfg.add(self.mode_seg)
        self.mode_seg.setVisible(len(self.pdef.modes) > 1)   # trang ảnh: 1 chế độ, có ảnh tham chiếu thì tự dùng Tham chiếu
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.model_cb = combo(self.pdef.models, self.st.get("model"))
        self.model_cb.currentTextChanged.connect(lambda _: self._apply_mode_ui())
        g.addWidget(field("Model", self.model_cb), 0, 0)
        if self.video:
            self.ratio = Seg(["16:9", "9:16"], self.st.get("ratio", "16:9"))
            g.addWidget(field("Tỷ lệ khung hình", self.ratio), 0, 1)
            lo, hi, dv = 3, 15, 8
            self.dur = QSlider(Qt.Horizontal)
            self.dur.setRange(lo, hi)
            self.dur.setValue(int(self.st.get("seconds", dv)))
            self.dur_lbl = QLabel()
            self.dur_lbl.setObjectName("fieldLabel")
            self.dur.valueChanged.connect(lambda v: self.dur_lbl.setText(tr("Thời lượng") + f" · {v} " + tr("giây")))
            self.dur_fixed = label("", "muted")
            dbox = QWidget()
            dv_ = QVBoxLayout(dbox)
            dv_.setContentsMargins(0, 0, 0, 0)
            dv_.setSpacing(4)
            dv_.addWidget(self.dur_lbl)
            dv_.addWidget(self.dur)
            dv_.addWidget(self.dur_fixed)
            self.dur_box = dbox
            g.addWidget(self.dur_box, 1, 0, 1, 2)
            # Kéo dài: số giây mỗi đoạn kéo dài (Flow: 3–10 giây)
            elo, ehi, edv = self.pdef.extra.get("extend_secs", (3, 10, 4))
            self.ext = QSlider(Qt.Horizontal)
            self.ext.setRange(elo, ehi)
            self.ext.setValue(int(self.st.get("extend_secs", edv)))
            self.ext_lbl = QLabel()
            self.ext_lbl.setObjectName("fieldLabel")
            self.ext.valueChanged.connect(lambda v: self.ext_lbl.setText(
                tr("Kéo dài mỗi đoạn") + f" · +{v} " + tr("giây") + f"  (~{v * 3} " + tr("tín dụng") + ")"))
            self.ext.valueChanged.emit(self.ext.value())
            ebox = QWidget()
            ev_ = QVBoxLayout(ebox)
            ev_.setContentsMargins(0, 0, 0, 0)
            ev_.setSpacing(4)
            ev_.addWidget(self.ext_lbl)
            ev_.addWidget(self.ext)
            self.ext_box = ebox
            g.addWidget(self.ext_box, 2, 0, 1, 2)
        else:
            self.ratio = combo(self.pdef.ratios, self.st.get("ratio"))
            g.addWidget(field("Tỷ lệ khung hình", self.ratio), 0, 1)
        qs = self.pdef.extra.get("quality", [])
        self.quality = Seg(qs or ["Gốc"], self.st.get("quality") if self.st.get("quality") in qs else (qs or ["Gốc"])[0])
        self.quality.setToolTip(tr("Bản cao hơn bản gốc do Flow tăng độ phân giải khi tải về (mất thêm thời gian)"))
        cfg.add(g)
        self.quality_box = field("Chất lượng tải về", self.quality)
        cfg.add(self.quality_box)
        self.has_quality = bool(qs)
        self.quality_box.setVisible(self.has_quality)
        nmax = max(1, int(self.pdef.max_count))
        cnt = str(self.st.get("count", 1)) if int(self.st.get("count", 1)) <= nmax else "1"
        self.count = Seg([str(i) for i in range(1, nmax + 1)], cnt)
        self.count_box = field("Số kết quả mỗi prompt", self.count)
        cfg.add(self.count_box)
        self.count_box.setVisible(nmax > 1)       # ChatGPT: mỗi prompt 1 ảnh
        if len(self.pdef.models) <= 1:            # chỉ 1 model (GPT Image…) → ẩn ô chọn model
            self.model_cb.parentWidget().setVisible(False)
            rbox = self.ratio.parentWidget()      # tỷ lệ khung hình chiếm cả hàng
            g.removeWidget(rbox)
            g.addWidget(rbox, 0, 0, 1, 2)

        # ảnh tham chiếu theo chế độ
        self.refs_strip = RefStrip(self.lib, 10)
        self.refs_strip.set_ids(self.st.get("ref_ids", []))
        self.refs_box = field("Ảnh tham chiếu (dùng cho mọi prompt · hoặc gõ @Tên trong prompt)", self.refs_strip)
        cfg.add(self.refs_box)
        self.refs_hint = QLabel(tr("Ảnh tham chiếu: thêm riêng cho từng tác vụ ở cột “Ảnh tham chiếu” trong danh sách tác vụ →"))
        self.refs_hint.setWordWrap(False)          # 1 dòng: tránh lỗi tính chiều cao của chữ tự xuống dòng
        self.refs_hint.setStyleSheet("background:#0f2340;border:1px solid #1e4a7a;border-radius:4px;color:#7cc4ff;"
                                     "padding:5px 8px;font-size:11.5px;font-weight:600;")
        cfg.add(self.refs_hint)
        if self.video:
            fr = QWidget()
            fh = QHBoxLayout(fr)
            fh.setContentsMargins(0, 0, 0, 0)
            self.first = RefStrip(self.lib, single=True, placeholder="Ảnh đầu")
            self.last = RefStrip(self.lib, single=True, placeholder="Ảnh cuối (nếu có)")
            self.first.set_ids(self.st.get("first_ids", []))
            self.last.set_ids(self.st.get("last_ids", []))
            fh.addWidget(self.first)
            fh.addWidget(self.last)
            self.frames_box = field("Ảnh đầu → ảnh cuối (chọn từ kho ảnh tham chiếu)", fr)
            cfg.add(self.frames_box)
        # thư mục lưu
        out = QPushButton()
        out.setCursor(Qt.PointingHandCursor)
        out.setIcon(icon("folder", "#67e8f9", 16))
        out.setStyleSheet(f"QPushButton{{text-align:left;padding:8px 10px;background:{C['input-bg']};"
                          f"border:1px solid {C['border-input']};border-radius:4px;font-weight:500;}}"
                          f"QPushButton:hover{{border-color:{C['accent']};}}")
        out.clicked.connect(self._pick_dir)
        self.out_btn = out
        self.out_dir = self.st.get("save_dir") or str(default_output_dir() / self.key)
        self._show_dir()
        cfg.add(field("Thư mục lưu kết quả (bấm để đổi)", out))
        from PySide6.QtWidgets import QSizePolicy
        cfg.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)   # không bị ép nhỏ: ô nhập prompt co lại thay
        left.addWidget(cfg)

        ar = QHBoxLayout()
        b_imp = button("Nhập tệp" if self.video else "Nhập tệp (TXT, Excel)", "primary", "upload")
        b_imp.setToolTip(tr("Nhập prompt từ tệp TXT / Excel"))
        b_imp.clicked.connect(self._import)
        b_ai = self.b_ai = button("AI Agent", None, "wand", "#f0abfc")
        b_ai.setToolTip(tr(AI_TIP))
        b_ai.clicked.connect(self._ai_fix)
        ar.addWidget(b_imp, 2)
        ar.addWidget(b_ai, 1)
        if self.video:                             # "Quy trình tự động" nằm bên phải tiêu đề khung Cấu hình
            b_sc = self.b_script = button("Quy trình tự động", None, "clapper", "#fbbf24")
            b_sc.setStyleSheet("QPushButton{border:1px solid #f59e0b;color:#fde68a;padding:4px 10px;}"
                               "QPushButton:hover{background:#2e2410;}")
            b_sc.setToolTip(tr("Quy trình tự động: chọn chủ đề, thêm ảnh nhân vật / sản phẩm / bối cảnh, AI Agent viết "
                               "đủ số cảnh theo thời lượng rồi đưa vào danh sách tác vụ (dùng cấu hình riêng trong popup)"))
            b_sc.clicked.connect(self.open_script)
            cfg.head_layout.addWidget(b_sc)
        left.addLayout(ar)
        pbox = QFrame()
        pbox.setObjectName("card")
        pv = QVBoxLayout(pbox)
        pv.setContentsMargins(6, 6, 6, 8)
        self.editor = PromptEditor()
        self.editor.setStyleSheet("QPlainTextEdit{border:none;background:transparent;}")
        self.editor.setPlaceholderText(tr(EXTEND_HINT) if self.mode == "extend" else tr(PROMPT_HINT))
        self.editor.setPlainText(self.st.get("draft", ""))
        self.editor.files_dropped.connect(self._load_files)
        self.editor.textChanged.connect(self._count_prompts)
        self._draft_timer = QTimer(self)
        self._draft_timer.setSingleShot(True)
        self._draft_timer.setInterval(250)
        self._draft_timer.timeout.connect(self._sync_drafts)
        self.editor.textChanged.connect(self._draft_timer.start)
        pv.addWidget(self.editor, 1)
        self.free_lbl = QLabel()
        self.free_lbl.setWordWrap(False)
        self.free_lbl.setStyleSheet("background:#2e2410;border:1px solid #5a4416;border-radius:4px;color:#fbbf24;"
                                    "padding:6px 8px;font-size:11.5px;font-weight:600;")
        self.free_lbl.hide()
        pv.addWidget(self.free_lbl)
        self.pcount = label("", "faint")
        pv.addWidget(self.pcount)
        self.editor.setMinimumHeight(70)
        left.addWidget(pbox, 1)
        runr = QHBoxLayout()
        self.b_start = button("Bắt đầu", "start", "play")
        self.b_pause = button("Tạm dừng", "pause", "pause", C["warning"])
        self.b_stop = button("Dừng", "stop", "stop", C["danger"])
        self.b_start.clicked.connect(self.start)
        self.b_pause.clicked.connect(lambda: self.ctx.engine.pause_page(self.key))
        self.b_stop.clicked.connect(self._stop)
        for b in (self.b_start, self.b_pause, self.b_stop):
            runr.addWidget(b)
        left.addLayout(runr)
        cols.addWidget(lw)

        # ---------- cột phải: danh sách tác vụ
        right = QFrame()
        right.setObjectName("card")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        tb = QHBoxLayout()
        tb.setContentsMargins(12, 10, 12, 10)
        tb.setSpacing(6)
        self.all_cb = QCheckBox()
        self.all_cb.setToolTip(tr("Chọn / bỏ chọn tất cả"))
        self.all_cb.clicked.connect(lambda on: self.model.set_all(on))
        tb.addWidget(self.all_cb)
        self.tasks_lbl = label("Tác vụ", "h2")
        tb.addWidget(self.tasks_lbl)
        self.sel_lbl = label("", "faint")
        tb.addWidget(self.sel_lbl)
        self.filters = QButtonGroup(self)
        # lọc Xong / Lỗi / Đang chạy: bấm các thẻ thống kê phía trên; "Tất cả" để bỏ lọc
        for key, text in ((None, "Tất cả"),):
            b = QPushButton(tr(text))
            b.setProperty("kind", "chip")
            b.setCheckable(True)
            b.setChecked(key is None)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, bb=b: (bb.setChecked(True), self._set_filter(None)))
            self.filters.addButton(b)
            tb.addWidget(b)
        tb.addStretch()
        self.b_bulk_refs = button("Ảnh tham chiếu", "chip", "library", "#f9a8d4")
        self.b_bulk_refs.setToolTip(tr("Thêm ảnh từ Kho ảnh tham chiếu vào TẤT CẢ tác vụ đã tick"))
        self.b_bulk_refs.clicked.connect(self._bulk_refs)
        tb.addWidget(self.b_bulk_refs)
        b_del = button("Xóa", "stop", "trash", C["danger"])
        b_del.setToolTip(tr("Xóa các tác vụ đã tick"))
        b_del.setStyleSheet(f"QPushButton{{padding:5px 9px;background:{C['danger-bg']};border:1px solid #62202f;color:{C['danger']};}}")
        b_del.clicked.connect(self._delete_checked)
        tb.addWidget(b_del)
        b_del_all = button("Xóa tất cả", "stop", "trash", C["danger"])
        b_del_all.setToolTip(tr("Xóa toàn bộ tác vụ trong danh sách (không cần tick)"))
        b_del_all.setStyleSheet(f"QPushButton{{padding:5px 9px;background:{C['danger-bg']};border:1px solid #62202f;color:{C['danger']};}}")
        b_del_all.clicked.connect(self._delete_all)
        tb.addWidget(b_del_all)
        b_run_sel = button("Chạy", "chip", "play", "#4ade80")
        b_run_sel.setToolTip(tr("Chỉ chạy các tác vụ đã tick (tác vụ chưa chạy hoặc bị lỗi)"))
        b_run_sel.clicked.connect(self.run_selected)
        tb.addWidget(b_run_sel)
        for text, ic, fn in (("Chạy lại tất cả tác vụ lỗi", "retry", self._retry),
                             ("Mở thư mục lưu", "folder", lambda: open_path(self._ensure_out()))):
            b = icon_button(ic, text, "#67e8f9")
            b.setFixedSize(32, 30)
            b.clicked.connect(fn)
            tb.addWidget(b)
        tb.setSpacing(4)
        tb.setContentsMargins(8, 10, 8, 10)
        self._tb = tb
        right.installEventFilter(self)
        self.b_bulk_refs.setStyleSheet("QPushButton{padding:5px 8px;}")
        for i in range(tb.count()):                              # nút trên thanh tác vụ không bị bóp mất chữ
            wdg = tb.itemAt(i).widget()
            if isinstance(wdg, QPushButton) and wdg.text():
                wdg.ensurePolished()
                from PySide6.QtGui import QFont, QFontMetrics
                f = QFont(wdg.font())
                f.setBold(True)
                need = QFontMetrics(f).horizontalAdvance(wdg.text()) + wdg.iconSize().width() + 26
                wdg.setMinimumWidth(max(wdg.sizeHint().width(), need))
        rv.addLayout(tb)
        # bấm ô đếm chung → danh sách tác vụ đúng trạng thái đó trên MỌI nền tảng, ngay tại đây (không mở cửa sổ mới)
        self.scope_bar = QFrame()
        sbh = QHBoxLayout(self.scope_bar)
        sbh.setContentsMargins(12, 6, 8, 6)
        self.scope_lbl = QLabel()
        self.scope_lbl.setStyleSheet("background:transparent;font-weight:700;")
        sbh.addWidget(self.scope_lbl, 1)
        self.b_scope_retry = button("Chạy lại tất cả tác vụ lỗi", "chip", "retry", "#fbbf24")
        self.b_scope_retry.clicked.connect(lambda: self._requeue(list(self.model.rows)))
        sbh.addWidget(self.b_scope_retry)
        b_x = button("Về danh sách của trang này", "chip", "x", "#fb7185")
        b_x.clicked.connect(lambda: self._set_scope(None))
        sbh.addWidget(b_x)
        self.scope_bar.hide()
        rv.addWidget(self.scope_bar)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{C['border']};")
        rv.addWidget(line)
        self.model = TaskModel(self.db, self.key)
        self.model.draft_refs = {k: [x for x in v if not x or Path(x).exists()]
                                 for k, v in (self.st.get("draft_refs") or {}).items()}
        self.draft_params: dict[str, dict] = dict(self.st.get("draft_params") or {})   # prompt nháp → tham số riêng (kịch bản)
        self.model.draft_params = self.draft_params
        self.table = TaskTable(self.model)
        self.table.action.connect(self._row_action)
        self.empty = QLabel(tr("Chưa có tác vụ nào.\nNhập prompt bên trái (mỗi dòng một prompt) – tác vụ sẽ hiện ngay ở đây."))
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("muted")
        rv.addWidget(self.table, 1)
        rv.addWidget(self.empty, 1)
        cols.addWidget(right, 1)
        self._apply_mode_ui()
        self._count_prompts()
        self._on_state(self.key, "running" if self.ctx.engine.is_running(self.key) else "idle")

    # ================================================================ trạng thái giao diện
    def _mode_changed(self, label_text):
        self.mode = next(m.key for m in self.pdef.modes if m.label == label_text)
        self._apply_mode_ui()
        self._save_state()

    def _apply_mode_ui(self):
        if hasattr(self, "model"):
            self.model.frames_mode = self.mode == "i2v"
            self.model.reload()
        # ảnh tham chiếu chung đã bỏ: ảnh được thêm riêng ở từng tác vụ
        self.refs_box.setVisible(False)
        self.refs_hint.setVisible(self.mode in ("i2i", "compose"))
        ext = self.mode == "extend"
        if hasattr(self, "ext_box"):
            self.ext_box.setVisible(ext)
        if hasattr(self, "count_box"):
            self.count_box.setVisible(not ext and self.pdef.max_count > 1)   # Kéo dài: mỗi tác vụ 1 video
            self.quality_box.setVisible(not ext and self.has_quality)      # Flow chỉ cho tải video đã kéo dài ở bản gốc 720p
        if hasattr(self, "editor"):
            self.editor.setPlaceholderText(tr(EXTEND_HINT) if ext else tr(PROMPT_HINT))
        if self.mode == "i2v":
            self.refs_hint.setText(tr("Chọn ảnh đầu / cuối ở cột “Ảnh tham chiếu” →"))
            self.refs_hint.setToolTip(tr("Bấm ô “Ảnh tham chiếu” ở từng tác vụ: ảnh 1 = khung đầu, ảnh 2 = khung cuối"))
        else:
            self.refs_hint.setText(tr("Chọn ảnh ở cột “Ảnh tham chiếu” của từng tác vụ →"))
        if self.video:
            self.frames_box.setVisible(False)
            m = self.model_cb.currentText()
            rng = self.pdef.extra.get("durations", {}).get(m)
            self.dur.setVisible(bool(rng))
            if rng:
                lo, hi, dv = rng
                self.dur.setRange(lo, hi)
                self.dur.valueChanged.emit(self.dur.value())

            self.dur_fixed.setVisible(False)
            self.dur_box.setVisible(bool(rng))      # Veo 3.1 - Lite: Flow không cho chỉnh thời lượng → ẩn

    def _show_dir(self):
        p = self.out_dir
        short = p if len(p) <= 52 else "…" + p[-50:]
        self.out_btn.setText("  " + short)
        self.out_btn.setToolTip(p)

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Chọn thư mục lưu kết quả"), self.out_dir)
        if d:
            self.out_dir = d
            self._show_dir()
            self._save_state()

    def _ensure_out(self) -> str:
        Path(self.out_dir).mkdir(parents=True, exist_ok=True)
        return self.out_dir

    def _accounts(self) -> tuple[list[str], int]:
        accs = [a for a in self.db.accounts(self.pdef.platform) if a["enabled"]]
        ready = [a["id"] for a in accs if a["status"] in ("ok", "unknown", "needs_user")]
        ok = sum(1 for a in accs if a["status"] == "ok")
        return ready, ok

    def _prompts(self) -> list[str]:
        return prompt_io.split_prompts(self.editor.toPlainText(), "line")

    def _count_prompts(self):
        n = len(self._prompts())
        ready, _ = self._accounts()
        k = len(ready)
        par = f" · {tr('chạy song song trên')} {min(n, k)} {tr('tài khoản')}" if k and n else ""
        if self._is_free():
            par = f" · {tr('gói Miễn phí: 1 tác vụ/lần')}" if n <= 1 else f" · ⚠ {tr('gói Miễn phí chỉ chạy 1 prompt/lần')}"
        self.pcount.setText(tr("Mỗi dòng = 1 tác vụ") + f" · {n} prompt{par}")

    def _save_state(self):
        st = {"mode": self.mode, "model": self.model_cb.currentText(), "count": int(self.count.value()),
              "quality": self.quality.value(),
              "save_dir": self.out_dir, "ref_ids": self.refs_strip.ids, "draft": self.editor.toPlainText()[:200000],
              "draft_refs": {k: v for k, v in self.model.draft_refs.items() if v and k in set(self._prompts())},
              "draft_params": {k: v for k, v in self.draft_params.items() if v and k in set(self._prompts())}}
        if self.video:
            st.update({"ratio": self.ratio.value(), "seconds": self.dur.value(), "extend_secs": self.ext.value(),
                       "first_ids": self.first.ids, "last_ids": self.last.ids})
        else:
            st["ratio"] = self.ratio.currentText()
        self.db.set_setting(f"page_{self.key}", st)

    # ================================================================ nhập prompt / AI
    def _import(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Nhập prompt"), "", "Prompt (*.txt *.csv *.xlsx)")
        if fs:
            self._load_files(fs)

    def _load_files(self, files):
        ps = []
        for f in files:
            try:
                ps += [p.replace("\n", " ") for p in prompt_io.load_file(f)]
            except Exception as e:
                self.ctx.toast("error", f"{Path(f).name}: {e}")
        if ps:
            cur = self.editor.toPlainText().strip()
            self.editor.setPlainText((cur + "\n" if cur else "") + "\n".join(ps))
            self.ctx.toast("ok", tr("Đã nhập") + f" {len(ps)} prompt")

    # ---------------- Tạo kịch bản (popup)
    def clip_secs(self) -> int:
        """Độ dài 1 clip của trang (để chia số cảnh theo thời lượng)."""
        from ..script_dialog import CLIP_SECS
        if self.video and self.pdef.extra.get("durations", {}).get(self.model_cb.currentText()):
            return int(self.dur.value())
        return CLIP_SECS.get(self.pdef.platform, 8)

    def model_name(self) -> str:
        return self.model_cb.currentText() or self.pdef.label

    def ratio_value(self) -> str:
        return self.ratio.value() if self.video else "9:16"

    def open_script(self):
        from ..script_dialog import ScriptDialog
        d = ScriptDialog(self)
        if not d.exec() or not d.result_tasks:
            return
        self.add_script_tasks(d.result_tasks, d.ratio.currentText())

    def add_script_tasks(self, tasks: list[dict], ratio: str | None = None):
        """Đưa các cảnh của kịch bản vào danh sách tác vụ (dòng nháp), gắn ảnh + tham số riêng của từng cảnh."""
        flow = self.pdef.platform == "flow"
        if flow and self.mode != "t2v":           # cảnh kịch bản chạy ở chế độ Văn bản → Video (+ ảnh / khung đầu tự động)
            lab = next(m.label for m in self.pdef.modes if m.key == "t2v")
            self.mode_seg.set_value(lab)
            self._mode_changed(lab)
        if ratio and self.video and ratio in self.ratio.btns:
            self.ratio.set_value(ratio)
        lines = self._prompts()
        used = set(lines)
        new = []
        for t in tasks:
            p = " ".join(t["prompt"].split())
            while p in used:                       # 2 cảnh trùng chữ: thêm dấu cách cuối để giữ riêng ảnh / tham số
                p += " ."
            used.add(p)
            new.append(p)
            params = dict(t.get("params") or {})
            if ratio and self.video:                   # tỷ lệ của popup đi theo từng cảnh (không theo khung Cấu hình)
                params["ratio"] = "16:9 Ngang" if ratio.startswith("16") else "9:16 Dọc"
            if not flow:
                params["_mode"] = "i2v" if t.get("refs") else "t2v"
            if t.get("refs"):
                self.model.draft_refs[p] = list(t["refs"])
            if params:
                self.draft_params[p] = params
        self._set_editor_lines(lines + new)
        self._save_state()
        self.ctx.toast("ok", tr("Đã thêm") + f" {len(new)} " + tr("cảnh vào danh sách tác vụ – bấm Bắt đầu để tạo video"))

    def _ai_run(self, fn, on_done, what: str):
        """Chạy AI Agent ở luồng nền (có thể mất vài chục giây khi dùng tài khoản qua trình duyệt ẩn)."""
        if getattr(self, "_ai_busy", False):
            return self.ctx.toast("info", tr("AI đang làm việc, chờ xong đã."))
        self._ai_busy = True
        self.b_ai.setEnabled(False)
        self.b_ai.setText(tr("AI Agent đang sửa…"))
        self.ctx.toast("info", tr(what))

        def job(progress):
            return fn(lambda m: progress(0, m))

        def done(res):
            self._ai_end()
            on_done(res)

        def err(msg):
            self._ai_end()
            self.ctx.toast("error", msg)
        run_bg(job, on_done=done, on_error=err, on_progress=lambda _p, m: m and self.b_ai.setToolTip(m))

    def _ai_end(self):
        self._ai_busy = False
        self.b_ai.setEnabled(True)
        self.b_ai.setText(tr("AI Agent"))
        self.b_ai.setToolTip(tr(AI_TIP))

    AI_FREE_NOTE = ("Gói Miễn phí: AI Agent mỗi lần chỉ sửa / viết 1 prompt. Nâng cấp gói để sửa hàng loạt prompt "
                    "và dùng đầy đủ tính năng tạo kịch bản nhiều cảnh.")

    def _ai_upsell(self, reason: str):
        self.ctx.win.upsell(tr(reason))

    def _ai_fix(self):
        from ...services import llm
        ps = self._prompts()
        if not ps:
            return self.ctx.toast("info", tr("Chưa có prompt nào để sửa – nhập prompt (mỗi dòng một prompt) trước."))
        eng = self.ctx.engine
        free = self._is_free()
        todo = ps[:1] if free else ps                     # gói Miễn phí: mỗi lần 1 prompt (dòng đầu)

        def done(out):
            new = [p.replace("\n", " ") for p in out] + (ps[len(out):] if free else [])
            self.editor.setPlainText("\n".join(new))
            self.ctx.toast("ok", tr("AI đã sửa") + f" {len(out)} prompt")
            if free and len(ps) > 1:
                self._ai_upsell("Gói Miễn phí: AI Agent chỉ sửa 1 prompt mỗi lần.")
        self._ai_run(lambda st: llm.fix_prompts(self.db, todo, eng, st), done, "AI Agent đang sửa các prompt…")

    def _params(self) -> dict:
        q = self.quality.value() if self.has_quality else ""
        if self.video:
            ratio = "16:9 Ngang" if self.ratio.value() == "16:9" else "9:16 Dọc"
            m = self.model_cb.currentText()
            p = {"model": m, "ratio": ratio, "quality": q}
            if m.lower().startswith("omni"):
                p["resolutions"] = "720p"          # tạo ở độ phân giải cao nhất Flow cho phép
            if self.pdef.extra.get("durations", {}).get(m):
                p["durations"] = f"{self.dur.value()} giây"
            if self.mode == "extend":
                p["extend_secs"] = int(self.ext.value())
                p["quality"] = ""                   # video đã kéo dài: Flow chỉ có bản gốc 720p
            return p
        return {"model": self.model_cb.currentText(), "ratio": self.ratio.currentText(), "quality": q}

    def build_rows(self, prompts: list[str] | None = None) -> list[dict] | None:
        prompts = self._prompts() if prompts is None else prompts
        if not prompts:
            self.ctx.toast("warn", tr("Chưa có prompt nào."))
            return None
        common = []          # không còn ảnh tham chiếu chung: chỉ dùng ảnh riêng của từng tác vụ (+ @Tên)
        frames = []
        rows = []
        for p in prompts:
            raw = list(self.model.draft_refs.get(p, []))
            own = [x for x in raw if x and Path(x).exists()]                          # ảnh riêng của tác vụ
            text, tag_refs = self.lib.expand(p, True)
            extra = dict(self.draft_params.get(p) or {})
            forced = extra.pop("_mode", None)
            mode = forced or self.mode
            if forced:                                # cảnh của kịch bản: giữ đúng ảnh của cảnh
                refs = own + [r for r in tag_refs if r not in own]
                if mode == "i2v" and not extra.get("keyframe"):
                    refs = refs[:1]
                rows.append({"mode": mode, "prompt": text, "refs": refs[:10], "params": extra,
                             "count": int(self.count.value())})
                continue
            if mode == "i2v":
                if raw and not raw[0] and len(raw) > 1:
                    self.ctx.toast("warn", tr("Tác vụ") + f" “{p[:40]}”: " + tr("cần ảnh Bắt đầu (ảnh Kết thúc là tùy chọn)."))
                    return None
                refs = (own or [r for r in tag_refs])[:2]
            else:
                refs = own + [r for r in common if r not in own]
                refs += [r for r in tag_refs if r not in refs]
                if mode == "t2v" and refs:
                    mode = "compose"          # có ảnh → dùng chế độ Tham chiếu (Thành phần) của Flow
                if mode == "t2i" and refs:
                    mode = "i2i"
            if mode in ("i2i", "compose", "i2v") and not refs:
                self.ctx.toast("warn", tr("Tác vụ") + f" “{p[:40]}” " +
                               tr("chưa có ảnh: bấm ô “Ảnh tham chiếu” ở dòng đó để chọn ảnh từ kho (hoặc gõ @Tên trong prompt)."))
                return None
            if mode == "extend":
                from ...adapters.flow import split_extend
                if len(split_extend(text)) < 2:
                    self.ctx.toast("warn", tr("Tác vụ") + f" “{p[:40]}”: " +
                                   tr("Kéo dài cần dạng  cảnh đầu || đoạn kéo dài  (có thể nối nhiều đoạn bằng ||)."))
                    return None
            rows.append({"mode": mode, "prompt": text, "refs": refs[:10], "params": extra,
                         "count": 1 if mode == "extend" else int(self.count.value())})
        return rows

    def _ready_or_warn(self) -> list[str] | None:
        ready, _ = self._accounts()
        if not ready:
            QMessageBox.information(self, tr("Chưa có tài khoản"),
                                    tr("Chưa có tài khoản") + f" {PLATFORM_LABELS.get(self.pdef.platform, self.pdef.platform)} " +
                                    tr("nào đăng nhập.\nVào Cài Đặt › Tài khoản › Thêm tài khoản "
                                       "rồi đăng nhập trong cửa sổ Chrome hiện ra."))
            return None
        return ready

    # ================================================================ gói Miễn phí: mỗi lần 1 tác vụ
    def _is_free(self) -> bool:
        win = self.ctx.win
        return hasattr(win, "is_pro") and not win.is_pro()

    def _busy_any(self) -> int:
        row = self.db.one("SELECT COUNT(*) n FROM jobs WHERE status IN ('queued','running','needs_user')")
        return int(row["n"]) if row else 0

    def _free_guard(self, n_new: int) -> bool:
        """True = được chạy. Gói Miễn phí: mỗi lần chỉ 1 prompt / 1 tác vụ (toàn phần mềm);
        tác vụ đang có xong rồi mới nhập và chạy được tác vụ tiếp theo."""
        if not self._is_free():
            return True
        if self._busy_any():
            self.ctx.win.upsell(tr("Gói Miễn phí: chờ tác vụ đang chạy xong mới tạo tiếp."))
            return False
        if n_new > 1:
            self.ctx.win.upsell(tr("Gói Miễn phí: mỗi lần chỉ chạy 1 prompt") + f" ({tr('đang có')} {n_new}).")
            return False
        return True

    def apply_tier(self):
        """Gói Miễn phí: khóa ô nhập prompt khi đang có tác vụ chạy."""
        if not hasattr(self, "free_lbl"):
            return
        free = self._is_free()
        busy = free and self._busy_any() > 0
        self.editor.setReadOnly(busy)
        self.editor.setStyleSheet("QPlainTextEdit{border:none;background:transparent;" +
                                  ("color:#7f8bc4;}" if busy else "}"))
        if busy:
            self.free_lbl.setText(tr("Đang tạo 1 tác vụ · chờ xong mới nhập prompt mới"))
        else:
            self.free_lbl.setText(tr("Gói Miễn phí: mỗi lần 1 prompt / 1 tác vụ"))
        self.free_lbl.setToolTip(tr("Gói Miễn phí: mỗi lần chỉ 1 prompt / 1 tác vụ, xong tác vụ này mới nhập được prompt "
                                    "khác. Nâng cấp Chuyên nghiệp để chạy hàng loạt, song song."))
        self.free_lbl.setVisible(free)

    def _enqueue(self, prompts: list[str]) -> int:
        if not self._free_guard(len(prompts)):
            return 0
        ready = self._ready_or_warn()
        if not ready:
            return 0
        rows = self.build_rows(prompts)
        if not rows:
            return 0
        if self.pdef.platform == "flow" and not self.ctx.win.ensure_flow_terms():
            return 0
        if self.pdef.platform == "flow" and any(r.get("refs") for r in rows) and not self.ctx.win.ensure_flow_rights():
            return 0
        self._save_state()
        self.db.create_batch(self.pdef.platform, self.key, self._params(), self._ensure_out(), "flat", rows)
        for p_ in prompts:
            self.model.draft_refs.pop(p_, None)
            self.draft_params.pop(p_, None)
        self.ctx.engine.start_page(self.key, ready, 1, DELAY, True)
        self.ctx.toast("info", tr("Đã chạy") + f" {len(rows)} " + tr("tác vụ") + " · " +
                       tr("song song trên") + f" {min(len(rows), len(ready))} " + tr("tài khoản"))
        return len(rows)

    def start(self):
        """Bắt đầu: chạy toàn bộ tác vụ 'Chưa chạy' trong danh sách (các dòng prompt đã nhập)."""
        prompts = self._prompts()
        if not prompts:
            n = self._requeue([r for r in self.model.rows if r["status"] in ("cancelled",)])
            if not n:
                self.ctx.toast("warn", tr("Chưa có tác vụ nào. Nhập prompt bên trái (mỗi dòng một prompt)."))
            return
        if self._enqueue(prompts):
            self._set_editor_lines([])

    def run_selected(self):
        rows = self.model.checked_rows()
        if not rows:
            self.ctx.toast("info", tr("Tick chọn các tác vụ muốn chạy."))
            return
        drafts = [r for r in rows if r["draft"]]
        others = [r for r in rows if not r["draft"]]
        if drafts and self._enqueue([r["prompt"] for r in drafts]):
            keep = [p for i, p in enumerate(self._prompts()) if i not in {r["index"] for r in drafts}]
            self._set_editor_lines(keep)
        if others:
            self._requeue(others)
        self.model.checked.clear()
        self.model.reload()
        self.refresh_stats()

    def _set_editor_lines(self, lines: list[str]):
        self.editor.setPlainText("\n".join(lines))
        self._sync_drafts()

    def _sync_drafts(self):
        self._draft_timer.stop()
        self.model.set_drafts(self._prompts())
        self._update_empty()

    def _edit_draft_line(self, index: int, text: str):
        lines = self._prompts()
        if 0 <= index < len(lines):
            old = lines[index]
            if old in self.model.draft_refs and text not in self.model.draft_refs:
                self.model.draft_refs[text] = self.model.draft_refs.pop(old)
            if old in self.draft_params and text not in self.draft_params:
                self.draft_params[text] = self.draft_params.pop(old)
            lines[index] = text
            self.editor.blockSignals(True)
            self.editor.setPlainText("\n".join(lines))
            self.editor.blockSignals(False)
            self._count_prompts()

    def _stop(self):
        if QMessageBox.question(self, tr("Dừng"), tr("Hủy tất cả tác vụ đang chờ và đang chạy?")) == QMessageBox.Yes:
            self.ctx.engine.stop_page(self.key)

    def _requeue(self, rows):
        other = [r for r in rows if not r.get("draft") and r.get("page") and r["page"] != self.key]
        if other:                                     # tác vụ của trang khác (đang xem chung mọi nền tảng)
            n = 0
            by: dict[str, list] = {}
            for r in other:
                by.setdefault(r["page"], []).append(r)
            for pg_key, rs in by.items():
                pg = self.ctx.win.page(pg_key)
                if hasattr(pg, "_requeue"):
                    n += pg._requeue(rs)
            rows = [r for r in rows if r not in other]
            return n + (self._requeue(rows) if rows else 0)
        todo = [r for r in rows if not r.get("draft") and r["status"] not in ("running", "queued")]
        if todo and not self._free_guard(len(todo)):
            return 0
        if todo and self.pdef.platform == "flow" and not self.ctx.win.ensure_flow_terms():
            return 0
        if (todo and self.pdef.platform == "flow" and any(r.get("refs_list") for r in todo)
                and not self.ctx.win.ensure_flow_rights()):
            return 0
        n = 0
        for r in rows:
            if not r.get("draft") and r["status"] not in ("running", "queued"):
                self.db.update_job(r["id"], status="queued", progress=0, error_code=None, error_text=None, attempts=0)
                n += 1
        ready, _ = self._accounts()
        if n and ready:
            self.ctx.engine.start_page(self.key, ready, 1, DELAY, True)
        self.model.reload()
        self.refresh_stats()
        return n

    def _retry(self):
        rows = self.model.checked_rows() or [r for r in self.db.jobs_for_platform(self.pdef.platform, self.key)
                                             if r["status"] in ("failed", "blocked", "cancelled")]
        n = self._requeue(rows)
        self.ctx.toast("info", tr("Chạy lại") + f" {n} " + tr("tác vụ"))

    def _delete_all(self, confirm: bool = True):
        """Xóa toàn bộ tác vụ của trang này (cả dòng chưa chạy). Tác vụ đang chạy giữ lại."""
        jobs = self.db.jobs_for_platform(self.pdef.platform, self.key)
        drafts = self._prompts()
        running = [j for j in jobs if j["status"] in ("running", "needs_user")]
        n = len(jobs) - len(running) + len(drafts)
        if not n:
            self.ctx.toast("info", tr("Danh sách tác vụ đang trống."))
            return
        if confirm and QMessageBox.question(
                self, tr("Xóa tất cả"),
                tr("Xóa toàn bộ") + f" {n} " + tr("tác vụ khỏi danh sách?") +
                ("\n" + tr("(Tác vụ đang chạy sẽ không bị xóa.)") if running else "") +
                "\n" + tr("Tệp kết quả đã tải về vẫn được giữ.")) != QMessageBox.Yes:
            return
        self.db.execute("DELETE FROM jobs WHERE status NOT IN ('running','needs_user') AND batch_id IN "
                        "(SELECT id FROM batches WHERE page=?)", (self.key,))
        self.db.execute("DELETE FROM batches WHERE page=? AND id NOT IN (SELECT DISTINCT batch_id FROM jobs)", (self.key,))
        self.model.draft_refs.clear()
        self._set_editor_lines([])
        self.model.checked.clear()
        self.model.reload()
        self.refresh_stats()
        self.apply_tier()
        self.ctx.toast("ok", tr("Đã xóa") + f" {n} " + tr("tác vụ"))

    def _delete_checked(self):
        rows = self.model.checked_rows()
        if not rows:
            self.ctx.toast("info", tr("Tick chọn tác vụ cần xóa (hoặc ô chọn tất cả ở đầu danh sách)."))
            return
        running = [r for r in rows if r["status"] == "running"]
        if QMessageBox.question(self, tr("Xóa tác vụ"), tr("Xóa") + f" {len(rows) - len(running)} " + tr("tác vụ khỏi danh sách?") +
                                ("\n" + tr("(Tác vụ đang chạy sẽ không bị xóa.)") if running else "") +
                                "\n" + tr("Tệp kết quả đã tải về vẫn được giữ.")) != QMessageBox.Yes:
            return
        drop = {r["index"] for r in rows if r.get("draft")}
        if drop:
            self._set_editor_lines([p for i, p in enumerate(self._prompts()) if i not in drop])
        for r in rows:
            if not r.get("draft") and r["status"] != "running":
                self.db.execute("DELETE FROM jobs WHERE id=?", (r["id"],))
        self.db.execute("DELETE FROM batches WHERE page=? AND id NOT IN (SELECT DISTINCT batch_id FROM jobs)", (self.key,))
        self.model.checked.clear()
        self.model.reload()
        self.refresh_stats()

    def _toggle_browser(self):
        ready, _ = self._accounts()
        opened = [a for a in ready if self.ctx.engine.browser.is_open(a)]
        if not opened:
            self.ctx.toast("info", tr("Trình duyệt chưa mở. Nó sẽ tự mở (ẩn) khi bạn bấm Bắt đầu."))
            return
        show = self.ctx.engine.browser_hidden(opened[0])
        for a in opened:
            self.ctx.engine.set_browser_visible(a, show)

    def _row_action(self, kind, r):
        if kind == "refs":
            self._task_refs(r)
            return
        if kind.startswith("ref_remove:"):
            self._remove_task_ref(r, int(kind.split(":")[1]))
            return
        if kind in ("frame0", "frame1"):
            self._task_frame(r, int(kind[-1]))
            return
        if r.get("draft"):
            if kind == "menu":
                m = QMenu(self)
                m.addAction(icon("play", "#4ade80"), tr("Chạy riêng tác vụ này"), lambda: self._run_draft(r))
                m.addAction(icon("trash", "#fb7185"), tr("Xóa"), lambda: self._set_editor_lines(
                    [p for i, p in enumerate(self._prompts()) if i != r["index"]]))
                m.exec(self.cursor().pos())
            return
        outs = self.db.outputs(r["id"])
        if kind == "view" and outs:
            from ..viewer import MediaViewer
            MediaViewer(self, outs, r["prompt"]).exec()
            return
        if kind == "folder" and outs:
            reveal(outs[0]["path"])
            return
        if kind != "menu":
            return
        m = QMenu(self)
        if outs:
            m.addAction(icon("eye", "#67e8f9"), tr("Xem lớn"), lambda: self._row_action("view", r))
            m.addAction(icon("folder", "#67e8f9"), tr("Mở thư mục chứa"), lambda: reveal(outs[0]["path"]))
            imgs = [o["path"] for o in outs if o["kind"] == "image"]
            if imgs:
                m.addAction(icon("library", "#f9a8d4"), tr("Thêm ảnh vào Kho ảnh tham chiếu"), lambda: self._to_library(imgs))
                m.addAction(icon("video", "#c4a5ff"), tr("Dùng làm ảnh đầu cho Tạo Video Flow"), lambda: self.ctx.send_to_video(imgs[:1]))
        m.addAction(icon("retry", "#4ade80"), tr("Chạy lại"), lambda: self._requeue([r]))
        m.exec(self.cursor().pos())

    def _remove_task_ref(self, r: dict, k: int):
        """Bấm vào 1 ảnh trong ô Ảnh tham chiếu → chỉ bỏ ảnh đó, các ảnh khác giữ nguyên."""
        cur = list(r.get("refs_list") or [])
        if 0 <= k < len(cur):
            del cur[k]
            self._set_task_refs(r, cur, quiet=True)

    def _task_refs(self, r: dict):
        """Bấm dấu + (hoặc chỗ trống) trong ô Ảnh tham chiếu → mở Kho ảnh tham chiếu để THÊM ảnh (giữ ảnh đang có)."""
        cur = list(r.get("refs_list") or [])
        limit = 2 if (self.video and self.mode == "i2v") else 10
        room = limit - len(cur)
        if room <= 0:
            self.ctx.toast("info", tr("Tác vụ đã đủ") + f" {limit} " + tr("ảnh. Bấm vào một ảnh để bỏ ảnh đó."))
            return
        from ..refs_ui import RefPickerDialog
        title = tr("Ảnh tham chiếu cho tác vụ") + f" #{r['row_no']}" + (
            " · " + tr("ảnh 1 = khung đầu, ảnh 2 = khung cuối") if limit == 2 else "")
        d = RefPickerDialog(self, self.lib, [], max_count=room, title=title)
        if d.exec():
            new = [p for p in self.lib.paths(d.selected_ids()) if p not in cur]
            if new:
                self._set_task_refs(r, (cur + new)[:limit])

    def _bulk_refs(self):
        """Nút "Ảnh tham chiếu" trên thanh tác vụ: chọn ảnh trong kho → thêm vào mọi tác vụ đã tick
        (giữ ảnh đang có, bỏ trùng, không vượt giới hạn; bỏ qua tác vụ đang chạy)."""
        rows = [r for r in self.model.checked_rows() if r["status"] not in ("running", "needs_user")]
        if not rows:
            msg = tr("Tick chọn các tác vụ cần thêm ảnh tham chiếu (hoặc ô chọn tất cả ở đầu danh sách).")
            if self.model.checked_rows():
                msg = tr("Các tác vụ đã tick đang chạy – không đổi ảnh tham chiếu được.")
            self.ctx.toast("info", msg)
            return
        limit = 2 if (self.video and self.mode == "i2v") else 10
        from ..refs_ui import RefPickerDialog
        title = tr("Ảnh tham chiếu cho") + f" {len(rows)} " + tr("tác vụ đã tick") + (
            " · " + tr("ảnh 1 = khung đầu, ảnh 2 = khung cuối") if limit == 2 else "")
        d = RefPickerDialog(self, self.lib, [], max_count=limit, title=title)
        if not d.exec():
            return
        picked = self.lib.paths(d.selected_ids())
        if not picked:
            return
        full = changed = 0
        frames = self.video and self.mode == "i2v"
        for r in rows:
            if frames:                                          # Ảnh → Video: điền vào ô Bắt đầu / Kết thúc còn trống
                slots = (list(r.get("refs_list") or []) + ["", ""])[:2]
                todo = [p for p in picked if p not in slots]
                if not todo:
                    continue
                if all(slots):
                    full += 1
                    continue
                for k in range(2):
                    if not slots[k] and todo:
                        slots[k] = todo.pop(0)
                self._set_task_refs(r, slots, quiet=True)
                changed += 1
                continue
            cur = [x for x in (r.get("refs_list") or []) if x]
            new = [p for p in picked if p not in cur]
            if not new:
                continue
            room = limit - len(cur)
            if room <= 0:
                full += 1
                continue
            self._set_task_refs(r, cur + new[:room], quiet=True)
            changed += 1
        msg = tr("Đã thêm ảnh tham chiếu cho") + f" {changed} " + tr("tác vụ")
        if full:
            msg += f" · {full} " + tr("tác vụ đã đủ ảnh, bỏ qua")
        self.ctx.toast("ok" if changed else "info", msg)

    def _task_frame(self, r: dict, k: int):
        """Ảnh → Video: ô Bắt đầu (k=0) / Kết thúc (k=1). Ô có ảnh → bấm để bỏ; ô trống → chọn 1 ảnh từ kho."""
        cur = list(r.get("refs_list") or []) + ["", ""]
        cur = cur[:2]
        if cur[k]:
            cur[k] = ""
        else:
            from ..refs_ui import RefPickerDialog
            title = tr("Ảnh bắt đầu") if k == 0 else tr("Ảnh kết thúc")
            d = RefPickerDialog(self, self.lib, [], max_count=1, title=title + f" · {tr('tác vụ')} #{r['row_no']}")
            if not d.exec():
                return
            got = self.lib.paths(d.selected_ids())
            if not got:
                return
            cur[k] = got[0]
        while cur and not cur[-1]:
            cur.pop()
        self._set_task_refs(r, cur, quiet=True)

    def _set_task_refs(self, r: dict, paths: list[str], quiet: bool = False):
        if r.get("draft"):
            if paths:
                self.model.draft_refs[r["prompt"]] = list(paths)
            else:
                self.model.draft_refs.pop(r["prompt"], None)
            self._save_state()
        else:
            import json as _json
            mode = r["mode"]
            if paths and mode == "t2i":
                mode = "i2i"
            elif paths and mode == "t2v":
                mode = "compose"
            elif not paths and mode == "i2i":
                mode = "t2i"
            elif not paths and mode == "compose":
                mode = "t2v"
            self.db.update_job(r["id"], refs=_json.dumps(paths, ensure_ascii=False), mode=mode)
        self.model.reload()
        if not quiet:
            self.ctx.toast("ok", tr("Đã cập nhật ảnh tham chiếu cho tác vụ") + f" #{r['row_no']} ({len([x for x in paths if x])} " + tr("ảnh") + ")")

    def _run_draft(self, r):
        if self._enqueue([r["prompt"]]):
            self._set_editor_lines([p for i, p in enumerate(self._prompts()) if i != r["index"]])

    def _to_library(self, paths):
        from ..refs_ui import import_with_names
        n = len(import_with_names(self, self.lib, paths))
        if n:
            self.ctx.toast("ok", tr("Đã thêm") + f" {n} " + tr("ảnh vào Kho ảnh tham chiếu"))

    def _edit(self, r):
        text, ok = QInputDialog.getMultiLineText(self, tr("Sửa prompt"), tr("Prompt:"), r["prompt"])
        if ok and text.strip():
            self.db.update_job(r["id"], prompt=text.strip())
            self.model.reload()

    def receive_start_frame(self, paths: list[str]):
        if not self.video or not paths:
            return
        self.lib.add(paths[0], None, "Bối cảnh")
        self.mode_seg.set_value(next(m.label for m in self.pdef.modes if m.key == "i2v"))
        self._mode_changed(next(m.label for m in self.pdef.modes if m.key == "i2v"))
        lines = self._prompts()
        prompt = tr("Chuyển động tự nhiên, máy quay chậm")
        k = 2
        while prompt in lines:
            prompt = tr("Chuyển động tự nhiên, máy quay chậm") + f" ({k})"
            k += 1
        self.model.draft_refs[prompt] = [paths[0]]
        self._set_editor_lines(lines + [prompt])

    # ================================================================ cập nhật
    def _set_filter(self, k):
        self.model.filter = k
        if k is None and self.model.scope:
            return self._set_scope(None)
        self.model.reload()
        self._update_empty()

    SCOPE_STYLE = {"running": ("#60a5fa", "#0f2547", "Đang chạy"), "queued": ("#fbbf24", "#2e2410", "Hàng đợi"),
                   "done": ("#4ade80", "#0f2e24", "Hoàn thành"), "failed": ("#fb7185", "#3a1520", "Lỗi")}

    def _set_scope(self, key):
        """key = ô đếm vừa bấm: hiện tác vụ trạng thái đó của mọi nền tảng; None: về danh sách của trang này."""
        self.model.scope = key
        self.model.filter = None
        self.model.checked.clear()
        self.model.reload()
        if key:
            fg, bg, name = self.SCOPE_STYLE[key]
            self.scope_bar.setStyleSheet(f"QFrame{{background:{bg};border:none;}}")
            self.scope_lbl.setStyleSheet(f"background:transparent;font-weight:700;color:{fg};")
        self._scope_text()
        self.scope_bar.setVisible(bool(key))
        self.filters.setExclusive(False)
        for b in self.filters.buttons():
            b.setChecked(not key)
        self.filters.setExclusive(not key)
        self._update_empty()
        self._checked_changed()

    def _scope_text(self):
        key = self.model.scope
        if key:
            self.scope_lbl.setText(tr("Đang xem") + f": {tr(self.SCOPE_STYLE[key][2])} · {len(self.model.rows)} "
                                   + tr("tác vụ") + " · " + tr("mọi nền tảng"))
        self.b_scope_retry.setVisible(key == "failed" and bool(self.model.rows))

    def _stat_click(self, key):
        if key == "accounts":
            self.ctx.win.open_settings()
            return
        # 4 ô đếm chung: hiện ngay trong danh sách tác vụ của trang này, gồm tác vụ của mọi nền tảng
        self._set_scope(None if self.model.scope == key else key)

    def focus_job(self, job_id: str, group: str):
        """Được mở từ danh sách tác vụ chung: lọc theo nhóm (Hoàn thành / Lỗi) và chọn, cuộn tới đúng dòng."""
        flt = group if group in ("done", "failed") else None
        for b in self.filters.buttons():
            b.setChecked(flt is None)
        self.filters.setExclusive(flt is None)
        self._set_filter(flt)
        for i, r in enumerate(self.model.rows):
            if r["id"] == job_id:
                idx = self.model.index(i, 0)
                self.table.scrollTo(idx)
                self.table.selectRow(i)
                self.model.checked = {job_id}
                self.model.layoutChanged.emit()
                self._checked_changed()
                break

    def _checked_changed(self):
        n = len(self.model.checked)
        self.sel_lbl.setText(f"· {tr('đã chọn')} {n}" if n else "")
        self.all_cb.setChecked(bool(self.model.rows) and n == len(self.model.rows))
        self._fit_toolbar()

    def eventFilter(self, obj, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.Resize and hasattr(self, "_tb"):
            self._fit_toolbar()
        return super().eventFilter(obj, e)

    def _fit_toolbar(self):
        """Khung tác vụ hẹp: ẩn bớt chữ "Tác vụ" / "đã chọn N" để các nút luôn đủ chỗ, không đè lên nhau."""
        tb = getattr(self, "_tb", None)
        if tb is None:
            return
        avail = tb.geometry().width() or (self.tasks_lbl.parentWidget().width() if self.tasks_lbl.parentWidget() else 0)
        m = tb.contentsMargins()
        avail -= m.left() + m.right()
        opt = (self.tasks_lbl, self.sel_lbl)
        ws = [tb.itemAt(i).widget() for i in range(tb.count())]
        ws = [w for w in ws if w is not None and w not in opt]
        need = sum(max(w.minimumWidth(), w.sizeHint().width()) for w in ws) + tb.spacing() * (len(ws) + 1)
        rest = avail - need
        lw = self.tasks_lbl.sizeHint().width() + tb.spacing()
        sw = (self.sel_lbl.sizeHint().width() + tb.spacing()) if self.sel_lbl.text() else 0
        self.tasks_lbl.setVisible(rest >= lw + sw)
        self.sel_lbl.setVisible(bool(self.sel_lbl.text()) and rest >= sw)

    def _flush(self):
        if self._dirty and self.isVisible():
            self._dirty = False
            self.model.reload()
            self.refresh_stats()
            self.apply_tier()

    def showEvent(self, e):
        super().showEvent(e)
        self.apply_tier()
        self.model.drafts = self._prompts()
        self.model.reload()
        self.refresh_stats()
        self._count_prompts()

    def hideEvent(self, e):
        self._save_state()
        super().hideEvent(e)

    def refresh_stats(self):
        c = self.db.counts(self.pdef.platform, self.key)          # trang này: thanh tiến độ, số trên menu
        running = c.get("running", 0) + c.get("needs_user", 0)
        failed = c.get("failed", 0) + c.get("blocked", 0)
        g = self.db.counts_all()                                  # 4 ô đếm: chung cho mọi nền tảng
        self.cards["running"].set(g.get("running", 0) + g.get("needs_user", 0))
        self.cards["queued"].set(g.get("queued", 0))
        self.cards["done"].set(g.get("done", 0))
        self.cards["failed"].set(g.get("failed", 0) + g.get("blocked", 0))
        ready, ok = self._accounts()
        self.cards["accounts"].set(ok)
        total = sum(v for k, v in c.items() if k != "cancelled")
        finished = c.get("done", 0) + failed
        self.bar.set(finished / total if total else 0)
        self.bar_lbl.setText(f"{finished} / {total}" + (f" · {int(100 * finished / total)}%" if total else ""))
        self.ctx.set_badge(self.key, running + c.get("queued", 0))
        if self.model.scope:
            self._scope_text()
        self._update_empty()
        self._checked_changed()

    def _update_empty(self):
        has = self.model.rowCount() > 0
        self.table.setVisible(has)
        self.empty.setVisible(not has)

    def _on_state(self, key, state):
        if key != self.key:
            return
        running = state == "running"
        self.b_start.setText(tr("Chạy tiếp") if running else tr("Bắt đầu"))
        self.b_pause.setEnabled(running)
