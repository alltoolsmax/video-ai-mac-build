"""Cài Đặt: Tài khoản · AI Agent · Thống kê."""
from __future__ import annotations

import re
import shutil

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMessageBox, QSpinBox, QTableWidget, QTableWidgetItem,
                               QPushButton, QTabWidget, QVBoxLayout, QWidget)

from ..widgets import Card, PathPicker, button, combo, field, icon, label
from ...core.i18n import LANGUAGES, tr
from ...core.paths import data_dir, default_output_dir, profiles_dir
from ...core.platforms import PAGES, PLATFORM_LABELS

SHORT_PLATFORM = {"flow": "Google", "gpt": "Chat GPT", "grok": "Grok", "dreamina": "Dreamina", "muse": "Muse",
                  "gemini": "Gemini"}
from ...services import llm

API_LEARN_URL = "https://mrhuynh.net/api-key-la-gi-tim-hieu-api-key"


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
        tabs = self.tabs = QTabWidget()
        tabs.addTab(self._accounts_tab(), tr("Tài khoản"))
        tabs.addTab(self._llm_tab(), tr("AI Agent"))
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

    def _engine_busy(self) -> bool:
        eng = self.ctx.engine
        return any(eng.is_running(k) for k in list(getattr(eng, "runs", {})))

    def _ask_restart(self, what: str):
        """Áp dụng ngay khi bấm, không hỏi: mở lại liền mạch (giữ cửa sổ, trang, Cài đặt).
        Đang có tác vụ chạy thì không cắt ngang (tránh mất tín dụng): tự áp dụng ngay khi chạy xong."""
        if not self._engine_busy():
            self.ctx.win.restart_app()
            return
        self.ctx.toast("info", tr("Đã chọn") + f" {what}. " + tr("Sẽ tự áp dụng ngay khi các tác vụ đang chạy xong."))
        if getattr(self, "_apply_timer", None) is None:
            from PySide6.QtCore import QTimer
            self._apply_timer = QTimer(self)
            self._apply_timer.timeout.connect(self._apply_when_idle)
            self._apply_timer.start(3000)

    def _apply_when_idle(self):
        if not self._engine_busy():
            self._apply_timer.stop()
            self.ctx.win.restart_app()

    def current_tab(self) -> int:
        return self.tabs.currentIndex() if hasattr(self, "tabs") else 0

    def set_tab(self, i: int):
        if hasattr(self, "tabs") and 0 <= i < self.tabs.count():
            self.tabs.setCurrentIndex(i)

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
        info = label("Mỗi tài khoản dùng một API Key và một hồ sơ trình duyệt riêng (chạy ẩn). Bấm 'Thêm tài khoản' hoặc "
                     "'API Key' → 'Lấy API Key' để mở SYNC API: dán cookie của tài khoản (JSON từ tiện ích Cookie-Editor hoặc "
                     "chuỗi Cookie), Lưu rồi 'Sao chép API Key'. Ứng dụng nạp cookie của key vào hồ sơ và tự kiểm tra trạng "
                     "thái. Cookie hết hạn thì mở lại SYNC API để dán cookie mới. Mật khẩu không bao giờ được lưu trong ứng dụng.",
                     "muted")
        info.setWordWrap(True)
        v.addWidget(info)
        self.headless_cb = QCheckBox(tr("Chạy ngầm hoàn toàn (tạo ảnh/video không mở cửa sổ trình duyệt nào)"))
        self.headless_cb.setChecked(bool(self.db.get_setting("run_headless", True)))
        self.headless_cb.setToolTip(tr("Khi nền tảng bắt xác minh robot, cửa sổ Chrome của tài khoản đó tự mở để bạn xác minh; "
                                       "tài khoản đó từ đó chạy bằng Chrome thường (cửa sổ ẩn ngoài màn hình) để giữ "
                                       "được xác minh. Tắt rồi bật lại tùy chọn này để cho mọi tài khoản chạy ngầm lại."))
        self.headless_cb.toggled.connect(self._set_headless)
        hrow = QHBoxLayout()
        hrow.addWidget(self.headless_cb)
        hrow.addStretch()
        # nút "Xem hướng dẫn": mở video YouTube hướng dẫn tab Tài khoản. Link nhập ở trang quản trị › Video hướng dẫn
        # (mã "settings_accounts"); chưa có link thì ẩn nút – giống nút "Xem Video hướng dẫn" của các trang tạo.
        self.b_acc_guide = QPushButton("  " + tr("Xem hướng dẫn"))
        self.b_acc_guide.setIcon(icon("play", "#ffffff", 14))
        self.b_acc_guide.setCursor(Qt.PointingHandCursor)
        self.b_acc_guide.setFixedHeight(30)
        self.b_acc_guide.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff1f3d,stop:1 #c4001a);"
                                       "color:white;border:1px solid rgba(255,255,255,.25);border-radius:5px;padding:0 12px;"
                                       "font-weight:700;font-size:12px;}QPushButton:hover{border:1px solid rgba(255,255,255,.85);}")
        self.b_acc_guide.clicked.connect(self._open_acc_guide)
        hrow.addWidget(self.b_acc_guide)
        v.addLayout(hrow)
        self.refresh_guide()
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
        for text, ic, fn in (("API Key", "login", self._login), ("Mở trình duyệt", "eye", self._open_browser),
                             ("Kiểm tra", "check", self._check), ("Đóng trình duyệt", "x", self._close_browser)):
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
        tip = label("Bấm vào hàng để chọn / bỏ chọn (chọn được nhiều tài khoản). Bấm đúp vào tên để đổi tên. "
                    "Chỉ tài khoản đang 'Bật' và đã đăng nhập mới được dùng để tạo.", "faint")
        bar2.addSpacing(10)
        bar2.addWidget(tip, 1)
        v.addLayout(bar2)
        self.acc_table = QTableWidget(0, 7)
        self.acc_table.setHorizontalHeaderLabels([tr(x) for x in ("", "#", "Tài khoản", "Trạng thái", "Dùng để tạo",
                                                                  "Kiểm tra lần cuối", "Hiệu lực cookie")])
        self.acc_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.acc_table.setEditTriggers(QAbstractItemView.DoubleClicked)
        self.acc_table.verticalHeader().setVisible(False)
        self.acc_table.verticalHeader().setDefaultSectionSize(42)
        hh = self.acc_table.horizontalHeader()
        for i, wd in ((0, 36), (1, 84), (3, 230), (4, 120), (5, 150), (6, 250)):
            hh.resizeSection(i, wd)
            hh.setSectionResizeMode(i, QHeaderView.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.acc_table.itemChanged.connect(self._acc_item_changed)
        self.acc_table.cellClicked.connect(self._acc_row_clicked)
        self.acc_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.acc_table.customContextMenuRequested.connect(self._acc_menu)
        self.acc_table.setToolTip("")
        v.addWidget(self.acc_table, 1)
        self._reload_accounts()
        return w

    def _reload_accounts(self):
        self._reload_ai_accounts()
        self.accs = self.db.accounts()
        t = self.acc_table
        keep = getattr(self, "_acc_checked", set())
        self._acc_checked = {a["id"] for a in self.accs if a["id"] in keep}
        t.blockSignals(True)
        t.setRowCount(len(self.accs))
        import time as _time
        cool = self.db.get_setting("flag_cooldown", {}) or {}
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
            until = cool.get(a["id"], 0)
            if until > _time.time():                  # Google báo "hoạt động bất thường": đang nghỉ
                s_.setText("◔ " + tr("Tạm nghỉ đến") + " " + _time.strftime("%H:%M", _time.localtime(until)))
                s_.setForeground(QColor("#fb923c"))
                s_.setToolTip(tr("Nền tảng báo hoạt động bất thường – tools tự cho tài khoản nghỉ 2 giờ, không dùng để tạo."))
            t.setItem(i, 3, s_)
            en = QTableWidgetItem(tr("Bật") if a["enabled"] else tr("Tắt"))
            en.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            en.setCheckState(Qt.Checked if a["enabled"] else Qt.Unchecked)
            en.setForeground(QColor("#4ade80") if a["enabled"] else QColor("#7f8bc4"))
            t.setItem(i, 4, en)
            lc = QTableWidgetItem((a["last_check_at"] or "")[:16].replace("T", " "))
            lc.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            t.setItem(i, 5, lc)
            from ...core.cookies import describe_expiry
            if a.get("cookie_enc") or a.get("cookie_expires"):
                text, state = describe_expiry(a.get("cookie_expires"))
            else:
                text, state = "Chưa dán cookie", "unknown"
            ex = QTableWidgetItem(tr(text) if state == "unknown" else text)
            ex.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            ex.setForeground(QColor({"ok": "#4ade80", "soon": "#fbbf24", "expired": "#fb7185"}.get(state, "#7f8bc4")))
            ex.setToolTip(tr("Hạn ghi trên cookie phiên đăng nhập (cập nhật mỗi lần Kiểm tra). Nền tảng vẫn có thể "
                             "thu hồi phiên sớm hơn – khi đó dán cookie mới."))
            t.setItem(i, 6, ex)
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

    def _acc_row_clicked(self, r: int, c: int):
        """Bấm vào hàng nào thì hàng đó được tick chọn, bấm lần nữa thì bỏ chọn
        (ô tick đầu dòng và ô Bật/Tắt giữ cách bấm riêng của chúng)."""
        if c in (0, 4) or not (0 <= r < len(self.accs)):
            return
        it = self.acc_table.item(r, 0)
        if it is not None:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)   # → _acc_item_changed

    def _acc_menu(self, pos):
        """Chuột phải vào hàng: menu thao tác. Hàng chưa được chọn → chọn riêng hàng đó (như Explorer);
        hàng đang nằm trong nhóm đã chọn → thao tác cho cả nhóm."""
        from PySide6.QtWidgets import QMenu
        from ..widgets import icon
        r = self.acc_table.rowAt(pos.y())
        if not (0 <= r < len(self.accs)):
            return
        a = self.accs[r]
        if a["id"] not in self._acc_checked:
            self._acc_checked = {a["id"]}
            self._reload_accounts()
        self.acc_table.setCurrentCell(r, 2)
        n = len(self._acc_checked)
        m = QMenu(self)
        title = m.addAction(a["label"] if n == 1 else f"{n} {tr('tài khoản đã chọn')}")
        title.setEnabled(False)
        m.addSeparator()
        items = [("API Key", "login", self._login, "#67e8f9"),
                 ("Mở trình duyệt", "eye", self._open_browser, "#67e8f9"),
                 ("Kiểm tra", "check", self._check, "#67e8f9"),
                 None,
                 ("Bật dùng", "check2", lambda: self._set_enabled(1), "#4ade80"),
                 ("Tắt dùng", "pause", lambda: self._set_enabled(0), "#fbbf24"),
                 ("Đổi tên", "edit", self._rename, "#c4a5ff"),
                 ("Đóng trình duyệt", "x", self._close_browser, "#67e8f9"),
                 None,
                 ("Xóa", "trash", self._delete, "#fb7185")]
        for it in items:
            if it is None:
                m.addSeparator()
                continue
            text, ic, fn, col = it
            act = m.addAction(icon(ic, col, 16), tr(text))
            act.triggered.connect(lambda _=False, f=fn: f())
            if text in ("Đổi tên", "API Key") and n != 1:
                act.setEnabled(False)          # API key là của riêng từng tài khoản: nhập cho 1 tài khoản mỗi lần
        self._last_menu = m
        m.popup(self.acc_table.viewport().mapToGlobal(pos))

    def _acc_paint_rows(self):
        t = self.acc_table
        for r, a in enumerate(self.accs):
            bg = QColor(124, 92, 255, 55) if a["id"] in self._acc_checked else QColor(0, 0, 0, 0)
            for c in range(t.columnCount()):
                it = t.item(r, c)
                if it is not None:
                    it.setBackground(bg)

    def _acc_sel_update(self):
        t = self.acc_table
        t.blockSignals(True)
        self._acc_paint_rows()
        t.blockSignals(False)
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
        from ...core.platforms import platform_url
        return platform_url(self.db, platform)

    def _add_account(self):
        from ...core.platforms import AGENT_ONLY_PLATFORMS
        plats = [p for p in dict.fromkeys(pg.platform for pg in PAGES if pg.ready)] + list(AGENT_ONLY_PLATFORMS)
        # Ghi rõ từng loại dùng để làm gì: "Google" là tài khoản tạo ảnh / video Flow (cookie ở flow.google.com), KHÁC với
        # "Gemini" (cookie ở gemini.google.com, chỉ cho AI Agent) – từng có người tạo tài khoản tên "Gemini" ở mục Google
        # rồi AI Agent báo chưa có tài khoản.
        names = [PLATFORM_LABELS.get(p, p) + (tr(" – chỉ dùng cho AI Agent (cookie ở gemini.google.com)") if p in AGENT_ONLY_PLATFORMS
                                              else tr(" Flow – tạo ảnh / video (cookie ở flow.google.com)") if p == "flow" else "")
                 for p in plats]
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
        # nhập tên xong → bắt buộc dán API Key của tài khoản (khung có nút Lấy API Key / OK / Cancel);
        # Cancel thì không tạo tài khoản
        key = self._ask_api_key(plat, name.strip())
        if not key:
            return
        slug = re.sub(r"[^A-Za-z0-9]+", "_", name.strip())[:40] or "acc"
        prof = profiles_dir() / f"{plat}_{slug}"
        k = 1
        while prof.exists():
            prof = profiles_dir() / f"{plat}_{slug}_{k}"
            k += 1
        aid = self.db.add_account(plat, name.strip(), str(prof))
        acc = self.db.one("SELECT * FROM accounts WHERE id=?", (aid,))
        self._apply_api_key(acc, key)

    def _login(self):
        """Nút 'API Key' (thay cho 'Dán cookie'): nhập / đổi API Key cho đúng 1 tài khoản."""
        ts = self._targets()
        if len(ts) > 1:
            self.ctx.toast("info", tr("Chọn đúng 1 tài khoản để nhập API Key."))
            return
        if ts:
            from ...syncapi import service as sync_service
            cur = sync_service.get(self.ctx).store.key_of(ts[0]["id"])
            key = self._ask_api_key(ts[0]["platform"], ts[0]["label"], cur)
            if key:
                self._apply_api_key(ts[0], key)

    def _ask_api_key(self, platform: str, account_label: str, current: str = "") -> str:
        """Hiện khung nhập API Key. Trả về key hợp lệ, hoặc '' nếu người dùng bấm Cancel."""
        from ...syncapi import service as sync_service
        from ..api_key_dialog import ApiKeyDialog
        dlg = ApiKeyDialog(sync_service.get(self.ctx), platform, account_label, self, current)
        return dlg.key if dlg.exec() == ApiKeyDialog.Accepted else ""

    def _apply_api_key(self, acc: dict, key: str):
        """Gắn API key cho tài khoản: SYNC API nạp cookie của key vào hồ sơ trình duyệt của tài khoản rồi tự kiểm tra."""
        from ...syncapi import service as sync_service
        from ...syncapi.store import SyncKeyError
        try:
            warns = sync_service.get(self.ctx).apply_key(acc, key)
        except SyncKeyError as e:
            self._reload_accounts()
            self.ctx.toast("error", f"{acc['label']}: {tr(str(e))}")
            return
        for w in warns:
            self.ctx.toast("warn", f"{acc['label']}: {tr(w)}")
        self._reload_accounts()

    def _set_headless(self, on: bool):
        self.db.set_setting("run_headless", bool(on))
        if on:
            # bật lại = cho mọi tài khoản thử chạy ngầm lại (kể cả tài khoản từng bị bắt xác minh khi chạy ngầm)
            self.db.set_setting("headed_accounts", [])
        self.ctx.toast("info", tr("Đã bật chạy ngầm hoàn toàn" if on else "Đã tắt chạy ngầm hoàn toàn") + " – " +
                       tr("áp dụng từ lần trình duyệt của tài khoản mở kế tiếp (đóng trình duyệt để áp dụng ngay)."))

    def _paste_cookie(self, acc: dict):
        from ..cookie_dialog import CookieDialog
        row = self.db.one("SELECT cookie_expires FROM accounts WHERE id=?", (acc["id"],)) or {}
        dlg = CookieDialog(acc, self, saved_text=self.db.account_cookie(acc["id"]), expires=row.get("cookie_expires"))
        if dlg.exec() != CookieDialog.Accepted:
            return
        for w in dlg.warnings:
            self.ctx.toast("warn", f"{acc['label']}: {tr(w)}")
        self.db.set_account_cookie(acc["id"], dlg.text, dlg.expires)
        self.db.update_account(acc["id"], status="unknown")
        self._reload_accounts()
        self.ctx.engine.paste_cookies(acc, dlg.cookies, self._url_for_platform(acc["platform"]))

    # ---------- nút "Xem hướng dẫn" của tab Tài khoản
    def _acc_guide_url(self) -> str:
        from ..main_window import GUIDE_ACCOUNTS
        win = getattr(self.ctx, "win", None)
        return win._guide_url(GUIDE_ACCOUNTS) if win is not None and hasattr(win, "_guide_url") else ""

    def refresh_guide(self):
        """Hiện nút khi trang quản trị đã có link (cửa sổ chính gọi lại sau khi tải xong danh sách link)."""
        if hasattr(self, "b_acc_guide"):
            url = self._acc_guide_url()
            self.b_acc_guide.setVisible(bool(url))
            self.b_acc_guide.setToolTip(url)

    def _open_acc_guide(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        url = self._acc_guide_url()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _open_browser(self):
        """Nút "Mở trình duyệt": mở cửa sổ Chrome thường của tài khoản (hồ sơ riêng của nó) để người dùng xem / thao tác
        tay – đăng nhập lại, xác minh, xem trang. Đóng cửa sổ thì ứng dụng tự kiểm tra lại trạng thái tài khoản."""
        ts = self._targets()
        if not ts:
            return self.ctx.toast("info", tr("Chọn tài khoản cần mở trình duyệt."))
        if len(ts) > 3:
            self.ctx.toast("info", tr("Chỉ mở trình duyệt cho 3 tài khoản đầu đã chọn."))
        for a in ts[:3]:
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
            from ...syncapi import service as sync_service
            sync_service.get(self.ctx).store.unlink(a["id"])       # API key vẫn nằm trong SYNC API, chỉ bỏ liên kết
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
        v.setSpacing(10)
        t = QLabel(tr("API Key (Không bắt buộc) Nếu có API thì tác vụ sẽ nhanh hơn"))
        t.setObjectName("h2")
        learn = button("Tìm hiểu API Key", "chip", "link")
        learn.setToolTip(API_LEARN_URL)
        learn.clicked.connect(lambda: __import__("webbrowser").open(API_LEARN_URL))
        hr = QHBoxLayout()
        hr.addWidget(t)
        hr.addWidget(learn)
        hr.addStretch()
        v.addLayout(hr)
        g = QGridLayout()
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(6)
        self.api_rows = {}
        from ...services import api_llm
        cfg = api_llm.config(self.db)
        for r, prov in enumerate(api_llm.PROVIDERS):
            on = QCheckBox(api_llm.LABEL[prov])
            on.setChecked(bool(cfg[prov]["on"]))
            key = QLineEdit(cfg[prov]["key"])
            key.setEchoMode(QLineEdit.Password)
            key.setPlaceholderText(tr("Dán API key Gemini (AIza…)") if prov == "gemini" else tr("Dán API key OpenAI (sk-…)"))
            mdl = QComboBox()
            mdl.setEditable(True)
            mdl.setMinimumWidth(180)
            mdl.addItem(cfg[prov]["model"])
            chk = button("Kiểm tra", "chip", "check")
            get = button("Lấy API", "chip", "link")
            get.setToolTip(api_llm.KEY_PAGE[prov])
            get.clicked.connect(lambda _=False, u=api_llm.KEY_PAGE[prov]: __import__("webbrowser").open(u))
            g.addWidget(on, r, 0)
            g.addWidget(key, r, 1)
            g.addWidget(get, r, 2)
            g.addWidget(mdl, r, 3)
            g.addWidget(chk, r, 4)
            self.api_rows[prov] = (on, key, mdl, chk)
            sv = lambda *_a, p=prov: self._save_api(p)
            on.toggled.connect(sv)
            key.editingFinished.connect(sv)
            mdl.currentTextChanged.connect(sv)
            chk.clicked.connect(lambda _=False, p=prov: self._check_api(p))
        g.setColumnStretch(1, 1)
        v.addLayout(g)
        ah = label("Bấm \"Lấy API\" để mở trang tạo key. Gemini: tạo key miễn phí – chưa bật thanh toán vẫn dùng được model "
                   "Flash trong giới hạn miễn phí (ít lượt / phút, / ngày). Chat GPT API: phải nạp tiền trước ở "
                   "trang OpenAI. Có key thì AI Agent dùng API trước; API lỗi / hết lượt thì tự chuyển sang tài "
                   "khoản Chat GPT bên dưới.", "faint")
        ah.setWordWrap(True)
        v.addWidget(ah)
        t = QLabel(tr("AI Agent tự chọn tài khoản"))
        t.setObjectName("h2")
        v.addWidget(t)
        self.ai_list = QTableWidget(0, 3)
        self.ai_list.setHorizontalHeaderLabels([tr("Thứ tự"), tr("Tài khoản"), tr("Trạng thái")])
        self.ai_list.verticalHeader().setVisible(False)
        self.ai_list.setEditTriggers(QTableWidget.NoEditTriggers)
        self.ai_list.setSelectionMode(QTableWidget.NoSelection)
        self.ai_list.setFocusPolicy(Qt.NoFocus)
        hh = self.ai_list.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.ai_list.setMinimumHeight(170)
        v.addWidget(self.ai_list, 1)
        hint = label("Không cần chọn: khi không có API key chính thức, AI Agent dùng luân phiên các tài khoản Chat GPT, "
                     "rồi tới các tài khoản Gemini. Tài khoản Gemini là loại tài khoản riêng chỉ dùng cho AI Agent (thêm ở "
                     "tab Tài khoản, cookie lấy ở gemini.google.com) – tài khoản Google của Flow không dùng cho AI Agent. "
                     "Tài khoản nào lỗi (không gửi được, hết lượt, không trả kết quả) thì tự chuyển sang tài khoản khác.",
                     "faint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self._reload_ai_accounts()
        self.b_ai_test = button("Thử AI Agent", "chip", "wand", "#f0abfc")
        self.b_ai_test.clicked.connect(self._test_llm)
        row = QHBoxLayout()
        row.addWidget(self.b_ai_test)
        row.addStretch()
        v.addLayout(row)
        return w

    def _reload_ai_accounts(self):
        from PySide6.QtGui import QColor
        from ...adapters.chat import LABEL
        if not hasattr(self, "ai_list"):
            return
        accs = llm.agent_accounts(self.db)
        self.ai_list.setRowCount(0)
        if not accs:
            self.ai_list.setRowCount(1)
            from ...services import api_llm
            it = QTableWidgetItem(tr("Đang dùng API key chính thức – không cần tài khoản.") if api_llm.active(self.db)
                                  else tr("Chưa có tài khoản Chat GPT / Gemini nào – thêm ở tab Tài khoản (loại «Gemini», không "
                                          "phải «Google Flow»)."))
            self.ai_list.setItem(0, 1, it)
            return
        for a in accs:
            r = self.ai_list.rowCount()
            self.ai_list.insertRow(r)
            self.ai_list.setItem(r, 0, QTableWidgetItem(str(r + 1)))
            site = "Chat GPT" if a["platform"] == "gpt" else LABEL.get(a["platform"], a["platform"])
            self.ai_list.setItem(r, 1, QTableWidgetItem(f"{site} · {a['label']}"))
            if llm.busy(a["id"]):
                st, col = tr("đang dùng"), "#4ade80"
            elif a["status"] == "ok":
                st, col = tr("sẵn sàng"), "#4ade80"
            else:
                st, col = tr("chưa kiểm tra"), "#fbbf24"
            it = QTableWidgetItem("● " + st)
            it.setForeground(QColor(col))
            self.ai_list.setItem(r, 2, it)

    def _save_api(self, prov: str):
        from ...services import api_llm
        on, key, mdl, _chk = self.api_rows[prov]
        api_llm.save(self.db, prov, key.text(), mdl.currentText(), on.isChecked())
        api_llm.mark_ok(prov)

    def _check_api(self, prov: str):
        from ..workers import run_bg
        from ...services import api_llm
        self._save_api(prov)
        on, key, mdl, chk = self.api_rows[prov]
        if not key.text().strip():
            self.ctx.toast("error", tr("Chưa nhập API key."))
            return
        chk.setEnabled(False)
        k = key.text()

        def job(progress):
            ms = api_llm.models(prov, k)
            out = api_llm.ask(self.db, prov, "Trả lời thật ngắn.", "Hãy trả lời đúng một chữ: OK", timeout_s=60)
            return ms, out

        def done(res):
            chk.setEnabled(True)
            ms, out = res
            cur = mdl.currentText()
            mdl.blockSignals(True)
            mdl.clear()
            mdl.addItems(ms or [cur])
            mdl.setCurrentText(cur)
            mdl.blockSignals(False)
            self.ctx.toast("ok", f"{api_llm.LABEL[prov]} {tr('dùng được')}: {out[:40]}")

        run_bg(job, on_done=done, on_error=lambda m: (chk.setEnabled(True), self.ctx.toast("error", m[:300])))

    def _test_llm(self):
        from ..workers import run_bg
        self.b_ai_test.setEnabled(False)
        self.b_ai_test.setText(tr("Đang thử…"))
        eng = self.ctx.engine
        llm.begin()

        def job(progress):
            return llm.complete(self.db, "Trả lời thật ngắn.", "Chào bạn, hãy trả lời đúng một chữ: OK", eng,
                                lambda m: progress(0, m))

        def end():
            self.b_ai_test.setEnabled(True)
            self.b_ai_test.setText(tr("Thử AI Agent"))
        run_bg(job, on_done=lambda out: (end(), self.ctx.toast("ok", "AI Agent: " + (out or "")[:80])),
               on_error=lambda m: (end(), self.ctx.toast("error", m[:240])),
               on_progress=lambda _p, m: m and self.ctx.toast("info", m))

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
