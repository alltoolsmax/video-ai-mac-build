"""Cài Đặt: Tài khoản · Nền tảng · AI viết prompt · Chung · Thống kê."""
from __future__ import annotations

import re
import shutil

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLineEdit, QMessageBox, QSpinBox, QTableWidget, QTableWidgetItem,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from ..widgets import Card, PathPicker, button, combo, field, label
from ...core.i18n import LANGUAGES, tr
from ...core.paths import data_dir, default_output_dir, profiles_dir
from ...core.platforms import PAGES, PLATFORM_LABELS

SHORT_PLATFORM = {"flow": "Flow", "gpt": "ChatGPT", "grok": "Grok", "dreamina": "Dreamina", "muse": "Muse", "vibes": "Meta"}
from ...services import llm


class SwatchButton(QPushButton):
    """Nút mẫu bộ màu: tô bằng màu THẬT của bộ màu đó (không bị đổi theo bộ màu đang dùng)."""

    def __init__(self, text, bg, accent, fg):
        super().__init__(text)
        self.bg, self.accent, self.fg = bg, accent, fg
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(172)
        self.setFixedHeight(34)

    def paintEvent(self, _):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QFont, QPainter, QPainterPath, QPen
        from PySide6 import QtGui
        base = QtGui.QColor
        while base.__name__ == "ThemedColor":
            base = base.__mro__[1]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 5, 5)
        p.fillPath(path, base(self.bg))
        p.setPen(QPen(base(self.accent), 2.4 if self.isChecked() else 1.0))
        p.drawPath(path)
        dot = QRectF(r.left() + 10, r.center().y() - 6, 12, 12)
        p.setBrush(base(self.accent))
        p.setPen(Qt.NoPen)
        p.drawEllipse(dot)
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(base(self.fg))
        p.drawText(QRectF(dot.right() + 8, r.top(), r.width() - 30, r.height()), Qt.AlignVCenter | Qt.AlignLeft,
                   ("✓ " if self.isChecked() else "") + self.text())
        p.end()


class SettingsPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.db = ctx.db
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.addLayout(self._lang_theme_rows())
        tabs = QTabWidget()
        tabs.addTab(self._accounts_tab(), tr("Tài khoản"))
        tabs.addTab(self._llm_tab(), tr("AI viết prompt"))
        tabs.addTab(self._general_tab(), tr("Chung"))
        tabs.addTab(self._stats_tab(), tr("Thống kê"))
        v.addWidget(tabs, 1)
        ctx.engine.account_updated.connect(lambda _: self._reload_accounts())

    # ------------------------------------------------------------ ngôn ngữ & bộ màu (hàng trên cùng)
    def _lang_theme_rows(self):
        from ..palette import THEMES, current as cur_theme
        box = QVBoxLayout()
        box.setSpacing(8)
        r1 = QHBoxLayout()
        r1.setSpacing(6)
        cap = label("Ngôn ngữ", "fieldLabel")
        cap.setFixedWidth(84)
        r1.addWidget(cap)
        cur = self.db.get_setting("language", "vi")
        self.lang_btns = {}
        for code, name in LANGUAGES.items():
            b = QPushButton(name)
            b.setProperty("kind", "seg")
            b.setCheckable(True)
            b.setChecked(code == cur)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumWidth(96)
            b.clicked.connect(lambda _=False, c=code: self._pick_language(c))
            self.lang_btns[code] = b
            r1.addWidget(b)
        r1.addStretch()
        box.addLayout(r1)
        r2 = QHBoxLayout()
        r2.setSpacing(6)
        cap2 = label("Giao diện", "fieldLabel")
        cap2.setFixedWidth(84)
        r2.addWidget(cap2)
        self.theme_btns = {}
        now = self.db.get_setting("theme", cur_theme())
        for key, (name, kind, bg, accent) in THEMES.items():
            b = SwatchButton(tr(name), bg, accent, "#1f2937" if kind == "light" else "#f3f4f6")
            b.setChecked(key == now)
            b.clicked.connect(lambda _=False, k=key: self._pick_theme(k))
            self.theme_btns[key] = b
            r2.addWidget(b)
        r2.addStretch()
        box.addLayout(r2)
        return box

    def _ask_restart(self, what: str):
        if QMessageBox.question(self, tr("Khởi động lại"),
                                tr("Đã lưu") + f" {what}. " + tr("Khởi động lại phần mềm ngay để áp dụng?")) == QMessageBox.Yes:
            self.ctx.win.restart_app()

    def _pick_language(self, code: str):
        for c, b in self.lang_btns.items():
            b.setChecked(c == code)
        if code == self.db.get_setting("language", "vi"):
            return
        self.db.set_setting("language", code)
        self._ask_restart(tr("ngôn ngữ") + f" {LANGUAGES[code]}")

    def _pick_theme(self, key: str):
        from ..palette import THEMES
        for k, b in self.theme_btns.items():
            b.setChecked(k == key)
            b.update()
        if key == self.db.get_setting("theme", "dark_navy"):
            return
        self.db.set_setting("theme", key)
        self._ask_restart(tr("giao diện") + f" “{tr(THEMES[key][0])}”")

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
        b_add = button("Thêm tài khoản", "primary", "plus")
        b_add.clicked.connect(self._add_account)
        bar.addWidget(b_add)
        self.all_acc = QCheckBox(tr("Chọn tất cả"))
        self.all_acc.toggled.connect(self._check_all)
        bar.addSpacing(8)
        bar.addWidget(self.all_acc)
        self.acc_sel_lbl = label("", "muted")
        bar.addWidget(self.acc_sel_lbl)
        bar.addStretch()
        for text, ic, fn in (("Mở để đăng nhập", "login", self._login), ("Kiểm tra", "check", self._check),
                             ("Hiện / ẩn trình duyệt", "eye", self._toggle_visible), ("Đóng trình duyệt", "x", self._close_browser)):
            b = button(text, "chip", ic, "#67e8f9")
            b.clicked.connect(fn)
            bar.addWidget(b)
        v.addLayout(bar)
        bar2 = QHBoxLayout()
        for text, ic, fn, col in (("Bật dùng", "check2", lambda: self._set_enabled(1), "#4ade80"),
                                  ("Tắt dùng", "pause", lambda: self._set_enabled(0), "#fbbf24"),
                                  ("Đổi tên", "edit", self._rename, "#c4a5ff"),
                                  ("Xóa đã chọn", "trash", self._delete, "#fb7185")):
            b = button(text, "chip", ic, col)
            b.clicked.connect(fn)
            bar2.addWidget(b)
        tip = label("Tick ô đầu dòng để chọn nhiều tài khoản. Bấm đúp vào tên để đổi tên. "
                    "Chỉ tài khoản đang 'Bật' và đã đăng nhập mới được dùng để tạo.", "faint")
        bar2.addSpacing(10)
        bar2.addWidget(tip, 1)
        v.addLayout(bar2)
        self.acc_table = QTableWidget(0, 6)
        self.acc_table.setHorizontalHeaderLabels([tr(x) for x in ("", "#", "Tài khoản", "Trạng thái", "Dùng để tạo", "Kiểm tra lần cuối")])
        self.acc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.acc_table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.acc_table.verticalHeader().setVisible(False)
        self.acc_table.verticalHeader().setDefaultSectionSize(42)
        hh = self.acc_table.horizontalHeader()
        for i, wd in ((0, 36), (1, 84), (3, 230), (4, 120), (5, 150)):
            hh.resizeSection(i, wd)
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.acc_table.itemChanged.connect(self._acc_item_changed)
        v.addWidget(self.acc_table, 1)
        self._reload_accounts()
        return w

    def _reload_accounts(self):
        self.accs = self.db.accounts()
        t = self.acc_table
        keep = getattr(self, "_acc_checked", set())
        self._acc_checked = {a["id"] for a in self.accs if a["id"] in keep}
        t.blockSignals(True)
        t.setRowCount(len(self.accs))
        st = {"ok": "● Đã đăng nhập", "expired": "○ Chưa đăng nhập", "needs_user": "◐ Đang chờ bạn đăng nhập / xác minh", "unknown": "· Chưa kiểm tra"}
        for i, a in enumerate(self.accs):
            ck = QTableWidgetItem()
            ck.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            ck.setCheckState(Qt.Checked if a["id"] in self._acc_checked else Qt.Unchecked)
            t.setItem(i, 0, ck)
            no = QTableWidgetItem(SHORT_PLATFORM.get(a["platform"], a["platform"]))
            no.setToolTip(f"#{i + 1} · " + PLATFORM_LABELS.get(a["platform"], a["platform"]))
            no.setFlags(Qt.ItemIsEnabled)
            no.setTextAlignment(Qt.AlignCenter)
            t.setItem(i, 1, no)
            nm = QTableWidgetItem(a["label"])
            nm.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
            nm.setToolTip(tr("Bấm đúp để đổi tên"))
            t.setItem(i, 2, nm)
            s_ = QTableWidgetItem(tr(st.get(a["status"], a["status"])))
            s_.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            s_.setForeground(QColor("#4ade80") if a["status"] == "ok" else QColor("#fbbf24"))
            t.setItem(i, 3, s_)
            en = QTableWidgetItem(tr("Bật") if a["enabled"] else tr("Tắt"))
            en.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            en.setCheckState(Qt.Checked if a["enabled"] else Qt.Unchecked)
            en.setForeground(QColor("#4ade80") if a["enabled"] else QColor("#7f8bc4"))
            t.setItem(i, 4, en)
            lc = QTableWidgetItem((a["last_check_at"] or "")[:16].replace("T", " "))
            lc.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            t.setItem(i, 5, lc)
        t.blockSignals(False)
        self._acc_sel_update()

    def _acc_item_changed(self, it):
        r, c = it.row(), it.column()
        if not (0 <= r < len(self.accs)):
            return
        a = self.accs[r]
        if c == 0:
            if it.checkState() == Qt.Checked:
                self._acc_checked.add(a["id"])
            else:
                self._acc_checked.discard(a["id"])
            self._acc_sel_update()
        elif c == 4:
            self.db.update_account(a["id"], enabled=1 if it.checkState() == Qt.Checked else 0)
            self._reload_accounts()
        elif c == 2:
            name = it.text().strip()
            if name and name != a["label"]:
                self.db.update_account(a["id"], label=name)
                self._reload_accounts()

    def _acc_sel_update(self):
        n = len(self._acc_checked)
        self.acc_sel_lbl.setText(f"· {tr('đã chọn')} {n}/{len(self.accs)}" if n else f"· {len(self.accs)} {tr('tài khoản')}")
        self.all_acc.blockSignals(True)
        self.all_acc.setChecked(bool(self.accs) and n == len(self.accs))
        self.all_acc.blockSignals(False)

    def _check_all(self, on: bool):
        self._acc_checked = {a["id"] for a in self.accs} if on else set()
        self._reload_accounts()

    def _targets(self) -> list[dict]:
        """Các tài khoản đã tick; nếu chưa tick thì lấy dòng đang chọn."""
        ts = [a for a in self.accs if a["id"] in self._acc_checked]
        if not ts:
            one = self._selected()
            ts = [one] if one else []
        if not ts:
            self.ctx.toast("info", tr("Tick chọn tài khoản trước (ô vuông đầu dòng)."))
        return ts

    def _selected(self):
        r = self.acc_table.currentRow()
        return self.accs[r] if 0 <= r < len(self.accs) else None

    def _set_enabled(self, on: int):
        for a in self._targets():
            self.db.update_account(a["id"], enabled=on)
        self._reload_accounts()

    def _rename(self):
        ts = self._targets()
        if len(ts) != 1:
            if ts:
                self.ctx.toast("info", tr("Chọn đúng 1 tài khoản để đổi tên."))
            return
        name, ok = QInputDialog.getText(self, tr("Đổi tên tài khoản"), tr("Tên gợi nhớ:"), text=ts[0]["label"])
        if ok and name.strip():
            self.db.update_account(ts[0]["id"], label=name.strip())
            self._reload_accounts()

    def _url_for_platform(self, platform):
        urls = self.db.get_setting("platform_urls", {}) or {}
        for p in PAGES:
            if p.platform == platform:
                return urls.get(p.key) or p.url
        return ""

    def _add_account(self):
        plats = [p for p in dict.fromkeys(pg.platform for pg in PAGES if pg.ready)]
        names = [PLATFORM_LABELS.get(p, p) for p in plats]
        if len(plats) > 1:
            choice, ok = QInputDialog.getItem(self, tr("Thêm tài khoản"), tr("Tài khoản của nền tảng nào?"), names, 0, False)
            if not ok:
                return
            plat = plats[names.index(choice)]
        else:
            plat = plats[0] if plats else "flow"
        name, ok = QInputDialog.getText(self, tr("Thêm tài khoản") + f" · {PLATFORM_LABELS.get(plat, plat)}",
                                        tr("Tên gợi nhớ (vd: email):"))
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
        for a in self._targets()[:3]:
            self.ctx.engine.open_login(a, self._url_for_platform(a["platform"]))

    def _check(self):
        for a in self._targets():
            self.ctx.toast("info", tr("Đang kiểm tra") + f" {a['label']}…")
            self.ctx.engine.check_account(a, self._url_for_platform(a["platform"]))

    def _toggle_visible(self):
        for a in self._targets():
            if not self.ctx.engine.browser.is_open(a["id"]):
                self.ctx.toast("info", tr("Trình duyệt của") + f" {a['label']} " + tr("chưa mở. Nó sẽ tự mở (ẩn) khi bạn bắt đầu tạo."))
                continue
            hidden = self.ctx.engine.browser_hidden(a["id"])
            self.ctx.engine.set_browser_visible(a["id"], hidden)

    def _close_browser(self):
        for a in self._targets():
            self.ctx.engine.close_account_browser(a["id"])

    def _toggle(self):
        for a in self._targets():
            self.db.update_account(a["id"], enabled=0 if a["enabled"] else 1)
        self._reload_accounts()

    def _delete(self):
        ts = self._targets()
        if not ts:
            return
        names = ", ".join(a["label"] for a in ts[:5]) + (f" … (+{len(ts) - 5})" if len(ts) > 5 else "")
        if QMessageBox.question(self, tr("Xóa tài khoản"),
                                tr("Xóa") + f" {len(ts)} " + tr("tài khoản và hồ sơ trình duyệt (phiên đăng nhập)?") +
                                f"\n\n{names}") != QMessageBox.Yes:
            return
        for a in ts:
            self.ctx.engine.close_account_browser(a["id"])
            self.db.delete_account(a["id"])
            shutil.rmtree(a["profile_dir"], ignore_errors=True)
            self._acc_checked.discard(a["id"])
        self._reload_accounts()
        self.ctx.toast("ok", tr("Đã xóa") + f" {len(ts)} " + tr("tài khoản"))

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
        self.maxc = QSpinBox()
        self.maxc.setRange(1, 6)
        self.maxc.setValue(int(self.db.get_setting("max_concurrency", 3)))
        self.def_out = PathPicker(self.db.get_setting("default_output", str(default_output_dir())))
        self.hide_browser = QCheckBox(tr("Ẩn trình duyệt khi tạo ảnh/video (tự hiện lại khi cần bạn xác minh)"))
        self.hide_browser.setChecked(bool(self.db.get_setting("hide_browser", True)))
        self.show_wh = QCheckBox(tr("Hiện mục Webhook API trên menu (dành cho n8n / Make, khởi động lại để áp dụng)"))
        self.show_wh.setChecked(bool(self.db.get_setting("show_webhook", False)))
        self.auto_upd = QCheckBox(tr("Tự tải và cài bản cập nhật mới (khởi động lại ứng dụng)"))
        self.auto_upd.setChecked(bool(self.db.get_setting("auto_update", True)))
        self.notify = QCheckBox(tr("Phát âm báo khi chạy xong hàng đợi"))
        self.notify.setChecked(bool(self.db.get_setting("notify_sound", True)))

        g.addWidget(field("Thư mục lưu mặc định", self.def_out), 1, 0, 1, 2)
        g.addWidget(self.hide_browser, 2, 0, 1, 2)
        g.addWidget(self.notify, 3, 0, 1, 2)
        g.addWidget(self.show_wh, 4, 0, 1, 2)
        g.addWidget(self.auto_upd, 5, 0, 1, 2)
        v.addLayout(g)
        note = label("Số tác vụ chạy cùng lúc = số tài khoản đã đăng nhập (mỗi tài khoản một trình duyệt). "
                     "Thêm tài khoản ở tab Tài khoản để chạy nhanh hơn.", "muted")
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
        self.db.set_setting("max_concurrency", self.maxc.value())
        self.db.set_setting("default_output", self.def_out.text())
        self.db.set_setting("notify_sound", self.notify.isChecked())
        self.db.set_setting("hide_browser", self.hide_browser.isChecked())
        self.db.set_setting("show_webhook", self.show_wh.isChecked())
        self.db.set_setting("auto_update", self.auto_upd.isChecked())
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
