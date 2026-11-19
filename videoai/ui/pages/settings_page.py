"""Cài Đặt: Tài khoản · Nền tảng · AI viết prompt · Chung · Thống kê."""
from __future__ import annotations

import re
import shutil

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLineEdit, QMessageBox, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from ..widgets import Card, PathPicker, button, combo, field, label
from ...core.i18n import LANGUAGES, tr
from ...core.paths import data_dir, default_output_dir, profiles_dir
from ...core.platforms import PAGES, PLATFORM_LABELS
from ...services import llm


class SettingsPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.db = ctx.db
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.addWidget(label("Cài đặt", "h1"))
        tabs = QTabWidget()
        tabs.addTab(self._accounts_tab(), tr("Tài khoản"))
        tabs.addTab(self._platform_tab(), tr("Nền tảng"))
        tabs.addTab(self._llm_tab(), tr("AI viết prompt"))
        tabs.addTab(self._general_tab(), tr("Chung"))
        tabs.addTab(self._stats_tab(), tr("Thống kê"))
        v.addWidget(tabs, 1)
        ctx.engine.account_updated.connect(lambda _: self._reload_accounts())

    # ------------------------------------------------------------ tài khoản
    def _accounts_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        info = label("Mỗi tài khoản dùng một hồ sơ Chrome riêng. Bấm 'Mở để đăng nhập' → đăng nhập trong cửa sổ Chrome vừa mở → "
                     "ứng dụng tự nhận ra khi bạn đăng nhập xong và ẩn trình duyệt. Sau đó chỉ cần thao tác trên ứng dụng. "
                     "Mật khẩu không bao giờ được lưu trong ứng dụng.", "muted")
        info.setWordWrap(True)
        v.addWidget(info)
        bar = QHBoxLayout()
        self.plat = combo([PLATFORM_LABELS[k] for k in PLATFORM_LABELS])
        b_add = button("Thêm tài khoản", "primary", "plus")
        b_add.clicked.connect(self._add_account)
        bar.addWidget(self.plat)
        bar.addWidget(b_add)
        bar.addStretch()
        for text, ic, fn in (("Mở để đăng nhập", "login", self._login), ("Kiểm tra", "check", self._check),
                             ("Hiện / ẩn trình duyệt", "eye", self._toggle_visible),
                             ("Đóng trình duyệt", "x", self._close_browser), ("Bật / tắt", "retry", self._toggle),
                             ("Xóa", "trash", self._delete)):
            b = button(text, "chip", ic, "#67e8f9" if ic != "trash" else "#fb7185")
            b.clicked.connect(fn)
            bar.addWidget(b)
        v.addLayout(bar)
        self.acc_table = QTableWidget(0, 6)
        self.acc_table.setHorizontalHeaderLabels([tr(x) for x in ("Nền tảng", "Tài khoản", "Trạng thái", "Credit", "Kiểm tra lần cuối", "Bật")])
        self.acc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.acc_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.acc_table.verticalHeader().setVisible(False)
        self.acc_table.verticalHeader().setDefaultSectionSize(40)
        self.acc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        v.addWidget(self.acc_table, 1)
        self._reload_accounts()
        return w

    def _reload_accounts(self):
        self.accs = self.db.accounts()
        t = self.acc_table
        t.setRowCount(len(self.accs))
        st = {"ok": "● Đã đăng nhập", "expired": "○ Chưa đăng nhập", "needs_user": "◐ Đang chờ bạn đăng nhập / xác minh", "unknown": "· Chưa kiểm tra"}
        for i, a in enumerate(self.accs):
            vals = [PLATFORM_LABELS.get(a["platform"], a["platform"]), a["label"], tr(st.get(a["status"], a["status"])),
                    "" if a["credits_left"] is None else str(a["credits_left"]),
                    (a["last_check_at"] or "")[:16].replace("T", " "), "✓" if a["enabled"] else "—"]
            for j, x in enumerate(vals):
                it = QTableWidgetItem(x)
                if j == 2:
                    it.setForeground(Qt.green if a["status"] == "ok" else Qt.yellow)
                t.setItem(i, j, it)

    def _selected(self):
        r = self.acc_table.currentRow()
        return self.accs[r] if 0 <= r < len(self.accs) else None

    def _url_for_platform(self, platform):
        urls = self.db.get_setting("platform_urls", {}) or {}
        for p in PAGES:
            if p.platform == platform:
                return urls.get(p.key) or p.url
        return ""

    def _add_account(self):
        plat = list(PLATFORM_LABELS)[self.plat.currentIndex()]
        name, ok = QInputDialog.getText(self, tr("Thêm tài khoản"), tr("Tên gợi nhớ (vd: email):"))
        if not ok or not name.strip():
            return
        slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip())[:40] or "acc"
        prof = profiles_dir() / f"{plat}_{slug}"
        k = 1
        while prof.exists():
            prof = profiles_dir() / f"{plat}_{slug}_{k}"
            k += 1
        aid = self.db.add_account(plat, name.strip(), str(prof))
        self._reload_accounts()
        acc = self.db.one("SELECT * FROM accounts WHERE id=?", (aid,))
        self.ctx.engine.open_login(acc, self._url_for_platform(plat))

    def _login(self):
        a = self._selected()
        if a:
            self.ctx.engine.open_login(a, self._url_for_platform(a["platform"]))

    def _check(self):
        a = self._selected()
        if a:
            self.ctx.toast("info", tr("Đang kiểm tra") + f" {a['label']}…")
            self.ctx.engine.check_account(a, self._url_for_platform(a["platform"]))

    def _toggle_visible(self):
        a = self._selected()
        if not a:
            return
        if not self.ctx.engine.browser.is_open(a["id"]):
            self.ctx.toast("info", tr("Trình duyệt của tài khoản này chưa mở. Nó sẽ tự mở (ẩn) khi bạn bắt đầu tạo."))
            return
        hidden = self.ctx.engine.browser_hidden(a["id"])
        self.ctx.engine.set_browser_visible(a["id"], hidden)

    def _close_browser(self):
        a = self._selected()
        if a:
            self.ctx.engine.close_account_browser(a["id"])

    def _toggle(self):
        a = self._selected()
        if a:
            self.db.update_account(a["id"], enabled=0 if a["enabled"] else 1)
            self._reload_accounts()

    def _delete(self):
        a = self._selected()
        if not a:
            return
        if QMessageBox.question(self, tr("Xóa tài khoản"),
                                tr("Xóa tài khoản và hồ sơ trình duyệt (phiên đăng nhập) của") + f" {a['label']}?") != QMessageBox.Yes:
            return
        self.ctx.engine.close_account_browser(a["id"])
        self.db.delete_account(a["id"])
        shutil.rmtree(a["profile_dir"], ignore_errors=True)
        self._reload_accounts()

    # ------------------------------------------------------------ nền tảng
    def _platform_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        info = label("Địa chỉ trang của từng mục. Nếu một nền tảng đổi địa chỉ hoặc giao diện, sửa ở đây và trong "
                     "file selector (không cần cài lại ứng dụng).", "muted")
        info.setWordWrap(True)
        v.addWidget(info)
        urls = self.db.get_setting("platform_urls", {}) or {}
        form = QFormLayout()
        form.setVerticalSpacing(8)
        self.url_edits = {}
        for p in PAGES:
            e = QLineEdit(urls.get(p.key) or p.url)
            self.url_edits[p.key] = e
            form.addRow(tr(p.label), e)
        v.addLayout(form)
        row = QHBoxLayout()
        b_save = button("Lưu địa chỉ", "primary", "save")
        b_save.clicked.connect(self._save_urls)
        b_sel = button("Mở thư mục selector", "chip", "folder", "#67e8f9")
        from .gen_page import open_path
        from ...adapters.base import selectors_dir
        b_sel.clicked.connect(lambda: open_path(str(selectors_dir())))
        row.addWidget(b_save)
        row.addWidget(b_sel)
        row.addStretch()
        v.addLayout(row)
        v.addStretch()
        return w

    def _save_urls(self):
        self.db.set_setting("platform_urls", {k: e.text().strip() for k, e in self.url_edits.items()})
        self.ctx.toast("ok", tr("Đã lưu."))

    # ------------------------------------------------------------ LLM
    def _llm_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        info = label("Dùng để sửa / viết prompt. Cần API key của chính bạn (Google AI Studio hoặc OpenAI). "
                     "Key được lưu trong Windows Credential Manager.", "muted")
        info.setWordWrap(True)
        v.addWidget(info)
        g = QGridLayout()
        self.llm_provider = combo(["gemini", "openai"], self.db.get_setting("llm_provider", "gemini"))
        self.llm_model = QLineEdit(self.db.get_setting("llm_model", ""))
        self.llm_model.setPlaceholderText("gemini-2.5-flash / gpt-4o-mini")
        self.llm_key = QLineEdit(llm.get_key(self.db, self.llm_provider.currentText()))
        self.llm_key.setEchoMode(QLineEdit.Password)
        self.llm_provider.currentTextChanged.connect(lambda p: self.llm_key.setText(llm.get_key(self.db, p)))
        g.addWidget(field("Nhà cung cấp", self.llm_provider), 0, 0)
        g.addWidget(field("Model (bỏ trống = mặc định)", self.llm_model), 0, 1)
        g.addWidget(field("API key", self.llm_key), 1, 0, 1, 2)
        v.addLayout(g)
        b = button("Lưu", "primary", "save")
        b.clicked.connect(self._save_llm)
        b_test = button("Thử", "chip", "wand", "#f0abfc")
        b_test.clicked.connect(self._test_llm)
        row = QHBoxLayout()
        row.addWidget(b)
        row.addWidget(b_test)
        row.addStretch()
        v.addLayout(row)
        v.addStretch()
        return w

    def _save_llm(self):
        self.db.set_setting("llm_provider", self.llm_provider.currentText())
        self.db.set_setting("llm_model", self.llm_model.text().strip())
        llm.set_key(self.db, self.llm_provider.currentText(), self.llm_key.text().strip())
        self.ctx.toast("ok", tr("Đã lưu."))

    def _test_llm(self):
        self._save_llm()
        try:
            self.ctx.busy(True)
            out = llm.complete(self.db, "Trả lời ngắn.", "Chào bạn, hãy nói 'OK'.")
            self.ctx.toast("ok", "AI: " + out[:80])
        except Exception as e:
            self.ctx.toast("error", str(e)[:200])
        finally:
            self.ctx.busy(False)

    # ------------------------------------------------------------ chung
    def _general_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        g = QGridLayout()
        g.setHorizontalSpacing(14)
        self.lang = combo(list(LANGUAGES.values()), LANGUAGES.get(self.db.get_setting("language", "vi")))
        self.maxc = QSpinBox()
        self.maxc.setRange(1, 6)
        self.maxc.setValue(int(self.db.get_setting("max_concurrency", 3)))
        self.def_out = PathPicker(self.db.get_setting("default_output", str(default_output_dir())))
        self.hide_browser = QCheckBox(tr("Ẩn trình duyệt khi tạo ảnh/video (tự hiện lại khi cần bạn xác minh)"))
        self.hide_browser.setChecked(bool(self.db.get_setting("hide_browser", True)))
        self.notify = QCheckBox(tr("Phát âm báo khi chạy xong hàng đợi"))
        self.notify.setChecked(bool(self.db.get_setting("notify_sound", True)))
        g.addWidget(field("Ngôn ngữ (khởi động lại để áp dụng)", self.lang), 0, 0)
        g.addWidget(field("Giới hạn số hàng chạy đồng thời", self.maxc), 0, 1)
        g.addWidget(field("Thư mục lưu mặc định", self.def_out), 1, 0, 1, 2)
        g.addWidget(self.hide_browser, 2, 0, 1, 2)
        g.addWidget(self.notify, 3, 0, 1, 2)
        v.addLayout(g)
        note = label("Gợi ý: để 1–2 hàng đồng thời cho mỗi tài khoản. Chạy quá nhiều có thể khiến nền tảng giới hạn tài khoản của bạn.", "muted")
        note.setWordWrap(True)
        v.addWidget(note)
        row = QHBoxLayout()
        b = button("Lưu", "primary", "save")
        b.clicked.connect(self._save_general)
        b_data = button("Mở thư mục dữ liệu", "chip", "folder", "#67e8f9")
        from .gen_page import open_path
        b_data.clicked.connect(lambda: open_path(str(data_dir())))
        row.addWidget(b)
        row.addWidget(b_data)
        row.addStretch()
        v.addLayout(row)
        v.addStretch()
        return w

    def _save_general(self):
        code = list(LANGUAGES)[self.lang.currentIndex()]
        self.db.set_setting("language", code)
        self.db.set_setting("max_concurrency", self.maxc.value())
        self.db.set_setting("default_output", self.def_out.text())
        self.db.set_setting("notify_sound", self.notify.isChecked())
        self.db.set_setting("hide_browser", self.hide_browser.isChecked())
        self.ctx.toast("ok", tr("Đã lưu."))

    # ------------------------------------------------------------ thống kê
    def _stats_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        self.stats = QTableWidget(0, 4)
        self.stats.setHorizontalHeaderLabels([tr("Ngày"), tr("Nền tảng"), tr("Thành công"), tr("Lỗi")])
        self.stats.verticalHeader().setVisible(False)
        self.stats.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.stats.setEditTriggers(QAbstractItemView.NoEditTriggers)
        b = button("Làm mới", "chip", "retry", "#67e8f9")
        b.clicked.connect(self._reload_stats)
        v.addWidget(b, 0, Qt.AlignLeft)
        v.addWidget(self.stats, 1)
        self._reload_stats()
        return w

    def _reload_stats(self):
        rows = self.db.query("SELECT * FROM stats_daily ORDER BY day DESC, platform LIMIT 400")
        self.stats.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, x in enumerate((r["day"], PLATFORM_LABELS.get(r["platform"], r["platform"]), r["done"], r["failed"])):
                self.stats.setItem(i, j, QTableWidgetItem(str(x)))
