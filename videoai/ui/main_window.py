"""Cửa sổ chính: menu bên trái (nút trực quan liền mạch) + các trang."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QStackedWidget,
                               QVBoxLayout, QWidget)

from .theme import C
from .widgets import MenuButton, Toast
from ..core.i18n import tr
from ..core.paths import APP_NAME, APP_VERSION, assets_dir
from ..core.platforms import FOOTER_ITEMS, PAGE_BY_KEY, PAGES, PLATFORM_LABELS, TOOL_ITEMS


class Ctx:
    """Đối tượng chia sẻ cho các trang."""

    def __init__(self, win, db, engine, characters, webhook):
        self.win, self.db, self.engine, self.characters, self.webhook = win, db, engine, characters, webhook

    def toast(self, kind, text):
        Toast.show_msg(self.win, kind, text)

    def go(self, key):
        self.win.go(key)

    def set_badge(self, key, n):
        b = self.win.menu.get(key)
        if b:
            b.set_badge(n)

    def busy(self, on: bool):
        if on:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        else:
            QApplication.restoreOverrideCursor()

    def send_to_video(self, paths):
        self.win.go("flow_video")
        self.win.pages["flow_video"].receive_start_frame(paths)
        self.toast("ok", tr("Đã đặt ảnh làm ảnh đầu trong Tạo Video Flow (đã thêm vào kho ảnh tham chiếu)."))

    def send_to_editor(self, paths):
        self.win.go("video_tools")
        self.win.pages["video_tools"].import_media(paths, add_to_timeline=True)


class ComingSoon(QWidget):
    def __init__(self, pdef):
        super().__init__()
        v = QVBoxLayout(self)
        v.addStretch()
        t = QLabel(tr(pdef.label))
        t.setObjectName("h1")
        t.setAlignment(Qt.AlignCenter)
        m = QLabel(tr("Chức năng này đang được phát triển.\nHiện tại hãy dùng Tạo ảnh Flow và Tạo Video Flow."))
        m.setObjectName("muted")
        m.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        v.addWidget(m)
        v.addStretch()


class MainWindow(QMainWindow):
    def __init__(self, db, engine, characters, webhook):
        super().__init__()
        self.ctx = Ctx(self, db, engine, characters, webhook)
        self.db = db
        self.setWindowTitle(f"{APP_NAME}  v{APP_VERSION}")
        self.setWindowIcon(QIcon(str(assets_dir() / "logo.png")))
        self.setMinimumSize(1280, 760)
        self.resize(1440, 900)

        root = QWidget()
        root.setObjectName("root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QHBoxLayout()
        body.setSpacing(0)
        outer.addLayout(body, 1)

        # ---------------- sidebar
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(246)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(10, 12, 10, 12)
        sv.setSpacing(5)
        brand = QHBoxLayout()
        logo = QLabel()
        pm = QPixmap(str(assets_dir() / "logo.png"))
        logo.setPixmap(pm.scaled(46, 46, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        logo.setFixedSize(46, 46)
        brand.addWidget(logo)
        bt = QVBoxLayout()
        bt.setSpacing(0)
        n1 = QLabel("Video AI")
        n1.setStyleSheet("font-size:17px;font-weight:800;color:#e0fbff;")
        n2 = QLabel("Mr. Huỳnh")
        n2.setStyleSheet("font-size:12px;color:#c084fc;font-weight:600;")
        bt.addWidget(n1)
        bt.addWidget(n2)
        brand.addLayout(bt)
        brand.addStretch()
        sv.addLayout(brand)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{C['border']};")
        sv.addSpacing(6)
        sv.addWidget(sep)
        sv.addSpacing(6)

        self.menu: dict[str, MenuButton] = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        show_wh = bool(db.get_setting("show_webhook", False))
        items = [(p.key, p.label, p.icon, p.tile) for p in PAGES] + [t for t in TOOL_ITEMS if t[0] != "webhook" or show_wh]
        for key, text, ic, tile in items:
            sv.addWidget(self._menu_btn(key, text, ic, tile))
        sv.addStretch()
        for key, text, ic, tile in FOOTER_ITEMS:
            sv.addWidget(self._menu_btn(key, text, ic, tile))
        body.addWidget(side)

        # ---------------- trang
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.pages: dict[str, QWidget] = {}

        # ---------------- thanh trạng thái
        sb = QWidget()
        sb.setObjectName("statusbar")
        sb.setFixedHeight(28)
        sl = QHBoxLayout(sb)
        sl.setContentsMargins(14, 0, 14, 0)
        self.status_acc = QLabel()
        self.status_acc.setObjectName("faint")
        self.status_right = QLabel()
        self.status_right.setObjectName("faint")
        sl.addWidget(self.status_acc)
        sl.addStretch()
        sl.addWidget(self.status_right)
        outer.addWidget(sb)
        self.setCentralWidget(root)

        engine.toast.connect(self.ctx.toast)
        engine.account_updated.connect(lambda _: self._status())
        self._status()
        start = db.get_setting("last_page", "flow_image")
        if start in PAGE_BY_KEY and not PAGE_BY_KEY[start].ready:
            start = "flow_image"
        self.go(start if start in self.menu else "flow_image")

    def _menu_btn(self, key, text, ic, tile):
        b = MenuButton(text, ic, tile)
        if key in PAGE_BY_KEY and not PAGE_BY_KEY[key].ready:
            b.soon = True
        b.clicked.connect(lambda _=False, k=key: self.go(k))
        self.group.addButton(b)
        self.menu[key] = b
        return b

    def _make_page(self, key):
        if key in PAGE_BY_KEY:
            pdef = PAGE_BY_KEY[key]
            if pdef.platform == "flow":
                from .pages.flow_page import FlowPage
                return FlowPage(self.ctx, pdef)
            return ComingSoon(pdef)
        if key == "settings":
            from .pages.settings_page import SettingsPage
            return SettingsPage(self.ctx)
        if key == "logs":
            from .pages.logs_page import LogsPage
            return LogsPage(self.ctx)
        if key in ("refs", "characters"):
            from .refs_ui import RefsPage
            return RefsPage(self.ctx)
        if key == "workflow":
            from .pages.workflow_page import WorkflowPage
            return WorkflowPage(self.ctx)
        if key == "webhook":
            from .pages.webhook_page import WebhookPage
            return WebhookPage(self.ctx)
        if key == "upscale":
            from .pages.upscale_page import UpscalePage
            return UpscalePage(self.ctx)
        if key == "video_tools":
            from .pages.video_tools_page import VideoToolsPage
            return VideoToolsPage(self.ctx)
        return QLabel(key)

    def go(self, key):
        if key not in self.pages:
            w = self._make_page(key)
            self.pages[key] = w
            self.stack.addWidget(w)
        self.stack.setCurrentWidget(self.pages[key])
        self.menu[key].setChecked(True)
        self.db.set_setting("last_page", key)

    def _status(self):
        accs = self.db.accounts()
        ok = [a for a in accs if a["status"] == "ok"]
        if accs:
            names = ", ".join(f"{PLATFORM_LABELS.get(a['platform'], a['platform'])}: {a['label']}" for a in ok[:3])
            self.status_acc.setText(f"●  {len(ok)}/{len(accs)} " + tr("tài khoản đã đăng nhập") + (f"  ·  {names}" if names else ""))
        else:
            self.status_acc.setText("○  " + tr("Chưa có tài khoản – vào Cài Đặt để thêm"))
        from ..core.i18n import LANGUAGES, current
        self.status_right.setText(f"{LANGUAGES[current()]}  ·  v{APP_VERSION}")

    def closeEvent(self, e):
        for p in self.pages.values():
            if hasattr(p, "_save_state"):
                try:
                    p._save_state()
                except Exception:
                    pass
        try:
            self.ctx.webhook.stop()
        except Exception:
            pass
        self.ctx.engine.shutdown()
        super().closeEvent(e)
