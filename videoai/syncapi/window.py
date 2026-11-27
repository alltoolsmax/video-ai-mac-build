"""Cửa sổ SYNC API: dán cookie → Lưu → Sao chép API Key (rồi ẩn xuống khay hệ thống)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QHBoxLayout, QLineEdit, QMenu, QPlainTextEdit,
                               QSystemTrayIcon, QVBoxLayout)

from . import APP_TITLE
from .store import PLATFORMS, SyncKeyError, SyncStore
from ..core.cookies import PLATFORM_HOSTS, CookieError, describe_expiry
from ..core.i18n import tr
from ..core.paths import assets_dir
from ..core.platforms import PLATFORM_LABELS
from ..ui.widgets import button, label

SITE = {"flow": "flow.google.com", "gpt": "chatgpt.com", "grok": "grok.com", "muse": "muse.ai",
        "gemini": "gemini.google.com"}
COLOR = {"ok": "#4ade80", "soon": "#fbbf24", "expired": "#fb7185", "unknown": "#7f8bc4", "error": "#fb7185"}


class SyncApiWindow(QDialog):
    """platform/key cho trước + lock=True: mở từ khung nhập API Key của một tài khoản (không cho đổi nền tảng / key).
    key_copied(key): người dùng bấm «Sao chép API Key» (cửa sổ tự đóng, biểu tượng nằm ở khay hệ thống).
    saved(key): cookie của key vừa được lưu."""
    key_copied = Signal(str)
    saved = Signal(str)

    def __init__(self, store: SyncStore, platform: str | None = None, key: str | None = None, lock: bool = False,
                 parent=None, base_url: str = "", account_labels=None):
        super().__init__(parent)
        self.store = store
        self.key = key or None
        self._saved_text = ""
        self._labels = account_labels or (lambda k: [])
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(QIcon(str(assets_dir() / "logo.png")))
        self.resize(640, 520)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 14)
        v.setSpacing(10)

        head = label(APP_TITLE, "pageTitle")
        f = head.font()
        f.setPointSize(f.pointSize() + 4)
        f.setBold(True)
        head.setFont(f)
        v.addWidget(head)
        info = label("Dán cookie của tài khoản vào ô bên dưới, bấm Lưu để nhận API key, rồi bấm «Sao chép API Key» "
                     "để dán vào Video AI. Cookie được lưu mã hóa trên máy bạn.", "muted")
        info.setWordWrap(True)
        v.addWidget(info)

        row = QHBoxLayout()
        self.plat_cb = QComboBox()
        for p in PLATFORMS:
            self.plat_cb.addItem(PLATFORM_LABELS.get(p, p) + f"  ({SITE[p]})", p)
        if platform in PLATFORMS:
            self.plat_cb.setCurrentIndex(PLATFORMS.index(platform))
        self.key_cb = QComboBox()
        row.addWidget(label("Nền tảng", "fieldLabel"))
        row.addWidget(self.plat_cb, 1)
        row.addSpacing(8)
        row.addWidget(label("API key", "fieldLabel"))
        row.addWidget(self.key_cb, 2)
        v.addLayout(row)
        if lock:                           # mở từ khung API Key của một tài khoản: cố định nền tảng, vẫn chọn lại được
            self.plat_cb.setEnabled(False)  # key đã lưu của nền tảng đó (vd. key của tài khoản vừa xóa)

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(tr("Dán cookie vào đây (JSON xuất từ tiện ích Cookie-Editor, hoặc chuỗi «Cookie: …»)"))
        self.edit.setFont(QFont("Consolas", 9))
        v.addWidget(self.edit, 1)

        self.msg = label("", "faint")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)

        self.key_edit = QLineEdit()
        self.key_edit.setReadOnly(True)
        self.key_edit.setPlaceholderText(tr("API key hiện ở đây sau khi bấm Lưu"))
        self.key_edit.setFont(QFont("Consolas", 9))
        v.addWidget(self.key_edit)

        foot = QHBoxLayout()
        self.b_get = button("Lấy Cookie", "chip", "link", "#67e8f9")
        self.b_get.setToolTip(tr("Mở trang của nền tảng bằng trình duyệt bạn đang dùng (cửa sổ thường, không ẩn danh)"))
        self.b_get.clicked.connect(self._open_site)
        self.b_save = button("Lưu", None, "save")
        self.b_save.clicked.connect(self._save)
        self.b_copy = button("Sao chép API Key", "primary", "check2")
        self.b_copy.clicked.connect(self._copy)
        foot.addWidget(self.b_get)
        foot.addStretch()
        foot.addWidget(self.b_save)
        foot.addWidget(self.b_copy)
        v.addLayout(foot)
        if base_url:
            api = label(tr("API cho ứng dụng khác") + f": {base_url}", "faint")
            api.setTextInteractionFlags(Qt.TextSelectableByMouse)
            v.addWidget(api)

        self._fill_keys()
        self.plat_cb.currentIndexChanged.connect(self._platform_changed)
        self.key_cb.currentIndexChanged.connect(self._key_changed)
        self._load_key()

    # ---------- trạng thái ----------
    @property
    def platform(self) -> str:
        return self.plat_cb.currentData()

    def _say(self, text: str, state: str = "unknown"):
        self.msg.setText(text)
        self.msg.setStyleSheet(f"color:{COLOR.get(state, COLOR['unknown'])};")

    def _fill_keys(self):
        self.key_cb.blockSignals(True)
        self.key_cb.clear()
        self.key_cb.addItem(tr("＋ Tạo API key mới"), None)
        for e in self.store.entries(self.platform):
            names = ", ".join(self._labels(e["key"])) or tr("chưa gắn tài khoản")
            self.key_cb.addItem(f"{names}  ·  …{e['key'][-6:]}", e["key"])
        i = self.key_cb.findData(self.key) if self.key else 0
        if i < 0:                      # key cho trước không thuộc nền tảng này / đã bị xóa
            self.key, i = None, 0
        self.key_cb.setCurrentIndex(i)
        self.key_cb.blockSignals(False)

    def _platform_changed(self):
        self.key = None
        self._fill_keys()
        self._load_key()

    def _key_changed(self):
        self.key = self.key_cb.currentData()
        self._load_key()

    def _load_key(self):
        """Hiện cookie + hạn của key đang chọn (key mới → ô trống)."""
        text = self.store.cookie_text(self.key) if self.key else ""
        self._saved_text = text
        self.edit.setPlainText(text)
        self.key_edit.setText(self.key or "")
        if self.key:
            e = self.store.get(self.key) or {}
            t, state = describe_expiry(e.get("expires"))
            self._say(tr("Hiệu lực cookie") + ": " + t, state)
        else:
            self._say(tr("Bấm «Lấy Cookie» để mở") + f" {SITE[self.platform]} " + tr(
                "bằng trình duyệt bạn đang dùng → đăng nhập đúng tài khoản → tiện ích Cookie-Editor → Export → JSON → dán vào ô trên."))

    # ---------- nút ----------
    def _open_site(self):
        QDesktopServices.openUrl(QUrl(PLATFORM_HOSTS[self.platform]))

    def _save(self) -> bool:
        text = self.edit.toPlainText().strip()
        try:
            key, expires, warns = self.store.save_cookie(self.platform, text, self.key)
        except (CookieError, SyncKeyError) as e:
            self._say("⚠ " + tr(str(e)), "error")
            return False
        self.key, self._saved_text = key, text
        self.key_edit.setText(key)
        self._fill_keys()
        t, state = describe_expiry(expires)
        note = (" · ⚠ " + " ".join(tr(w) for w in warns)) if warns else ""
        self._say(tr("Đã lưu. Hiệu lực cookie") + ": " + t + note, "soon" if warns and state == "ok" else state)
        self.saved.emit(key)
        return True

    def _copy(self):
        if not self.key or self.edit.toPlainText().strip() != self._saved_text:
            if not self._save():           # chưa lưu / vừa sửa cookie → lưu trước; cookie sai thì dừng ở đây
                return
        QGuiApplication.clipboard().setText(self.key)
        self.key_copied.emit(self.key)
        self.close()                       # biểu tượng SYNC API vẫn nằm ở khay hệ thống


class SyncApiTray(QObject):
    """Biểu tượng SYNC API ở khay hệ thống: bấm để mở lại cửa sổ."""
    open_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.icon: QSystemTrayIcon | None = None
        self._told = False

    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self, announce: bool = False):
        if not self.available():
            return
        if self.icon is None:
            self.icon = QSystemTrayIcon(QIcon(str(assets_dir() / "logo.png")), self)
            self.icon.setToolTip(APP_TITLE)
            menu = QMenu()
            act = QAction(tr("Mở SYNC API"), menu)
            act.triggered.connect(self.open_requested)
            menu.addAction(act)
            self._menu = menu
            self.icon.setContextMenu(menu)
            self.icon.activated.connect(self._activated)
        self.icon.show()
        if announce and not self._told:
            self._told = True
            self.icon.showMessage(APP_TITLE, tr("Đã sao chép API key. SYNC API nằm ở khay hệ thống – bấm vào biểu tượng để mở lại."),
                                  QSystemTrayIcon.Information, 4000)

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.open_requested.emit()

    def hide(self):
        if self.icon is not None:
            self.icon.hide()


def modal_parent(fallback=None):
    """Cửa sổ đang giữ tương tác (hộp thoại modal đang mở) – để cửa sổ SYNC API mở lên vẫn bấm được."""
    return QApplication.activeModalWidget() or fallback
