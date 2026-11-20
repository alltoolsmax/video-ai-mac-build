"""Trang tạo nội dung hàng loạt (dùng chung cho mọi mục: Flow Ảnh, Flow Video, Dreamina, Grok...)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QSize, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
                               QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget)

from ..task_table import TaskModel, TaskTable
from ..theme import C, icon
from ..widgets import (Card, FrameSlot, GradientBar, PathPicker, PromptEditor, StatCard, button, combo, field,
                       icon_button, label)
from ...core.i18n import tr
from ...core.paths import default_output_dir
from ...core.platforms import PLATFORM_LABELS, PageDef
from ...services import prompt_io

DELAYS = {"Không chờ": (0, 0), "2–5 giây": (2, 5), "5–10 giây": (5, 10), "10–20 giây": (10, 20),
          "20–40 giây": (20, 40), "40–90 giây": (40, 90)}
SAVE_MODES = {"Thư mục theo từng hàng": "per_task", "Thư mục theo lần chạy": "per_batch", "Chung một thư mục": "flat"}


def open_path(p: str):
    if sys.platform.startswith("win"):
        os.startfile(p)  # noqa
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(p))


def reveal(p: str):
    if sys.platform.startswith("win") and Path(p).exists():
        subprocess.Popen(["explorer", "/select,", str(Path(p))])
    else:
        open_path(str(Path(p).parent if Path(p).is_file() else p))


class AccountPicker(QListWidget):
    """Danh sách tài khoản có ô tick: chọn một hoặc nhiều tài khoản để chạy song song."""

    def __init__(self):
        super().__init__()
        self.setFixedHeight(92)
        self.setSelectionMode(QListWidget.NoSelection)
        self.itemChanged.connect(lambda _: None)

    def set_accounts(self, accs: list[dict], checked: list[str]):
        self.blockSignals(True)
        self.clear()
        for a in accs:
            mark = {"ok": "●", "expired": "○", "needs_user": "◐"}.get(a["status"], "·")
            state = {"ok": "đã đăng nhập", "expired": "chưa đăng nhập", "needs_user": "chờ xác minh"}.get(a["status"], "chưa kiểm tra")
            it = QListWidgetItem(f"{mark}  {a['label']}   ·  {tr(state)}")
            it.setData(Qt.UserRole, a["id"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            on = a["id"] in checked or (not checked and a is accs[0])
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            self.addItem(it)
        if not accs:
            it = QListWidgetItem(tr("Chưa có tài khoản – thêm ở Cài Đặt › Tài khoản"))
            it.setFlags(Qt.NoItemFlags)
            self.addItem(it)
        self.blockSignals(False)

    def selected(self) -> list[str]:
        out = []
        for i in range(self.count()):
            it = self.item(i)
            if it.data(Qt.UserRole) and it.checkState() == Qt.Checked:
                out.append(it.data(Qt.UserRole))
        return out

    def currentData(self):
        sel = self.selected()
        return sel[0] if sel else None


class GenPage(QWidget):
    def __init__(self, ctx, pdef: PageDef):
        super().__init__()
        self.ctx = ctx
        self.pdef = pdef
        self.db = ctx.db
        self.key = pdef.key
        self.st = self.db.get_setting(f"page_{self.key}", {}) or {}
        self.mode = self.st.get("mode", pdef.modes[0].key)
        self.refs: list[str] = list(self.st.get("refs", []))
        self._build()
        self.model.reload()
        self.refresh_stats()
        self._dirty = False
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._flush)
        self._timer.start()
        ctx.engine.job_updated.connect(self._on_job)
        ctx.engine.page_state.connect(self._on_state)
        ctx.engine.account_updated.connect(lambda _: self.reload_accounts())

    # ================================================================ UI
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)

        # thống kê
        sr = QHBoxLayout()
        sr.setSpacing(10)
        self.cards = {k: StatCard(k) for k in ("running", "queued", "done", "failed", "accounts")}
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

        # ----- cột trái -----
        left_w = QWidget()
        left_w.setFixedWidth(480)
        left = QVBoxLayout(left_w)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 4, 0)
        iv.setSpacing(10)
        scroll.setWidget(inner)
        scroll.setFrameShape(QFrame.NoFrame)
        inner.setObjectName("inner")
        inner.setStyleSheet("QWidget#inner{background:transparent;}")
        scroll.viewport().setAutoFillBackground(False)

        basic = Card("Cấu hình cơ bản", "sliders")
        # chế độ
        if len(self.pdef.modes) > 1:
            mrow = QHBoxLayout()
            mrow.setSpacing(6)
            self.mode_group = QButtonGroup(self)
            for m in self.pdef.modes:
                b = QPushButton(tr(m.label))
                b.setProperty("kind", "chip")
                b.setCheckable(True)
                b.setChecked(m.key == self.mode)
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, k=m.key: self._set_mode(k))
                self.mode_group.addButton(b)
                mrow.addWidget(b)
            mrow.addStretch()
            basic.add(mrow)
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        self.model_cb = combo(self.pdef.models, self.st.get("model"))
        self.ratio_cb = combo(self.pdef.ratios, self.st.get("ratio"))
        self.conc = QSpinBox()
        self.conc.setRange(1, int(self.db.get_setting("max_concurrency", 3)))
        self.conc.setValue(int(self.st.get("concurrency", 1)))
        self.delay_cb = combo(list(DELAYS), self.st.get("delay", "5–10 giây"))
        self.save_cb = combo(list(SAVE_MODES), self.st.get("save_mode", "Thư mục theo từng hàng"))
        self.count = QSpinBox()
        self.count.setRange(1, self.pdef.max_count)
        self.count.setValue(int(self.st.get("count", 1)))
        self.acc_cb = AccountPicker()
        self.failover = QCheckBox(tr("Tự chuyển sang tài khoản khác khi một tài khoản hết tín dụng / bị đăng xuất / lỗi kỹ thuật"))
        self.failover.setChecked(bool(self.st.get("failover", True)))
        g.addWidget(field("Model", self.model_cb), 0, 0)
        g.addWidget(field("Tỷ lệ khung hình", self.ratio_cb), 0, 1)
        g.addWidget(field("Số hàng đồng thời / tài khoản", self.conc), 1, 0)
        g.addWidget(field("Thời gian chờ giữa các hàng", self.delay_cb), 1, 1)
        g.addWidget(field("Chế độ lưu", self.save_cb), 2, 0)
        g.addWidget(field("Số kết quả mỗi prompt", self.count), 2, 1)
        row = 3
        self.extra_cbs = {}
        ex = self.pdef.extra
        col = 0
        for k, title in (("resolutions", "Độ phân giải"), ("durations", "Thời lượng")):
            if k in ex:
                cb = combo(ex[k], self.st.get(k))
                self.extra_cbs[k] = cb
                g.addWidget(field(title, cb), row, col)
                col += 1
        if col:
            row += 1
        g.addWidget(field("Tài khoản " + PLATFORM_LABELS.get(self.pdef.platform, "") + " (tick nhiều để chạy song song)",
                          self.acc_cb), row, 0, 1, 2)
        row += 1
        g.addWidget(self.failover, row, 0, 1, 2)
        row += 1
        self.out = PathPicker(self.st.get("save_dir") or str(default_output_dir() / self.key))
        g.addWidget(field("Thư mục lưu", self.out), row, 0, 1, 2)
        basic.add(g)
        iv.addWidget(basic)

        # nâng cao
        adv = Card("Cấu hình nâng cao · Ảnh tham chiếu", "image", collapsible=True,
                   collapsed=not self.refs, icon_color="#f9a8d4")
        self.frames_w = QWidget()
        fl = QHBoxLayout(self.frames_w)
        fl.setContentsMargins(0, 0, 0, 0)
        self.first_slot = FrameSlot("Ảnh đầu")
        self.last_slot = FrameSlot("Ảnh cuối (tùy chọn)")
        self.first_slot.set_path(self.st.get("first", ""))
        self.last_slot.set_path(self.st.get("last", ""))
        fl.addWidget(self.first_slot)
        fl.addWidget(self.last_slot)
        adv.add(field("Khung hình (dùng chung cho mọi hàng, bỏ trống nếu dùng danh sách ảnh bên dưới)", self.frames_w))
        self.ref_list = QListWidget()
        self.ref_list.setFixedHeight(96)
        self.ref_list.setViewMode(QListWidget.IconMode)
        self.ref_list.setIconSize(QSize(64, 64))
        self.ref_list.setResizeMode(QListWidget.Adjust)
        self._fill_refs()
        rb = QHBoxLayout()
        b_add = button("Thêm ảnh", "chip", "plus", "#67e8f9")
        b_add.clicked.connect(self._add_refs)
        b_clear = button("Xóa hết", "chip", "trash", "#fb7185")
        b_clear.clicked.connect(self._clear_refs)
        self.ref_mode = combo(["Dùng chung cho mọi hàng", "Mỗi ảnh ứng với một hàng"], self.st.get("ref_mode"))
        rb.addWidget(b_add)
        rb.addWidget(b_clear)
        rb.addWidget(self.ref_mode, 1)
        adv.add(field("Ảnh tham chiếu", self.ref_list))
        adv.add(rb)
        self.prefix = QLineEdit(self.st.get("prefix", ""))
        self.prefix.setPlaceholderText(tr("vd: cinematic, 35mm film, ..."))
        self.suffix = QLineEdit(self.st.get("suffix", ""))
        self.suffix.setPlaceholderText(tr("vd: no text, no watermark-like logos"))
        adv.add(field("Thêm vào đầu mỗi prompt", self.prefix))
        adv.add(field("Thêm vào cuối mỗi prompt", self.suffix))
        self.char_desc = QCheckBox(tr("Thay @Tên bằng mô tả nhân vật và gửi kèm ảnh nhân vật"))
        self.char_desc.setChecked(self.st.get("char_desc", True))
        adv.add(self.char_desc)
        self.timeout = QSpinBox()
        self.timeout.setRange(60, 1800)
        self.timeout.setSuffix(" " + tr("giây"))
        self.timeout.setValue(int(self.st.get("timeout", 600 if self.pdef.kind == "video" else 240)))
        adv.add(field("Thời gian chờ tối đa mỗi hàng", self.timeout))
        iv.addWidget(adv)
        iv.addStretch()
        left.addWidget(scroll, 0)
        scroll.setMaximumHeight(430)

        # nhập prompt
        ar = QHBoxLayout()
        ar.setSpacing(8)
        b_imp = button("Nhập tệp (TXT, Excel)", "primary", "upload")
        b_imp.clicked.connect(self._import)
        self.split_cb = combo(["1 hàng | 1 prompt", "Cách nhau dòng trống"], self.st.get("split"))
        b_ai = button("AI", None, "wand", "#f0abfc")
        b_ai.setToolTip(tr("Sửa / viết prompt bằng AI"))
        b_ai.clicked.connect(self._ai_menu)
        ar.addWidget(b_imp, 3)
        ar.addWidget(self.split_cb, 2)
        ar.addWidget(b_ai, 1)
        left.addLayout(ar)
        pbox = QFrame()
        pbox.setObjectName("card")
        pv = QVBoxLayout(pbox)
        pv.setContentsMargins(6, 6, 6, 8)
        self.editor = PromptEditor()
        self.editor.setStyleSheet("QPlainTextEdit{border:none;background:transparent;}")
        self.editor.setPlainText(self.st.get("draft", ""))
        self.editor.files_dropped.connect(self._load_files)
        self.editor.textChanged.connect(self._count_prompts)
        pv.addWidget(self.editor, 1)
        foot = QHBoxLayout()
        self.one_for_all = QCheckBox(tr("Dùng một prompt cho tất cả"))
        self.repeat = QSpinBox()
        self.repeat.setRange(1, 500)
        self.repeat.setValue(int(self.st.get("repeat", 5)))
        self.repeat.setPrefix("× ")
        self.repeat.setVisible(False)
        self.one_for_all.toggled.connect(self.repeat.setVisible)
        self.one_for_all.toggled.connect(lambda _: self._count_prompts())
        self.repeat.valueChanged.connect(lambda _: self._count_prompts())
        self.split_cb.currentIndexChanged.connect(lambda _: self._count_prompts())
        self.pcount = label("0 prompt", "faint")
        foot.addWidget(self.one_for_all)
        foot.addWidget(self.repeat)
        foot.addStretch()
        foot.addWidget(self.pcount)
        pv.addLayout(foot)
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
        cols.addWidget(left_w)

        # ----- cột phải: bảng -----
        right = QFrame()
        right.setObjectName("card")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        tb = QHBoxLayout()
        tb.setContentsMargins(12, 10, 12, 10)
        tb.setSpacing(6)
        tb.addWidget(label("Danh sách tác vụ", "h2"))
        self.filters = QButtonGroup(self)
        for key, text in ((None, "Tất cả"), ("done", "Xong"), ("running", "Đang chạy"), ("queued", "Chờ"), ("failed", "Lỗi")):
            b = QPushButton(tr(text))
            b.setProperty("kind", "chip")
            b.setCheckable(True)
            b.setChecked(key is None)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._set_filter(k))
            self.filters.addButton(b)
            tb.addWidget(b)
        tb.addStretch()
        for text, ic, fn in (("Mở thư mục", "folder", lambda: open_path(self._ensure_out())),
                             ("Chạy lại lỗi", "retry", self._retry_failed),
                             ("Xóa đã xong", "trash", self._clear_done)):
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
        self.table = TaskTable(self.model)
        self.table.action.connect(self._row_action)
        self.empty = QLabel(tr("Chưa có tác vụ nào.\nDán prompt bên trái rồi bấm Bắt đầu."))
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setObjectName("muted")
        rv.addWidget(self.table, 1)
        rv.addWidget(self.empty, 1)
        cols.addWidget(right, 1)

        self.reload_accounts()
        self._apply_mode_ui()
        self._count_prompts()
        self._on_state(self.key, "running" if self.ctx.engine.is_running(self.key) else "idle")

    # ================================================================ helpers
    def _set_mode(self, k):
        self.mode = k
        self._apply_mode_ui()
        self._save_state()

    def _apply_mode_ui(self):
        m = next(m for m in self.pdef.modes if m.key == self.mode)
        self.frames_w.parentWidget().setVisible(m.frames)

    def reload_accounts(self):
        cur = self.acc_cb.selected() or self.st.get("account_ids") or ([self.st["account_id"]] if self.st.get("account_id") else [])
        accs = [a for a in self.db.accounts(self.pdef.platform) if a["enabled"]]
        self.acc_cb.set_accounts(accs, cur)
        self.cards["accounts"].set(len(accs))

    def _fill_refs(self):
        from PySide6.QtGui import QIcon, QPixmap
        self.ref_list.clear()
        for p in self.refs:
            it = QListWidgetItem(QIcon(QPixmap(p)), Path(p).name[:12])
            it.setToolTip(p)
            self.ref_list.addItem(it)

    def _add_refs(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Chọn ảnh tham chiếu"), "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
        if fs:
            self.refs += [f for f in fs if f not in self.refs]
            self._fill_refs()
            self._save_state()

    def _clear_refs(self):
        self.refs = []
        self._fill_refs()
        self._save_state()

    def _prompts(self) -> list[str]:
        mode = "block" if self.split_cb.currentIndex() == 1 else "line"
        ps = prompt_io.split_prompts(self.editor.toPlainText(), mode)
        if self.one_for_all.isChecked() and ps:
            ps = [ps[0]] * self.repeat.value()
        return ps

    def _count_prompts(self):
        self.pcount.setText(f"{len(self._prompts())} prompt")

    def _import(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Nhập prompt"), "", "Prompt (*.txt *.csv *.xlsx)")
        if fs:
            self._load_files(fs)

    def _load_files(self, files):
        ps = []
        for f in files:
            try:
                ps += prompt_io.load_file(f)
            except Exception as e:
                self.ctx.toast("error", f"{Path(f).name}: {e}")
        if ps:
            sep = "\n\n" if self.split_cb.currentIndex() == 1 else "\n"
            cur = self.editor.toPlainText().strip()
            self.editor.setPlainText((cur + sep if cur else "") + sep.join(ps))
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
            out = llm.fix_prompts(self.db, ps)
            self.editor.setPlainText("\n".join(out))
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

    def _params(self) -> dict:
        p = {"model": self.model_cb.currentText(), "ratio": self.ratio_cb.currentText(),
             "timeout_s": self.timeout.value()}
        for k, cb in self.extra_cbs.items():
            p[k] = cb.currentText()
        return p

    def _ensure_out(self) -> str:
        d = self.out.text() or str(default_output_dir() / self.key)
        Path(d).mkdir(parents=True, exist_ok=True)
        return d

    def _save_state(self):
        st = {"mode": self.mode, "model": self.model_cb.currentText(), "ratio": self.ratio_cb.currentText(),
              "concurrency": self.conc.value(), "delay": self.delay_cb.currentText(),
              "save_mode": self.save_cb.currentText(), "count": self.count.value(),
              "account_ids": self.acc_cb.selected(), "failover": self.failover.isChecked(), "save_dir": self.out.text(), "refs": self.refs,
              "ref_mode": self.ref_mode.currentText(), "prefix": self.prefix.text(), "suffix": self.suffix.text(),
              "char_desc": self.char_desc.isChecked(), "timeout": self.timeout.value(),
              "first": self.first_slot.path, "last": self.last_slot.path,
              "split": self.split_cb.currentText(), "repeat": self.repeat.value(),
              "draft": self.editor.toPlainText()[:200000]}
        for k, cb in self.extra_cbs.items():
            st[k] = cb.currentText()
        self.db.set_setting(f"page_{self.key}", st)

    # ================================================================ chạy
    def start(self):
        acc = self.acc_cb.selected()
        if not acc:
            QMessageBox.information(self, tr("Chưa chọn tài khoản"),
                                    tr("Hãy thêm, đăng nhập và tick ít nhất một tài khoản (Cài Đặt › Tài khoản)."))
            return
        prompts = self._prompts()
        m = next(m for m in self.pdef.modes if m.key == self.mode)
        rows = []
        per_row = self.ref_mode.currentIndex() == 1
        if not prompts and per_row and self.refs:
            prompts = [""] * len(self.refs)
        if not prompts:
            self.ctx.toast("warn", tr("Chưa có prompt nào."))
            return
        pre, suf = self.prefix.text().strip(), self.suffix.text().strip()
        for i, p in enumerate(prompts):
            text, char_refs = self.ctx.characters.expand(p, self.char_desc.isChecked())
            text = " ".join(x for x in (pre, text, suf) if x)
            refs: list[str] = []
            if m.frames and self.first_slot.path:
                refs.append(self.first_slot.path)
                if self.last_slot.path:
                    refs.append(self.last_slot.path)
            if self.refs:
                if per_row:
                    if i < len(self.refs):
                        refs.append(self.refs[i])
                else:
                    refs += self.refs
            if self.char_desc.isChecked():
                refs += [r for r in char_refs if r not in refs]
            if m.needs_ref and not refs:
                self.ctx.toast("warn", tr("Chế độ này cần ảnh tham chiếu (mục Cấu hình nâng cao)."))
                return
            rows.append({"mode": self.mode, "prompt": text, "refs": refs, "count": self.count.value()})
        self._save_state()
        save_dir = self._ensure_out()
        self.db.create_batch(self.pdef.platform, self.key, self._params(), save_dir,
                             SAVE_MODES[self.save_cb.currentText()], rows)
        self.ctx.engine.start_page(self.key, acc, self.conc.value(), DELAYS[self.delay_cb.currentText()],
                                           self.failover.isChecked())
        self.model.reload()
        self.refresh_stats()
        self.ctx.toast("info", tr("Đã thêm") + f" {len(rows)} " + tr("hàng vào hàng đợi."))

    def _stop(self):
        if QMessageBox.question(self, tr("Dừng"), tr("Hủy tất cả tác vụ đang chờ và đang chạy của trang này?")) == QMessageBox.Yes:
            self.ctx.engine.stop_page(self.key)

    def _toggle_browser(self):
        opened = [a for a in self.acc_cb.selected() if self.ctx.engine.browser.is_open(a)]
        if not opened:
            self.ctx.toast("info", tr("Trình duyệt chưa mở. Nó sẽ tự mở (ẩn) khi bạn bấm Bắt đầu."))
            return
        show = self.ctx.engine.browser_hidden(opened[0])
        for a in opened:
            self.ctx.engine.set_browser_visible(a, show)

    def _retry_failed(self):
        rows = self.db.query("SELECT j.id FROM jobs j JOIN batches b ON b.id=j.batch_id WHERE b.page=?"
                             " AND j.status IN ('failed','blocked','cancelled')", (self.key,))
        for r in rows:
            self.db.update_job(r["id"], status="queued", progress=0, error_code=None, error_text=None)
        if rows:
            acc = self.acc_cb.selected()
            if acc:
                self.ctx.engine.start_page(self.key, acc, self.conc.value(), DELAYS[self.delay_cb.currentText()],
                                           self.failover.isChecked())
        self.model.reload()
        self.refresh_stats()

    def _clear_done(self):
        self.db.execute("DELETE FROM jobs WHERE status IN ('done','cancelled') AND batch_id IN (SELECT id FROM batches WHERE page=?)",
                        (self.key,))
        self.db.execute("DELETE FROM batches WHERE page=? AND id NOT IN (SELECT DISTINCT batch_id FROM jobs)", (self.key,))
        self.model.reload()
        self.refresh_stats()

    def _row_action(self, kind, r):
        if kind == "open":
            outs = self.db.outputs(r["id"])
            if outs:
                open_path(outs[0]["path"])
            return
        m = QMenu(self)
        outs = self.db.outputs(r["id"])
        if outs:
            m.addAction(icon("eye", "#67e8f9"), tr("Mở kết quả"), lambda: open_path(outs[0]["path"]))
            m.addAction(icon("folder", "#67e8f9"), tr("Mở thư mục chứa"), lambda: reveal(outs[0]["path"]))
            if self.pdef.kind == "image" and any(o["kind"] == "image" for o in outs):
                m.addAction(icon("video", "#c4a5ff"), tr("Gửi ảnh sang Flow Video (Ảnh → Video)"),
                            lambda: self.ctx.send_to_video([o["path"] for o in outs if o["kind"] == "image"]))
        m.addAction(icon("edit", "#fbbf24"), tr("Sửa prompt"), lambda: self._edit(r))
        m.addAction(icon("retry", "#4ade80"), tr("Chạy lại"), lambda: self._requeue([r]))
        m.addAction(icon("trash", "#fb7185"), tr("Xóa"), lambda: self._delete([r]))
        sel = self.table.selected_rows()
        if len(sel) > 1:
            m.addSeparator()
            m.addAction(tr("Chạy lại") + f" {len(sel)} " + tr("hàng đã chọn"), lambda: self._requeue(sel))
            m.addAction(tr("Xóa") + f" {len(sel)} " + tr("hàng đã chọn"), lambda: self._delete(sel))
        m.exec(self.cursor().pos())

    def _edit(self, r):
        text, ok = QInputDialog.getMultiLineText(self, tr("Sửa prompt"), tr("Prompt:"), r["prompt"])
        if ok and text.strip():
            self.db.update_job(r["id"], prompt=text.strip())
            self.model.reload()

    def _requeue(self, rows):
        for r in rows:
            if r["status"] != "running":
                self.db.update_job(r["id"], status="queued", progress=0, error_code=None, error_text=None)
        acc = self.acc_cb.selected()
        if acc:
            self.ctx.engine.start_page(self.key, acc, self.conc.value(), DELAYS[self.delay_cb.currentText()],
                                           self.failover.isChecked())
        self.model.reload()
        self.refresh_stats()

    def _delete(self, rows):
        for r in rows:
            if r["status"] != "running":
                self.db.execute("DELETE FROM jobs WHERE id=?", (r["id"],))
        self.model.reload()
        self.refresh_stats()

    def _set_filter(self, k):
        self.model.filter = k
        self.model.reload()
        self._update_empty()

    def _stat_click(self, key):
        mapping = {"running": "running", "queued": "queued", "done": "done", "failed": "failed"}
        if key == "accounts":
            self.ctx.go("settings")
            return
        k = mapping[key]
        for b in self.filters.buttons():
            b.setChecked(b.text() == tr({"running": "Đang chạy", "queued": "Chờ", "done": "Xong", "failed": "Lỗi"}[k]))
        self._set_filter(k)

    # ================================================================ cập nhật
    def _on_job(self, _jid):
        self._dirty = True

    def _flush(self):
        if self._dirty and self.isVisible():
            self._dirty = False
            self.model.reload()
            self.refresh_stats()

    def showEvent(self, e):
        super().showEvent(e)
        self.reload_accounts()
        self.model.reload()
        self.refresh_stats()

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
        total = sum(v for k, v in c.items() if k != "cancelled")
        finished = c.get("done", 0) + failed
        self.bar.set(finished / total if total else 0)
        self.bar_lbl.setText(f"{finished} / {total}" + (f" · {int(100 * finished / total)}%" if total else ""))
        self.ctx.set_badge(self.key, running + c.get("queued", 0))
        self._update_empty()

    def _update_empty(self):
        has = self.model.rowCount() > 0
        self.table.setVisible(has)
        self.empty.setVisible(not has)

    def _on_state(self, key, state):
        if key != self.key:
            return
        running = state == "running"
        self.b_start.setText(tr("Đang chạy…") if running else tr("Bắt đầu"))
        self.b_pause.setEnabled(running)

    def receive_images(self, paths: list[str]):
        """Nhận ảnh từ trang khác (Gửi sang Flow Video)."""
        self.refs = paths
        self.ref_mode.setCurrentIndex(1)
        if any(m.key == "i2v" for m in self.pdef.modes):
            self._set_mode("i2v")
            for b in getattr(self, "mode_group", QButtonGroup()).buttons():
                b.setChecked(b.text() == tr("Ảnh → Video"))
        self._fill_refs()
        self._save_state()
