"""Giao diện cập nhật: tự kiểm tra khi mở ứng dụng, tự tải bản mới, cài và khởi động lại."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QMessageBox, QPlainTextEdit, QVBoxLayout

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
        self.b_later = button("Để sau")
        self.b_later.clicked.connect(self.reject)
        self.b_go = button("Cập nhật ngay", "primary", "download")
        self.b_go.clicked.connect(self.start)
        row.addWidget(self.b_later)
        row.addWidget(self.b_go)
        v.addLayout(row)
        if info.get("mandatory"):
            self.b_later.setEnabled(False)
        if auto:
            QTimer.singleShot(300, self.start)

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
            QMessageBox.information(self, tr("Cập nhật"),
                                    tr("Đã tải bộ cài tại:") + f"\n{self.setup}\n\n" + tr("Hãy đóng ứng dụng rồi chạy bộ cài này."))
            self.accept()
            return
        L.info("Cài bản %s và khởi động lại", self.info["version"])
        updater.install_and_restart(self.setup)
        self.accept()
        self.win.close()
        QApplication.quit()

    def _err(self, msg):
        L.warning("Cập nhật lỗi: %s", msg)
        self.state.setText(tr("Lỗi") + ": " + msg[:200])
        self.b_go.setEnabled(True)
        self.b_go.setText(tr("Thử lại"))


def check_update(win, manual: bool = False):
    db = win.ctx.db
    if not updater.manifest_url(db):
        if manual:
            QMessageBox.information(win, tr("Kiểm tra cập nhật"),
                                    tr("Bạn đang dùng phiên bản") + f" {APP_VERSION}.\n\n" +
                                    tr("Chưa cấu hình máy chủ cập nhật (videoai/update_config.json)."))
        return
    if manual:
        win.b_update.setText(tr("Đang kiểm tra…"))

    def done(info):
        win.b_update.setText(tr("Kiểm tra cập nhật") + f"  ·  v{APP_VERSION}")
        if info:
            win.b_update.setText(tr("Có bản mới") + f" {info['version']} ↻")
            UpdateDialog(win, info, auto=bool(db.get_setting("auto_update", True))).exec()
        elif manual:
            QMessageBox.information(win, tr("Kiểm tra cập nhật"), tr("Bạn đang dùng phiên bản mới nhất") + f" ({APP_VERSION}).")

    def err(msg):
        win.b_update.setText(tr("Kiểm tra cập nhật") + f"  ·  v{APP_VERSION}")
        L.warning("Không kiểm tra được cập nhật: %s", msg)
        if manual:
            QMessageBox.warning(win, tr("Kiểm tra cập nhật"), tr("Không kết nối được máy chủ cập nhật.") + f"\n{msg[:200]}")

    run_bg(lambda progress: updater.check(db), on_done=done, on_error=err)
