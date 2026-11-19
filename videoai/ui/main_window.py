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

SOCIAL = [   # tên, đường dẫn, màu thương hiệu, biểu tượng (SVG 48x30, màu thật)
    ("Zalo", "https://zalo.me/0979007367", "#0068ff",
     '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 30"><rect x="6" y="3" width="36" height="24" rx="5" fill="#0068ff"/>'
     '<text x="24" y="20" font-family="Arial,Helvetica,sans-serif" font-size="11.5" font-weight="700" fill="#fff" text-anchor="middle">Zalo</text></svg>'),
    ("YouTube", "https://www.youtube.com/channel/UCwSbzgfgu1iMfOR__AB4QGQ?sub_confirmation=1", "#ff0033",
     '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 30"><rect x="9" y="4" width="30" height="22" rx="6" fill="#ff0033"/>'
     '<path d="M21 10v10l8.5-5z" fill="#fff"/></svg>'),
    ("Facebook", "https://facebook.com/mr.huynhxuyenson", "#1877f2",
     '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 30"><circle cx="24" cy="15" r="11.5" fill="#1877f2"/>'
     '<path d="M25.6 26.4v-8.2h2.8l.4-3.3h-3.2v-2.1c0-.9.3-1.6 1.6-1.6h1.7V8.3c-.3 0-1.3-.1-2.5-.1-2.5 0-4.2 1.5-4.2 4.3v2.4h-2.8v3.3h2.8v8.3z" fill="#fff"/></svg>'),
]


class SocialButton(QPushButton):
    """Nút chữ nhật: nền tối nhuốm màu thương hiệu, viền màu thương hiệu, logo ở giữa.
    Rê chuột: sáng nền + viền, hắt bóng phát sáng. Không hiện chú thích khi rê chuột."""

    def __init__(self, name, url, color, svg):
        super().__init__()
        from PySide6.QtCore import QByteArray, QPropertyAnimation, QUrl
        from PySide6.QtGui import QColor, QDesktopServices
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        self.name, self.color = name, QColor(color)
        self.setAccessibleName(name)
        self.svg = QSvgRenderer(QByteArray(svg.encode()))
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)
        self.setMinimumWidth(56)
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = False
        self.glow = QGraphicsDropShadowEffect(self)
        self.glow.setOffset(0, 0)
        self.glow.setColor(QColor(color))
        self.glow.setBlurRadius(0)
        self.setGraphicsEffect(self.glow)
        self.anim = QPropertyAnimation(self.glow, b"blurRadius", self)
        self.anim.setDuration(180)
        self.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))

    def event(self, e):
        from PySide6.QtCore import QEvent
        if e.type() == QEvent.ToolTip:      # không hiện thuộc tính/chú thích khi rê chuột
            return True
        return super().event(e)

    def enterEvent(self, e):
        self._hover = True
        self.anim.stop(); self.anim.setEndValue(18); self.anim.start()
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.anim.stop(); self.anim.setEndValue(0); self.anim.start()
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5 + (1 if self.isDown() else 0), -1.5, -1.5 + (1 if self.isDown() else 0))
        path = QPainterPath()
        path.addRoundedRect(r, 8, 8)
        fill = QColor(self.color)
        fill.setAlpha(70 if self._hover else 34)
        p.fillPath(path, QColor("#0a1030"))
        p.fillPath(path, fill)
        edge = QColor(self.color)
        edge.setAlpha(255 if self._hover else 190)
        p.setPen(QPen(edge, 1.6))
        p.drawPath(path)
        h = r.height() - 6
        w = h * 48 / 30
        self.svg.render(p, QRectF(r.center().x() - w / 2, r.center().y() - h / 2, w, h))
        p.end()


class SocialBar(QWidget):
    def __init__(self):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(2, 6, 2, 6)
        h.setSpacing(8)
        for name, url, color, svg in SOCIAL:
            h.addWidget(SocialButton(name, url, color, svg), 1)


class BrandHeader(QWidget):
    """Khu thương hiệu: logo có vòng sáng + chữ VIDEO AI chuyển màu (Montserrat Black) + nhãn Mr. Huỳnh + gói đang dùng."""

    def __init__(self, plan_text: str = ""):
        super().__init__()
        self.pm = QPixmap(str(assets_dir() / "logo.png"))
        self.plan_text = plan_text
        self.setFixedHeight(78)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(50)

    def set_plan(self, text: str):
        self.plan_text = text
        self.update()

    def _tick(self):
        self._t = (self._t + 0.012) % 1.0
        self.update()

    def paintEvent(self, _):
        import math
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import (QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPainterPath,
                                   QPen)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # logo + vòng sáng xoay
        lr = QRectF(4, 9, 58, 58)
        ring = QConicalGradient(lr.center(), -360 * self._t)
        for pos, col in ((0, "#22d3ee"), (0.33, "#6366f1"), (0.66, "#d946ef"), (1, "#22d3ee")):
            ring.setColorAt(pos, QColor(col))
        p.setPen(QPen(ring, 2.6))
        p.drawRoundedRect(lr.adjusted(-1, -1, 1, 1), 12, 12)
        clip = QPainterPath()
        clip.addRoundedRect(lr.adjusted(2, 2, -2, -2), 10, 10)
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(lr.adjusted(2, 2, -2, -2).toRect(), self.pm)
        p.restore()
        # chữ VIDEO AI chuyển màu, ánh sáng chạy qua
        x0 = lr.right() + 12
        f = QFont("Montserrat")
        f.setWeight(QFont.Black)
        f.setPixelSize(25)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        path = QPainterPath()
        path.addText(QPointF(x0, 36), f, "VIDEO AI")
        br = path.boundingRect()
        g = QLinearGradient(br.topLeft(), br.topRight())
        g.setColorAt(0, QColor("#67e8f9"))
        g.setColorAt(0.5, QColor("#818cf8"))
        g.setColorAt(1, QColor("#f472b6"))
        glow = QColor("#22d3ee")
        glow.setAlpha(55)
        p.setPen(QPen(glow, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.fillPath(path, g)
        sx = br.left() - 40 + (br.width() + 80) * self._t
        sh = QLinearGradient(QPointF(sx - 18, 0), QPointF(sx + 18, 0))
        sh.setColorAt(0, QColor(255, 255, 255, 0))
        sh.setColorAt(0.5, QColor(255, 255, 255, 150))
        sh.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, sh)
        # nhãn Mr. Huỳnh
        f2 = QFont("Be Vietnam Pro")
        f2.setWeight(QFont.ExtraBold)
        f2.setPixelSize(12)
        p.setFont(f2)
        tw = p.fontMetrics().horizontalAdvance("Mr. Huỳnh") + 18
        pill = QRectF(x0, 45, tw, 20)
        pg = QLinearGradient(pill.topLeft(), pill.topRight())
        pg.setColorAt(0, QColor("#f97316"))
        pg.setColorAt(1, QColor("#ec4899"))
        pp = QPainterPath()
        pp.addRoundedRect(pill, 5, 5)
        p.fillPath(pp, pg)
        p.setPen(QColor("white"))
        p.drawText(pill, Qt.AlignCenter, "Mr. Huỳnh")
        if self.plan_text:
            f3 = QFont("Be Vietnam Pro")
            f3.setWeight(QFont.Bold)
            f3.setPixelSize(10)
            p.setFont(f3)
            tw2 = p.fontMetrics().horizontalAdvance(self.plan_text) + 12
            pr = QRectF(pill.right() + 6, 47, tw2, 16)
            pro = self.plan_text.upper().startswith("PRO")
            col = QColor("#facc15" if pro else "#94a3b8")
            p.setPen(QPen(col, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(pr, 4, 4)
            p.setPen(col)
            p.drawText(pr, Qt.AlignCenter, self.plan_text)
        p.end()


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
    def __init__(self, db, engine, characters, webhook, lic=None):
        super().__init__()
        if lic is None:
            from ..core.license import License
            lic = License()
            lic.local()
        self.lic = lic
        self.ctx = Ctx(self, db, engine, characters, webhook)
        self.ctx.license = lic
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
        side.setFixedWidth(236)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(10, 10, 10, 10)
        sv.setSpacing(4)
        self.brand = BrandHeader()
        sv.addWidget(self.brand)
        sep = QWidget()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background:{C['border']};")
        sv.addSpacing(4)
        sv.addWidget(sep)
        sv.addSpacing(4)

        self.menu: dict[str, MenuButton] = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        show_wh = bool(db.get_setting("show_webhook", False))
        items = [(p.key, p.label, p.icon, p.tile) for p in PAGES] + [t for t in TOOL_ITEMS if t[0] != "webhook" or show_wh]
        from PySide6.QtWidgets import QFrame, QScrollArea
        menu_box = QWidget()
        menu_box.setStyleSheet("background:transparent;")
        mv = QVBoxLayout(menu_box)
        mv.setContentsMargins(0, 0, 4, 0)
        mv.setSpacing(4)
        for key, text, ic, tile in items:
            mv.addWidget(self._menu_btn(key, text, ic, tile))
        mv.addStretch()
        scroll = QScrollArea()           # màn hình thấp: cuộn danh sách menu, logo & nút dưới cùng luôn hiện
        scroll.setWidget(menu_box)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}"
                             "QScrollBar:vertical{width:5px;background:transparent;}"
                             "QScrollBar::handle:vertical{background:#2a3d8f;border-radius:2px;min-height:30px;}")
        sv.addWidget(scroll, 1)
        sv.addSpacing(4)
        for key, text, ic, tile in FOOTER_ITEMS:      # Cài Đặt · Thông tin bản quyền · Log: luôn hiện
            sv.addWidget(self._menu_btn(key, text, ic, tile))
        sv.addWidget(SocialBar())
        self.b_lic = QPushButton()
        self.b_lic.setCursor(Qt.PointingHandCursor)
        self.b_lic.clicked.connect(self.open_license)
        sv.addWidget(self.b_lic)
        sv.addSpacing(4)
        self.b_update = QPushButton(tr("Kiểm tra cập nhật") + f"  ·  v{APP_VERSION}")
        self.b_update.setCursor(Qt.PointingHandCursor)
        self.b_update.setStyleSheet(f"QPushButton{{background:transparent;border:1px solid {C['border']};border-radius:4px;"
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

        self._lic_button()
        self._lic_timer = QTimer(self)
        self._lic_timer.setInterval(3 * 3600 * 1000)      # 3 giờ kiểm tra lại 1 lần
        self._lic_timer.timeout.connect(self._lic_tick)
        self._lic_timer.start()
        if lic.status.tier == "pro" and lic.status.exp and lic.status.days_left <= 5:
            QTimer.singleShot(1500, lambda: self.ctx.toast("warn", f"Gói Chuyên nghiệp còn {lic.status.days_left} ngày. Bấm nút bản quyền để gia hạn."))
        engine.toast.connect(self.ctx.toast)
        engine.account_updated.connect(lambda _: self._status())
        self._status()
        start = db.get_setting("last_page", "flow_image")
        if (start in PAGE_BY_KEY and not PAGE_BY_KEY[start].ready) or start in DISABLED_TOOLS:
            start = "flow_image"
        self.go(start if start in self.menu else "flow_image")
        self._apply_tier()

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
        if key == "eula":
            self.open_eula()
            cur = self.db.get_setting("last_page", "flow_image")
            if cur in self.menu:
                self.menu[cur].setChecked(True)
            return
        if key not in self.pages:
            w = self._make_page(key)
            self.pages[key] = w
            self.stack.addWidget(w)
        self.stack.setCurrentWidget(self.pages[key])
        self.menu[key].setChecked(True)
        self.db.set_setting("last_page", key)

    # ------------------------------------------------------------ cập nhật online
    # ---------------- bản quyền
    def _lic_button(self):
        st = self.lic.status
        self._apply_tier()
        if st.kind == "dev":
            self.b_lic.hide()
            self.brand.set_plan("PRO")
            return
        pro = st.tier == "pro"
        self.brand.set_plan("PRO" if pro else "FREE")
        soon = pro and st.exp and st.days_left <= 5
        if pro:
            c1, c2 = ("#f97316", "#db2777") if soon else ("#0e7490", "#4338ca")
            self.b_lic.setText(f"{st.label()}\n" + ("Sắp hết hạn · bấm để gia hạn" if soon else "Bấm để xem / gia hạn"))
        else:
            c1, c2 = "#f59e0b", "#db2777"
            self.b_lic.setText("Gói Miễn phí · 1 tác vụ/lần\nNâng cấp Chuyên nghiệp")
        self.b_lic.setStyleSheet(
            f"QPushButton{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {c1},stop:1 {c2});color:white;"
            "border:1px solid rgba(255,255,255,.25);border-radius:5px;padding:6px 6px;font-weight:700;font-size:12px;}"
            "QPushButton:hover{border:1px solid rgba(255,255,255,.8);}")

    def _apply_tier(self):
        """Gói Miễn phí: toàn phần mềm chỉ chạy 1 tác vụ tại một thời điểm (khóa cả ở bộ máy chạy)."""
        self.ctx.engine.max_total = 0 if self.lic.status.tier == "pro" else 1
        for pg in self.pages.values():
            if hasattr(pg, "apply_tier"):
                pg.apply_tier()

    def is_pro(self) -> bool:
        return self.lic.status.tier == "pro"

    def upsell(self, reason: str):
        from PySide6.QtWidgets import QMessageBox
        m = QMessageBox(self)
        m.setWindowTitle("Gói Miễn phí")
        m.setIcon(QMessageBox.Information)
        m.setText(f"<b>{reason}</b><br><br>Gói Miễn phí dùng đủ chức năng nhưng mỗi lần chỉ tạo <b>1 tác vụ</b>; "
                  "tạo xong tác vụ này mới nhập được prompt cho tác vụ tiếp theo.<br><br>"
                  "Nâng cấp <b>Chuyên nghiệp</b> để chạy hàng loạt, song song trên nhiều tài khoản.")
        b_up = m.addButton("Nâng cấp Chuyên nghiệp", QMessageBox.AcceptRole)
        m.addButton("Để sau", QMessageBox.RejectRole)
        m.exec()
        if m.clickedButton() is b_up:
            self.open_license()

    def open_eula(self, first_run: bool = False) -> bool:
        from .eula_ui import EulaDialog
        return bool(EulaDialog(self, first_run).exec())

    def open_license(self):
        from .license_ui import LicenseDialog
        LicenseDialog(self, self.lic).exec()
        self._lic_button()

    def _lic_tick(self):
        """Kiểm tra lại bản quyền định kỳ (luồng nền). Bị khóa/hết hạn: về gói Miễn phí."""
        if not self.lic.enabled:
            return
        from .license_ui import run_bg
        was_pro = self.is_pro()

        def done(st):
            self._lic_button()
            if was_pro and st.tier == "free":
                self.ctx.toast("warn", (st.message or "Bản quyền Chuyên nghiệp không còn hiệu lực.") + " Đã chuyển về gói Miễn phí.")
        run_bg(self, self.lic.refresh, done, lambda e: None)

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
