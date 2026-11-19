"""Cửa sổ chính: menu bên trái (nút trực quan liền mạch) + các trang."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

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


DISABLED_TOOLS = {"workflow", "upscale", "video_tools"}     # tạm khóa, sẽ mở ở bản sau
TOOL_NAMES = [(k, n) for k, n, _, _ in TOOL_ITEMS]

SOCIAL = [
    ("Zalo", "https://zalo.me/0979006367",
     '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect width="48" height="48" rx="12" fill="#0068FF"/>'
     '<text x="24" y="30" font-family="Arial,Helvetica,sans-serif" font-size="14" font-weight="700" fill="#fff" text-anchor="middle">Zalo</text></svg>'),
    ("YouTube", "https://www.youtube.com/channel/UCwSbzgfgu1iMfOR__AB4QGQ?sub_confirmation=1",
     '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect width="48" height="48" rx="12" fill="#FF0000"/>'
     '<path d="M19 15l14 9-14 9z" fill="#fff"/></svg>'),
    ("Facebook", "https://facebook.com/mr.huynhxuyenson",
     '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><rect width="48" height="48" rx="12" fill="#1877F2"/>'
     '<path d="M26.5 40V26.5h4.6l.7-5.3h-5.3v-3.4c0-1.5.4-2.6 2.7-2.6h2.8V10.4c-.5-.1-2.2-.2-4.1-.2-4.1 0-6.8 2.5-6.8 7v3.9h-4.6v5.3h4.6V40z" fill="#fff"/></svg>'),
]


class SocialBar(QWidget):
    def __init__(self):
        super().__init__()
        from PySide6.QtCore import QByteArray, QRectF, QUrl
        from PySide6.QtGui import QDesktopServices, QIcon, QPainter, QPixmap
        from PySide6.QtSvg import QSvgRenderer
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        h.addStretch()
        for name, url, svg in SOCIAL:
            pm = QPixmap(72, 72)
            pm.fill(Qt.transparent)
            qp = QPainter(pm)
            QSvgRenderer(QByteArray(svg.encode())).render(qp, QRectF(0, 0, 72, 72))
            qp.end()
            b = QPushButton()
            b.setIcon(QIcon(pm))
            b.setIconSize(pm.size() / 2)
            b.setFixedSize(42, 42)
            b.setToolTip(name)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet("QPushButton{background:transparent;border:none;}QPushButton:hover{background:#1b2563;border-radius:10px;}")
            b.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            h.addWidget(b)
        h.addStretch()


class ComingSoon(QWidget):
    def __init__(self, pdef):
        super().__init__()
        v = QVBoxLayout(self)
        v.addStretch()
        t = QLabel(tr(getattr(pdef, "label", pdef)))
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
        side.setFixedWidth(232)
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
        sv.addSpacing(6)
        sv.addWidget(SocialBar())
        self.b_update = QPushButton(tr("Kiểm tra cập nhật") + f"  ·  v{APP_VERSION}")
        self.b_update.setCursor(Qt.PointingHandCursor)
        self.b_update.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {C['border']};border-radius:9px;"
                                    f"padding:6px;color:{C['text-muted']};font-weight:500;font-size:12px;}}"
                                    f"QPushButton:hover{{border-color:{C['accent']};color:{C['text']};}}")
        self.b_update.clicked.connect(lambda: self.check_update(manual=True))
        sv.addWidget(self.b_update)
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
        if (start in PAGE_BY_KEY and not PAGE_BY_KEY[start].ready) or start in DISABLED_TOOLS:
            start = "flow_image"
        self.go(start if start in self.menu else "flow_image")

    def _menu_btn(self, key, text, ic, tile):
        b = MenuButton(text, ic, tile)
        if (key in PAGE_BY_KEY and not PAGE_BY_KEY[key].ready) or key in DISABLED_TOOLS:
            b.soon = True
        b.clicked.connect(lambda _=False, k=key: self.go(k))
        self.group.addButton(b)
        self.menu[key] = b
        return b

    def _make_page(self, key):
        if key in DISABLED_TOOLS:
            return ComingSoon(dict(TOOL_NAMES)[key])
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

    # ------------------------------------------------------------ cập nhật online
    def check_update(self, manual: bool = False):
        from .updater_ui import check_update
        check_update(self, manual)

    def _status(self):
        accs = self.db.accounts()
        ok = [a for a in accs if a["status"] == "ok"]
        if accs:
            self.status_acc.setText(f"●  {len(ok)} " + tr("tài khoản sẵn sàng") +
                                    (f" · {tr('tạo song song tối đa')} {len(ok)} {tr('tác vụ')}" if ok else ""))
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
