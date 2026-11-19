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
from ...core.i18n import tr
from ...core.paths import default_output_dir
from ...core.platforms import PageDef
from ...services import prompt_io

DELAY = (10, 15)   # tài khoản chạy xong 1 tác vụ thì nghỉ 10–15 giây (ngẫu nhiên) rồi mới nhận tác vụ kế tiếp


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
        else:
            self.ratio = combo(self.pdef.ratios, self.st.get("ratio"))
            g.addWidget(field("Tỷ lệ khung hình", self.ratio), 0, 1)
        qs = self.pdef.extra.get("quality", [])
        self.quality = Seg(qs, self.st.get("quality", qs[0]))
        self.quality.setToolTip(tr("Bản cao hơn bản gốc do Flow tăng độ phân giải khi tải về (mất thêm thời gian)"))
        cfg.add(g)
        cfg.add(field("Chất lượng tải về", self.quality))
        self.count = Seg(["1", "2", "3", "4"], str(self.st.get("count", 1)))
        cfg.add(field("Số kết quả mỗi prompt", self.count))

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
        b_imp = button("Nhập tệp (TXT, Excel)", "primary", "upload")
        b_imp.clicked.connect(self._import)
        b_ai = button("AI", None, "wand", "#f0abfc")
        b_ai.setToolTip(tr("Sửa / viết prompt bằng AI"))
        b_ai.clicked.connect(self._ai_menu)
        ar.addWidget(b_imp, 3)
        ar.addWidget(b_ai, 1)
        left.addLayout(ar)
        pbox = QFrame()
        pbox.setObjectName("card")
        pv = QVBoxLayout(pbox)
        pv.setContentsMargins(6, 6, 6, 8)
        self.editor = PromptEditor()
        self.editor.setStyleSheet("QPlainTextEdit{border:none;background:transparent;}")
        self.editor.setPlaceholderText(tr("Mỗi dòng là một prompt = một tác vụ.\nGõ @Tên để dùng ảnh trong Kho ảnh tham chiếu cho dòng đó."))
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
        tb.addWidget(label("Tác vụ", "h2"))
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
        b_del = button("Xóa", "stop", "trash", C["danger"])
        b_del.setToolTip(tr("Xóa các tác vụ đã tick"))
        b_del.setStyleSheet(f"QPushButton{{padding:5px 12px;background:{C['danger-bg']};border:1px solid #62202f;color:{C['danger']};}}")
        b_del.clicked.connect(self._delete_checked)
        tb.addWidget(b_del)
        b_del_all = button("Xóa tất cả", "stop", "trash", C["danger"])
        b_del_all.setToolTip(tr("Xóa toàn bộ tác vụ trong danh sách (không cần tick)"))
        b_del_all.setStyleSheet(f"QPushButton{{padding:5px 12px;background:{C['danger-bg']};border:1px solid #62202f;color:{C['danger']};}}")
        b_del_all.clicked.connect(self._delete_all)
        tb.addWidget(b_del_all)
        b_run_sel = button("Chạy", "chip", "play", "#4ade80")
        b_run_sel.setToolTip(tr("Chỉ chạy các tác vụ đã tick (tác vụ chưa chạy hoặc bị lỗi)"))
        b_run_sel.clicked.connect(self.run_selected)
        tb.addWidget(b_run_sel)
        for text, ic, fn in (("Chạy lại tất cả tác vụ lỗi", "retry", self._retry),
                             ("Mở thư mục lưu", "folder", lambda: open_path(self._ensure_out())),
                             ("Hiện / ẩn trình duyệt đang chạy", "eye", self._toggle_browser)):
            b = icon_button(ic, text, "#67e8f9")
            b.setFixedSize(32, 30)
            b.clicked.connect(fn)
            tb.addWidget(b)
        rv.addLayout(tb)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background:{C['border']};")
        rv.addWidget(line)
        self.model = TaskModel(self.db, self.key)
        self.model.draft_refs = {k: [x for x in v if not x or Path(x).exists()]
                                 for k, v in (self.st.get("draft_refs") or {}).items()}
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
              "draft_refs": {k: v for k, v in self.model.draft_refs.items() if v and k in set(self._prompts())}}
        if self.video:
            st.update({"ratio": self.ratio.value(), "seconds": self.dur.value(),
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

    def _ai_menu(self):
        m = QMenu(self)
        m.addAction(tr("Sửa lại các prompt cho rõ ràng hơn"), self._ai_fix)
        m.addAction(tr("Viết chuỗi prompt từ một ý tưởng"), self._ai_write)
        m.exec(self.cursor().pos())

    def _ai_fix(self):
        from ...services import llm
        ps = self._prompts()
        if not ps:
            return
        try:
            self.ctx.busy(True)
            self.editor.setPlainText("\n".join(p.replace("\n", " ") for p in llm.fix_prompts(self.db, ps)))
        except Exception as e:
            self.ctx.toast("error", str(e))
        finally:
            self.ctx.busy(False)

    def _ai_write(self):
        from ...services import llm
        idea, ok = QInputDialog.getMultiLineText(self, tr("Viết prompt bằng AI"), tr("Ý tưởng / cốt truyện:"))
        if not ok or not idea.strip():
            return
        n, ok = QInputDialog.getInt(self, tr("Số cảnh"), tr("Bao nhiêu prompt?"), 8, 1, 100)
        if not ok:
            return
        try:
            self.ctx.busy(True)
            self.editor.setPlainText("\n".join(llm.write_story(self.db, idea, n)))
        except Exception as e:
            self.ctx.toast("error", str(e))
        finally:
            self.ctx.busy(False)

    # ================================================================ chạy
    def _params(self) -> dict:
        q = self.quality.value()
        if self.video:
            ratio = "16:9 Ngang" if self.ratio.value() == "16:9" else "9:16 Dọc"
            m = self.model_cb.currentText()
            p = {"model": m, "ratio": ratio, "quality": q}
            if m.lower().startswith("omni"):
                p["resolutions"] = "720p"          # tạo ở độ phân giải cao nhất Flow cho phép
            if self.pdef.extra.get("durations", {}).get(m):
                p["durations"] = f"{self.dur.value()} giây"
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
            mode = self.mode
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
            rows.append({"mode": mode, "prompt": text, "refs": refs[:10], "count": int(self.count.value())})
        return rows

    def _ready_or_warn(self) -> list[str] | None:
        ready, _ = self._accounts()
        if not ready:
            QMessageBox.information(self, tr("Chưa có tài khoản"),
                                    tr("Chưa có tài khoản Google Flow nào đăng nhập.\nVào Cài Đặt › Tài khoản › Thêm tài khoản "
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
        """True = được chạy. Gói Miễn phí: chỉ 1 tác vụ tại một thời điểm (toàn phần mềm)."""
        if not self._is_free():
            return True
        if self._busy_any():
            self.ctx.win.upsell(tr("Đang có 1 tác vụ chạy. Chờ tác vụ này xong rồi tạo tác vụ tiếp theo."))
            return False
        if n_new > 1:
            self.ctx.win.upsell(tr("Gói Miễn phí chỉ tạo 1 tác vụ mỗi lần") + f" ({tr('đang có')} {n_new} prompt).")
            return False
        return True

    def apply_tier(self):
        """Khóa ô nhập prompt khi gói Miễn phí đang có tác vụ chạy."""
        if not hasattr(self, "free_lbl"):
            return
        free = self._is_free()
        busy = free and self._busy_any() > 0
        self.editor.setReadOnly(busy)
        self.editor.setStyleSheet("QPlainTextEdit{border:none;background:transparent;" +
                                  ("color:#7f8bc4;}" if busy else "}"))
        if busy:
            self.free_lbl.setText(tr("Đang tạo 1 tác vụ · chờ xong mới nhập prompt mới"))
            self.free_lbl.setToolTip(tr("Gói Miễn phí: mỗi lần 1 tác vụ. Nâng cấp Chuyên nghiệp để chạy hàng loạt."))
        else:
            self.free_lbl.setText(tr("Gói Miễn phí: mỗi lần 1 tác vụ (1 dòng prompt)"))
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
        self._save_state()
        self.db.create_batch(self.pdef.platform, self.key, self._params(), self._ensure_out(), "flat", rows)
        for p_ in prompts:
            self.model.draft_refs.pop(p_, None)
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
            lines[index] = text
            self.editor.blockSignals(True)
            self.editor.setPlainText("\n".join(lines))
            self.editor.blockSignals(False)
            self._count_prompts()

    def _stop(self):
        if QMessageBox.question(self, tr("Dừng"), tr("Hủy tất cả tác vụ đang chờ và đang chạy?")) == QMessageBox.Yes:
            self.ctx.engine.stop_page(self.key)

    def _requeue(self, rows):
        todo = [r for r in rows if not r.get("draft") and r["status"] not in ("running", "queued")]
        if todo and not self._free_guard(len(todo)):
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

    def _task_refs(self, r: dict):
        """Bấm ô ảnh tham chiếu của 1 tác vụ: đang có ảnh → bỏ ảnh; ô trống → mở Kho ảnh tham chiếu."""
        cur = list(r.get("refs_list") or [])
        if cur:
            self._set_task_refs(r, [])
            return
        limit = 2 if (self.video and self.mode == "i2v") else 10
        from ..refs_ui import RefPickerDialog
        title = tr("Ảnh tham chiếu cho tác vụ") + f" #{r['row_no']}" + (
            " · " + tr("ảnh 1 = khung đầu, ảnh 2 = khung cuối") if limit == 2 else "")
        d = RefPickerDialog(self, self.lib, [], max_count=limit, title=title)
        if d.exec():
            new = self.lib.paths(d.selected_ids())
            if new:
                self._set_task_refs(r, new[:limit])

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
        self.model.reload()
        self._update_empty()

    def _stat_click(self, key):
        if key == "accounts":
            self.ctx.win.open_settings()
            return
        flt = None if key in ("queued", "running") else key
        for b in self.filters.buttons():
            b.setChecked(flt is None)
        self.filters.setExclusive(flt is None)
        self._set_filter(flt)

    def _checked_changed(self):
        n = len(self.model.checked)
        self.sel_lbl.setText(f"· {tr('đã chọn')} {n}" if n else "")
        self.all_cb.setChecked(bool(self.model.rows) and n == len(self.model.rows))

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
        c = self.db.counts(self.pdef.platform, self.key)
        running = c.get("running", 0) + c.get("needs_user", 0)
        failed = c.get("failed", 0) + c.get("blocked", 0)
        self.cards["running"].set(running)
        self.cards["queued"].set(c.get("queued", 0))
        self.cards["done"].set(c.get("done", 0))
        self.cards["failed"].set(failed)
        ready, ok = self._accounts()
        self.cards["accounts"].set(ok)
        total = sum(v for k, v in c.items() if k != "cancelled")
        finished = c.get("done", 0) + failed
        self.bar.set(finished / total if total else 0)
        self.bar_lbl.setText(f"{finished} / {total}" + (f" · {int(100 * finished / total)}%" if total else ""))
        self.ctx.set_badge(self.key, running + c.get("queued", 0))
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
