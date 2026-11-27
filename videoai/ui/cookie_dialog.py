"""Hộp thoại dán cookie cho một tài khoản (thay cho mở Chrome để đăng nhập).

Cookie đã dán được lưu (mã hóa) và hiện lại ở đây lần sau, kèm hạn của cookie phiên."""
from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPlainTextEdit, QVBoxLayout

from .widgets import button, label
from ..core.cookies import CookieError, describe_expiry, parse, session_expiry
from ..core.i18n import tr
from ..core.platforms import PLATFORM_LABELS

SITE_HINT = {
    "flow": "flow.google.com", "gvids": "vids.google.com", "gpics": "photos.google.com",
    "gpt": "chatgpt.com", "grok": "grok.com", "muse": "muse.ai",
}
EXPIRY_COLOR = {"ok": "#4ade80", "soon": "#fbbf24", "expired": "#fb7185", "unknown": "#7f8bc4"}


class CookieDialog(QDialog):
    """Người dùng dán cookie → bấm Nạp. Sau khi accept(): self.text (nguyên văn đã dán), self.cookies
    (định dạng Playwright), self.expires (hạn cookie phiên, giây epoch hoặc None), self.warnings."""

    def __init__(self, account: dict, parent=None, saved_text: str = "", expires: float | None = None):
        super().__init__(parent)
        self.account = account
        self.text = ""
        self.cookies: list[dict] = []
        self.expires: float | None = None
        self.warnings: list[str] = []
        plat = account["platform"]
        site = SITE_HINT.get(plat, plat)
        self.setWindowTitle(tr("Dán cookie") + f" · {account['label']} ({PLATFORM_LABELS.get(plat, plat)})")
        self.resize(720, 540)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 14)
        v.setSpacing(10)
        info = label(tr("Mở") + f" {site} " + tr(
            "trên Chrome thường (đã đăng nhập đúng tài khoản) → tiện ích Cookie-Editor → Export → JSON, rồi dán vào ô "
            "bên dưới. Cũng nhận chuỗi «Cookie:» chép từ DevTools › Network. Cookie được lưu mã hóa trên máy bạn và "
            "chỉ nạp vào hồ sơ trình duyệt riêng của tài khoản này, không gửi đi đâu khác."), "muted")
        info.setWordWrap(True)
        v.addWidget(info)
        self.exp_lbl = label("", "faint")
        v.addWidget(self.exp_lbl)
        self._show_expiry(expires, saved=bool(saved_text))
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText('[{"domain": ".google.com", "name": "__Secure-1PSID", "value": "…"}, …]')
        self.edit.setFont(QFont("Consolas", 9))
        self.edit.setPlainText(saved_text)
        self.edit.textChanged.connect(self._preview)
        v.addWidget(self.edit, 1)
        self.msg = label("", "faint")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        foot = QHBoxLayout()
        foot.addStretch()
        b_cancel = button("Hủy")
        b_cancel.clicked.connect(self.reject)
        b_ok = button("Nạp cookie & kiểm tra", "primary", "check")
        b_ok.clicked.connect(self._submit)
        foot.addWidget(b_cancel)
        foot.addWidget(b_ok)
        v.addLayout(foot)

    def _show_expiry(self, expires: float | None, saved: bool = True):
        if not saved and not expires:
            self.exp_lbl.setText(tr("Hiệu lực cookie") + ": " + tr("chưa có cookie"))
            self.exp_lbl.setStyleSheet(f"color:{EXPIRY_COLOR['unknown']};")
            return
        text, state = describe_expiry(expires)
        self.exp_lbl.setText(tr("Hiệu lực cookie") + ": " + text)
        self.exp_lbl.setStyleSheet(f"color:{EXPIRY_COLOR[state]};font-weight:600;")
        self.exp_lbl.setToolTip(tr("Hạn ghi trên cookie phiên đăng nhập. Nền tảng vẫn có thể thu hồi phiên sớm hơn "
                                   "(đăng xuất, đổi mật khẩu, hoạt động bất thường)."))

    def _preview(self):
        """Dán xong là thấy ngay hạn của cookie vừa dán (không báo lỗi khi đang gõ dở)."""
        try:
            cks, _ = parse(self.edit.toPlainText(), self.account["platform"])
        except CookieError:
            return
        self._show_expiry(session_expiry(cks, self.account["platform"]))

    def _submit(self):
        text = self.edit.toPlainText().strip()
        try:
            self.cookies, self.warnings = parse(text, self.account["platform"])
        except CookieError as e:
            self.msg.setText("⚠ " + tr(str(e)))
            self.msg.setStyleSheet("color:#fb7185;")
            return
        self.text = text
        self.expires = session_expiry(self.cookies, self.account["platform"])
        self.accept()
