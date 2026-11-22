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
    from PySide6.QtWidgets import QApplication

    from .core import log
    from .core.db import Database
    from .core.i18n import set_language, tr
    from .core.paths import APP_NAME, assets_dir

    L = log.setup()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(QIcon(str(assets_dir() / ("icon.ico" if os.name == "nt" else "logo.png"))))
    fonts = assets_dir() / "fonts"
    if fonts.exists():
        for f in fonts.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(f))

    db = Database()
    set_language(db.get_setting("language", "vi"))
    from .ui import palette
    palette.install(db.get_setting("theme", palette.DEFAULT))   # bộ màu: phải chọn trước khi tạo giao diện

    restarted = "--restarted" in sys.argv          # mở lại sau khi đổi ngôn ngữ / bộ màu: không màn hình chào
    if restarted:
        class _NoSplash:
            def showMessage(self, *_):
                pass

            def finish(self, *_):
                pass
        splash = _NoSplash()
    else:
        from .ui.splash import AnimatedSplash
        splash = AnimatedSplash()
        splash.show()
        splash.showMessage(tr("Đang tải giao diện"))

    from .ui.theme import qss
    app.setStyleSheet(qss())
    n = db.recover_running()
    if n:
        L.info("Khôi phục %d tác vụ đang chạy dở về hàng đợi", n)

    from .core.license import License
    lic = License()
    splash.showMessage(tr("Đang kiểm tra bản quyền"))
    st = lic.startup() if lic.enabled and not restarted else lic.local()   # không có key / hết hạn → gói Miễn phí, không chặn
    L.info("Bản quyền: %s", st.label())

    splash.showMessage(tr("Đang chuẩn bị bộ máy tạo ảnh/video"))
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
    splash.finish(win)
    rs = db.get_setting("restart_state", {}) if restarted else {}
    if rs.get("geom"):
        from PySide6.QtCore import QByteArray
        win.restoreGeometry(QByteArray.fromHex(rs["geom"].encode()))
    win.show()
    if rs:
        db.set_setting("restart_state", {})
        if rs.get("settings"):
            def _reopen():
                from PySide6.QtCore import QByteArray
                d = win.open_settings()
                if rs.get("settings_geom"):
                    d.restoreGeometry(QByteArray.fromHex(rs["settings_geom"].encode()))
                sp = win.pages.get("settings")
                if sp is not None and hasattr(sp, "set_tab"):
                    sp.set_tab(int(rs.get("settings_tab", 0)))
            QTimer.singleShot(50, _reopen)
    if n and not restarted:
        QTimer.singleShot(800, lambda: win.ctx.toast("info", f"Có {n} tác vụ chạy dở từ lần trước đã được đưa lại vào hàng đợi. Bấm Bắt đầu để chạy tiếp."))
    QTimer.singleShot(6000, lambda: win.check_update(manual=False))   # tự kiểm tra bản mới sau khi mở
    upd_timer = QTimer(win)                                             # và mỗi 3 giờ khi để máy chạy lâu
    upd_timer.timeout.connect(lambda: win.check_update(manual=False))
    upd_timer.start(3 * 3600 * 1000)
    L.info("Khởi động xong")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
