"""Khung nhập API Key cho một tài khoản: [Lấy API Key] … [OK] [Cancel].

«Lấy API Key» mở SYNC API (dán cookie → Lưu → Sao chép API Key); khi người dùng bấm «Sao chép API Key», SYNC API
ẩn xuống khay hệ thống và khung này hiện lại với key đã điền sẵn."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QVBoxLayout

from .widgets import button, label
from ..core.i18n import tr
from ..core.platforms import PLATFORM_LABELS
from ..syncapi.store import looks_like_key


class ApiKeyDialog(QDialog):
    """Sau khi accept(): self.key là API key hợp lệ của đúng nền tảng (có trong kho SYNC API)."""

    def __init__(self, sync, platform: str, account_label: str, parent=None, key: str = ""):
        super().__init__(parent)
        self.sync, self.platform = sync, platform
        self.key = ""
        self.setWindowTitle(tr("API Key") + f" · {account_label} ({PLATFORM_LABELS.get(platform, platform)})")
        self.resize(620, 220)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 14)
        v.setSpacing(10)
        info = label("Dán API Key của tài khoản này. Chưa có: bấm «Lấy API Key» để mở SYNC API, dán cookie của tài khoản, "
                     "Lưu rồi bấm «Sao chép API Key».", "muted")
        info.setWordWrap(True)
        v.addWidget(info)
        self.edit = QLineEdit(key)
        self.edit.setPlaceholderText("sync-…")
        self.edit.setFont(QFont("Consolas", 10))
        self.edit.setClearButtonEnabled(True)
        self.edit.returnPressed.connect(self._ok)
        v.addWidget(self.edit)
        self.msg = label("", "faint")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        v.addStretch()
        foot = QHBoxLayout()
        self.b_get = button("Lấy API Key", "chip", "link", "#67e8f9")
        self.b_get.setAutoDefault(False)
        self.b_get.clicked.connect(self._get_key)
        self.b_ok = button("OK", "primary", "check")
        self.b_ok.clicked.connect(self._ok)
        self.b_cancel = button("Cancel")
        self.b_cancel.setAutoDefault(False)
        self.b_cancel.clicked.connect(self.reject)
        foot.addWidget(self.b_get)
        foot.addStretch()
        foot.addWidget(self.b_ok)
        foot.addWidget(self.b_cancel)
        v.addLayout(foot)
        self._sync_win = None

    def _warn(self, text: str):
        self.msg.setText("⚠ " + tr(text))
        self.msg.setStyleSheet("color:#fb7185;")

    def _get_key(self):
        cur = self.edit.text().strip()
        e = self.sync.store.get(cur) if cur else None
        key = cur if e and e["platform"] == self.platform else None     # đang có key đúng → mở để cập nhật cookie của nó
        w = self.sync.open_window(self.platform, key, lock=True, parent=self)
        w.key_copied.connect(self.sync_key_copied)
        self._sync_win = w

    def sync_key_copied(self, key: str):
        """SYNC API vừa sao chép key (và đã ẩn xuống khay hệ thống) → điền key, đưa khung này lên lại."""
        self.edit.setText(key)
        self.msg.setText(tr("Đã nhận API key từ SYNC API. Bấm OK để gắn cho tài khoản."))
        self.msg.setStyleSheet("color:#4ade80;")
        self.show()
        self.raise_()
        self.activateWindow()
        self.b_ok.setFocus()

    def _ok(self):
        key = self.edit.text().strip()
        if not key:
            return self._warn("Chưa dán API Key.")
        if not looks_like_key(key):
            return self._warn("API Key không đúng dạng (sync-… gồm 48 ký tự 0-9, a-f).")
        e = self.sync.store.get(key)
        if not e:
            return self._warn("API Key này không có trong SYNC API trên máy này. Bấm «Lấy API Key» để tạo.")
        if e["platform"] != self.platform:
            return self._warn(f"API Key này của nền tảng {PLATFORM_LABELS.get(e['platform'], e['platform'])}, "
                              f"không phải {PLATFORM_LABELS.get(self.platform, self.platform)}.")
        self.key = key
        self.accept()
