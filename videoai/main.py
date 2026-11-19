"""Điểm khởi động: Video AI - Mr. Huỳnh."""
from __future__ import annotations

import os
import sys


def _frozen_setup() -> None:
    """Bản exe: dùng Chromium đóng gói kèm (thư mục ms-playwright cạnh file exe) nếu có."""
    if getattr(sys, "frozen", False):
        from pathlib import Path
        base = Path(sys.executable).resolve().parent
        browsers = base / "ms-playwright"
        if browsers.exists():
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(browsers))
        bin_ffmpeg = base / "bin" / "ffmpeg"
        if bin_ffmpeg.exists():
            os.environ["PATH"] = str(bin_ffmpeg) + os.pathsep + os.environ.get("PATH", "")


def main() -> int:
    _frozen_setup()
    if os.name == "nt":
        try:  # biểu tượng riêng trên thanh tác vụ Windows
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MrHuynh.VideoAI")
        except Exception:
            pass
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QFontDatabase, QIcon, QPixmap
    from PySide6.QtWidgets import QApplication, QSplashScreen

    from .core import log
    from .core.db import Database
    from .core.i18n import set_language
    from .core.paths import APP_NAME, assets_dir

    L = log.setup()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(assets_dir() / "icon.ico")))
    fonts = assets_dir() / "fonts"
    if fonts.exists():
        for f in fonts.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(f))

    splash = QSplashScreen(QPixmap(str(assets_dir() / "logo.png")).scaled(280, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    splash.show()
    app.processEvents()

    from .ui.theme import qss
    app.setStyleSheet(qss())
    db = Database()
    set_language(db.get_setting("language", "vi"))
    n = db.recover_running()
    if n:
        L.info("Khôi phục %d tác vụ đang chạy dở về hàng đợi", n)

    from .core.license import License
    from .ui.license_ui import LicenseDialog
    lic = License()
    splash.showMessage("Đang kiểm tra bản quyền…", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
    app.processEvents()
    if lic.enabled:
        st = lic.startup()
        if not st.ok:
            splash.close()
            LicenseDialog(None, lic, blocking=True).exec()
            if not lic.status.ok:
                L.info("Chưa kích hoạt bản quyền, thoát")
                return 0
        L.info("Bản quyền: %s", lic.status.label())
    else:
        lic.local()

    from .core.engine import Engine
    from .services.refs import RefLibrary as Characters
    from .services.webhook import WebhookServer
    from .ui.main_window import MainWindow

    engine = Engine(db)
    webhook = WebhookServer(db, engine)
    if db.get_setting("webhook_enabled", False):
        try:
            webhook.start(int(db.get_setting("webhook_port", 8787)))
        except Exception as e:
            L.warning("Không bật được webhook: %s", e)
    win = MainWindow(db, engine, Characters(db), webhook, lic)
    win.show()
    splash.finish(win)
    if n:
        QTimer.singleShot(800, lambda: win.ctx.toast("info", f"Có {n} tác vụ chạy dở từ lần trước đã được đưa lại vào hàng đợi. Bấm Bắt đầu để chạy tiếp."))
    QTimer.singleShot(6000, lambda: win.check_update(manual=False))   # tự kiểm tra bản mới sau khi mở
    L.info("Khởi động xong")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
