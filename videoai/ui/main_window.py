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

SOCIAL = [   # tên, đường dẫn, màu đầu, màu cuối, biểu tượng trắng (SVG 24x24)
    ("Zalo", "https://zalo.me/0979006367", "#2b8cff", "#0050d8",
     '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M12 2.5C6.2 2.5 1.5 6.4 1.5 11.2c0 2.7 1.5 5.1 3.8 6.7'
     '-.2 1.4-.9 2.7-1.9 3.6 2-.1 3.7-.8 5-1.8 1.1.3 2.3.5 3.6.5 5.8 0 10.5-3.9 10.5-8.7S17.8 2.5 12 2.5z" fill="#fff"/>'
     '<path d="M7.6 8.4h6.1v1.3l-4 4.6h4.1v1.4H7.4v-1.3l4-4.6H7.6z" fill="#0068ff"/>'
     '<path d="M15.4 8.4h1.5v7.3h-1.5z" fill="#0068ff"/></svg>'),
    ("YouTube", "https://www.youtube.com/channel/UCwSbzgfgu1iMfOR__AB4QGQ?sub_confirmation=1", "#ff3b3b", "#c4001a",
     '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><rect x="1.5" y="5" width="21" height="14.5" rx="4.2" fill="#fff"/>'
     '<path d="M10 9v6.5l5.6-3.25z" fill="#e60012"/></svg>'),
    ("Facebook", "https://facebook.com/mr.huynhxuyenson", "#3b8bff", "#1258c9",
     '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M13.6 22v-8.4h2.9l.45-3.4H13.6V8.1c0-1 .3-1.7 1.7-1.7h1.8'
     'V3.4c-.3 0-1.4-.14-2.6-.14-2.6 0-4.3 1.6-4.3 4.4v2.5H7.3v3.4h2.9V22z" fill="#fff"/></svg>'),
]


class SocialButton(QPushButton):
    """Nút chữ nhật bo góc: nền chuyển màu thương hiệu, viền sáng, biểu tượng + tên.
    Rê chuột: sáng lên, nổi viền và hắt bóng phát sáng; bấm: lún nhẹ."""

    def __init__(self, name, url, c1, c2, svg):
        super().__init__()
        from PySide6.QtCore import QByteArray, QPropertyAnimation, QUrl
        from PySide6.QtGui import QColor, QDesktopServices
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        self.name, self.c1, self.c2 = name, QColor(c1), QColor(c2)
        self.svg = QSvgRenderer(QByteArray(svg.encode()))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{name} · Mr. Huỳnh")
        self.setFixedHeight(54)
        self.setMinimumWidth(60)
        self._hover = False
        self.glow = QGraphicsDropShadowEffect(self)
        self.glow.setOffset(0, 3)
        self.glow.setColor(QColor(c1).darker(110))
        self.glow.setBlurRadius(6)
        self.setGraphicsEffect(self.glow)
        self.anim = QPropertyAnimation(self.glow, b"blurRadius", self)
        self.anim.setDuration(180)
        self.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))

    def enterEvent(self, e):
        self._hover = True
        self.anim.stop(); self.anim.setEndValue(22); self.anim.start()
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.anim.stop(); self.anim.setEndValue(6); self.anim.start()
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        down = self.isDown()
        r = QRectF(self.rect()).adjusted(1.5, 1.5 + (1 if down else 0), -1.5, -1.5 + (1 if down else 0))
        path = QPainterPath()
        path.addRoundedRect(r, 11, 11)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        c1 = self.c1.lighter(118) if self._hover else self.c1
        c2 = self.c2.lighter(112) if self._hover else self.c2
        g.setColorAt(0, c1)
        g.setColorAt(1, c2)
        p.fillPath(path, g)
        # vệt sáng phía trên (hiệu ứng kính)
        hl = QLinearGradient(r.topLeft(), r.center())
        hl.setColorAt(0, QColor(255, 255, 255, 70 if self._hover else 45))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        top = QPainterPath()
        top.addRoundedRect(QRectF(r.left(), r.top(), r.width(), r.height() * 0.55), 11, 11)
        p.fillPath(top.intersected(path), hl)
        p.setPen(QPen(QColor(255, 255, 255, 150 if self._hover else 70), 1.2))
        p.drawPath(path)
        ic = 20
        self.svg.render(p, QRectF(r.center().x() - ic / 2, r.top() + 8, ic, ic))
        f = QFont(self.font())
        f.setPointSizeF(8.6)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(r.left(), r.top() + 30, r.width(), 18), Qt.AlignHCenter | Qt.AlignVCenter, self.name)
        p.end()


class SocialBar(QWidget):
    def __init__(self):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(4, 6, 4, 8)
        h.setSpacing(8)
        for name, url, c1, c2, svg in SOCIAL:
            h.addWidget(SocialButton(name, url, c1, c2, svg), 1)


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
        sb.hide()          # bỏ dòng trạng thái dưới cùng (phiên bản đã có ở nút Kiểm tra cập nhật)
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
