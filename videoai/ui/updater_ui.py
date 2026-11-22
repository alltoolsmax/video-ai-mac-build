"""Giao diện cập nhật: tự kiểm tra khi mở ứng dụng, tự tải bản mới, cài và khởi động lại."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QMessageBox, QPlainTextEdit, QVBoxLayout

from .theme import C
from .widgets import GradientBar, button, label
from .workers import run_bg
from ..core import log, updater
from ..core.i18n import tr
from ..core.paths import APP_VERSION

L = log.get("update")


class UpdateDialog(QDialog):
    def __init__(self, win, info: dict, auto: bool):
        super().__init__(win)
        self.win = win
        self.info = info
        self.setup = None
        self.setWindowTitle(tr("Có bản cập nhật mới"))
        self.setFixedSize(520, 380)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.addWidget(label(tr("Có phiên bản mới") + f" {info['version']}", "h1"))
        v.addWidget(label(tr("Bạn đang dùng") + f" {APP_VERSION}", "muted"))
        notes = QPlainTextEdit(info.get("notes") or tr("(Không có ghi chú)"))
        notes.setReadOnly(True)
        v.addWidget(notes, 1)
        self.bar = GradientBar()
        self.state = label("", "faint")
        v.addWidget(self.bar)
        v.addWidget(self.state)
        row = QHBoxLayout()
        row.addStretch()
        self.mandatory = updater.is_mandatory(info)
        self.b_later = button("Thoát phần mềm" if self.mandatory else "Để sau")
        self.b_later.clicked.connect(self._quit if self.mandatory else self.reject)
        self.b_go = button("Cập nhật ngay", "primary", "download")
        self.b_go.clicked.connect(self.start)
        row.addWidget(self.b_later)
        row.addWidget(self.b_go)
        v.addLayout(row)
        if self.mandatory:
            warn = label("Đây là bản cập nhật bắt buộc. Vui lòng cập nhật để tiếp tục sử dụng.")
            warn.setStyleSheet(f"color:{C['warning']};font-weight:600;")
            warn.setWordWrap(True)
            v.insertWidget(2, warn)
            self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        if auto or self.mandatory:
            QTimer.singleShot(300, self.start)

    def reject(self):
        if self.mandatory:          # bản bắt buộc: không đóng hộp thoại bằng Esc / dấu X
            return
        super().reject()

    def _quit(self):
        self.done(0)
        self.win.close()
        QApplication.quit()

    def start(self):
        if self.setup is not None:
            return self.install()
        self.b_go.setEnabled(False)
        self.state.setText(tr("Đang tải bản mới…"))
        run_bg(lambda progress: updater.download(self.info, progress), on_done=self._downloaded, on_error=self._err,
               on_progress=lambda p, m: (self.bar.set(p / 100), self.state.setText(f"{tr('Đang tải')} {p}% · {m}")))

    def _downloaded(self, path):
        self.setup = path
        self.bar.set(1)
        busy = any(getattr(self.win.ctx.engine, "is_running")(k) for k in ("flow_image", "flow_video"))
        if busy:
            self.state.setText(tr("Đã tải xong. Đang có tác vụ chạy – bấm 'Cài đặt & khởi động lại' khi xong việc."))
            self.b_go.setText(tr("Cài đặt & khởi động lại"))
            self.b_go.setEnabled(True)
            return
        self.state.setText(tr("Đã tải xong. Ứng dụng sẽ tự cài bản mới và mở lại sau 5 giây…"))
        self.b_go.setText(tr("Cài đặt ngay"))
        self.b_go.setEnabled(True)
        QTimer.singleShot(5000, self.install)

    def install(self):
        if not self.setup or not self.isVisible():
            return
        if not updater.can_self_install():
            import sys
            how = (tr("Hãy đóng ứng dụng, mở tệp .dmg này rồi kéo ứng dụng vào thư mục Applications (chọn Thay thế).")
                   if sys.platform == "darwin" else tr("Hãy đóng ứng dụng rồi chạy bộ cài này."))
            QMessageBox.information(self, tr("Cập nhật"), tr("Đã tải bộ cài tại:") + f"\n{self.setup}\n\n" + how)
            try:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.setup.parent)))
            except Exception:
                pass
            self.accept()
            return
        L.info("Cài bản %s và khởi động lại", self.info["version"])
        db = self.win.ctx.db
        prev = db.get_setting("update_attempt", {}) or {}
        n = int(prev.get("n", 0)) + 1 if prev.get("version") == self.info["version"] else 1
        db.set_setting("update_attempt", {"version": self.info["version"], "from": APP_VERSION, "n": n})
        updater.install_and_restart(self.setup)
        self.accept()
        self.win.close()
        QApplication.quit()

    def _err(self, msg):
        L.warning("Cập nhật lỗi: %s", msg)
        self.state.setText(tr("Lỗi") + ": " + msg[:200])
        self.b_go.setEnabled(True)
        self.b_go.setText(tr("Thử lại"))


def _btn_idle(win):
    win.b_update.setText(tr("Kiểm tra cập nhật") + f"  ·  v{APP_VERSION}")


def check_update(win, manual: bool = False):
    db = win.ctx.db
    if getattr(win, "_upd_open", False):          # đang mở hộp thoại cập nhật → không hỏi lại
        return
    pending = getattr(win, "_upd_info", None)
    if manual and pending:                         # đã biết có bản mới → mở luôn
        return _show(win, pending, auto=False)
    if not updater.manifest_url(db):
        if manual:
            QMessageBox.information(win, tr("Kiểm tra cập nhật"),
                                    tr("Bạn đang dùng phiên bản") + f" {APP_VERSION}.\n\n" +
                                    tr("Chưa cấu hình máy chủ cập nhật."))
        return
    if manual:
        win.b_update.setText(tr("Đang kiểm tra…"))

    def done(info):
        if not info:
            win._upd_info = None
            _btn_idle(win)
            if manual:
                QMessageBox.information(win, tr("Kiểm tra cập nhật"), tr("Bạn đang dùng phiên bản mới nhất") + f" ({APP_VERSION}).")
            return
        L.info("Có bản mới %s (đang dùng %s)", info["version"], APP_VERSION)
        att = db.get_setting("update_attempt", {}) or {}
        if att.get("version") == info["version"] and att.get("from") == APP_VERSION and int(att.get("n", 0)) >= 1:
            # đã cài bản này rồi mà phần mềm vẫn là bản cũ → KHÔNG tự cài lại (tránh vòng lặp cài – khởi động lại)
            L.warning("Đã cài bản %s nhưng phần mềm vẫn là %s: bộ cài trên máy chủ không đúng phiên bản hoặc cài không thành công",
                      info["version"], APP_VERSION)
            win._upd_info = info
            win.b_update.setText("⚠  " + tr("Cập nhật") + f" {info['version']} " + tr("không thành công"))
            if manual:
                QMessageBox.warning(win, tr("Cập nhật"),
                                    tr("Đã cài bản") + f" {info['version']} " + tr("nhưng phần mềm vẫn là bản") + f" {APP_VERSION}.\n\n" +
                                    tr("File cài đặt trên máy chủ có thể không đúng phiên bản. Hãy liên hệ người bán để được hỗ trợ."))
            return
        known = (getattr(win, "_upd_info", None) or {}).get("version") == info["version"]
        win._upd_info = info
        win.b_update.setText("⬆  " + tr("Có bản mới") + f" {info['version']} – " + tr("bấm để cập nhật"))
        win.b_update.setProperty("hot", True)
        win.b_update.setStyleSheet(win.b_update.styleSheet() + "QPushButton{border-color:#ff8a1f;color:#ffb066;font-weight:700;}")
        # tự kiểm tra định kỳ: chỉ hiện hộp thoại lần đầu thấy bản này (trừ bản bắt buộc)
        if manual or not known or updater.is_mandatory(info):
            _show(win, info, auto=not manual)          # mục Chung đã bỏ: luôn tự cập nhật

    def err(msg):
        _btn_idle(win)
        L.warning("Không kiểm tra được cập nhật: %s", msg)
        if manual:
            QMessageBox.warning(win, tr("Kiểm tra cập nhật"), tr("Không kết nối được máy chủ cập nhật.") + f"\n{msg[:200]}")

    run_bg(lambda progress: updater.check(db), on_done=done, on_error=err)


def _show(win, info, auto):
    win._upd_open = True
    try:
        UpdateDialog(win, info, auto=auto).exec()
    finally:
        win._upd_open = False
