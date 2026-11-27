"""Cửa sổ chính: menu bên trái (nút trực quan liền mạch) + các trang."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QIcon, QPixmap, QDesktopServices
from PySide6.QtWidgets import (QAbstractButton, QApplication, QButtonGroup, QHBoxLayout, QLabel, QMainWindow, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from .theme import C, icon_pixmap
from .widgets import MenuButton, ShineButton, Toast
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


MIN_W, START_W = round(1324 * 1.2), round(1484 * 1.2)      # rộng thêm 20%
DISABLED_TOOLS = {"workflow"}     # tạm khóa, sẽ mở ở bản sau
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


class NoButtonTips(QObject):
    """v2.0: rê chuột vào nút không hiện chú thích (tooltip)."""

    def eventFilter(self, obj, e):
        if e.type() == QEvent.ToolTip and isinstance(obj, QAbstractButton):
            return True
        return False


class BrandHeader(QWidget):
    """Khu thương hiệu: logo có vòng sáng + chữ VIDEO AI chuyển màu (Montserrat Black) + nhãn Mr. Huỳnh + gói đang dùng."""

    def __init__(self, plan_text: str = "", on_eula=None):
        super().__init__()
        self.pm = QPixmap(str(assets_dir() / "logo.png"))
        self.plan_text = plan_text
        self.setFixedHeight(92)
        self.b_eula = QPushButton(tr("Thông tin bản quyền"), self)     # nút nhỏ, chữ đơn giản dưới nhãn Mr. Huỳnh
        self.b_eula.setCursor(Qt.PointingHandCursor)
        self.b_eula.setStyleSheet("QPushButton{background:transparent;border:none;color:#8b96c9;font-size:10.5px;"
                                  "font-weight:500;padding:0;text-align:left;}"
                                  "QPushButton:hover{color:#e0f2fe;text-decoration:underline;}")
        self.b_eula.move(self.TX, 72)
        self.b_eula.adjustSize()
        if on_eula:
            self.b_eula.clicked.connect(on_eula)
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    LR = (5, 8, 68, 68)          # khung logo (lớn hơn bản cũ 58 px)
    TX = 90                      # chữ bắt đầu từ đây (dịch sang phải cho cân khung)

    def set_plan(self, text: str):
        self.plan_text = text
        self.update()

    def _tick(self):
        self._t = (self._t + 0.008) % 1.0
        self.update()

    def paintEvent(self, _):
        import math
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import (QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPainterPath,
                                   QPen)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # logo AI: quầng sáng thở + vòng gradient xoay + 2 hạt sáng chạy quanh viền + tia quét chéo + sao lấp lánh
        t = self._t
        lr = QRectF(*self.LR)
        c = lr.center()
        from PySide6.QtGui import QRadialGradient
        breath = 0.5 + 0.5 * math.sin(t * 2 * math.pi * 2)
        halo = QRadialGradient(c, lr.width() * 0.78)
        hc = QColor("#6366f1")
        hc.setAlpha(int(70 + 70 * breath))
        halo.setColorAt(0.55, hc)
        hc2 = QColor("#d946ef")
        hc2.setAlpha(0)
        halo.setColorAt(1, hc2)
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(c, lr.width() * 0.78, lr.height() * 0.78)
        p.setBrush(Qt.NoBrush)
        ring = QConicalGradient(c, -360 * t * 2)
        for pos, col in ((0, "#22d3ee"), (0.33, "#6366f1"), (0.66, "#d946ef"), (1, "#22d3ee")):
            ring.setColorAt(pos, QColor(col))
        p.setPen(QPen(ring, 2.8))
        rr = QPainterPath()
        rr.addRoundedRect(lr.adjusted(-1, -1, 1, 1), 14, 14)
        p.drawPath(rr)
        clip = QPainterPath()
        clip.addRoundedRect(lr.adjusted(2, 2, -2, -2), 12, 12)
        p.save()
        p.setClipPath(clip)
        p.drawPixmap(lr.adjusted(2, 2, -2, -2).toRect(), self.pm)
        # tia sáng quét chéo qua logo (mỗi vòng 1 lần)
        sx = lr.left() - 40 + (lr.width() + 80) * ((t * 2) % 1.0)
        sw = QLinearGradient(QPointF(sx - 14, lr.top()), QPointF(sx + 14, lr.top() + 20))
        sw.setColorAt(0, QColor(255, 255, 255, 0))
        sw.setColorAt(0.5, QColor(255, 255, 255, 95))
        sw.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(lr, sw)
        p.restore()
        # 2 hạt dữ liệu chạy quanh viền, có đuôi
        for k, col in ((0.0, "#67e8f9"), (0.5, "#f0abfc")):
            for j in range(7):
                q = (t * 2 + k - j * 0.012) % 1.0
                pt = rr.pointAtPercent(q)
                cc = QColor(col)
                cc.setAlpha(int(255 * (1 - j / 7)))
                p.setPen(Qt.NoPen)
                p.setBrush(cc)
                p.drawEllipse(pt, 2.6 - j * 0.25, 2.6 - j * 0.25)
        # sao lấp lánh ở 2 góc
        for (px, py, ph) in ((lr.right() - 3, lr.top() + 2, 0.0), (lr.left() + 4, lr.bottom() - 2, 0.5)):
            a_ = max(0.0, math.sin((t * 3 + ph) * 2 * math.pi))
            if a_ > 0.05:
                sc = QColor(255, 255, 255, int(230 * a_))
                p.setPen(QPen(sc, 1.4))
                r_ = 2 + 3.5 * a_
                p.drawLine(QPointF(px - r_, py), QPointF(px + r_, py))
                p.drawLine(QPointF(px, py - r_), QPointF(px, py + r_))
        p.setBrush(Qt.NoBrush)
        # chữ VIDEO AI chuyển màu, ánh sáng chạy qua
        x0 = float(self.TX)
        f = QFont("Montserrat")
        f.setWeight(QFont.Black)
        f.setPixelSize(25)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        path = QPainterPath()
        path.addText(QPointF(x0, 37), f, "VIDEO AI")
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
        pill = QRectF(x0, 46, tw, 20)
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
            pr = QRectF(pill.right() + 6, 48, tw2, 16)
            pro = self.plan_text.upper().startswith("PRO")
            col = QColor("#facc15" if pro else "#94a3b8")
            p.setPen(QPen(col, 1.2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(pr, 4, 4)
            p.setPen(col)
            p.drawText(pr, Qt.AlignCenter, self.plan_text)
        p.end()


MENU_SECTIONS = [   # khóa, tiêu đề, màu nhãn, các mục (theo thứ tự)
    ("image", "TẠO ẢNH", "#22d3ee", ["flow_image", "gpt_image", "grok_image", "muse_image"]),
    ("video", "TẠO VIDEO", "#fb923c", ["flow_video", "meta_muse", "grok_video", "lipsync"]),
    ("tools", "CÔNG CỤ", "#4ade80", ["refs", "workflow", "upscale", "watermark", "quick_tools", "download", "logs"]),
]


class MenuSection(QWidget):
    """Một mục menu: khung màu riêng + nhãn dán ở góc trên bên trái."""

    def __init__(self, title: str, color: str):
        super().__init__()
        self.title, self.color = title, color
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(6, 18, 6, 6)
        self.v.setSpacing(4)

    def add(self, w):
        self.v.addWidget(w)

    def paintEvent(self, _):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 9, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        col = QColor(self.color)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        top = QColor(col)
        top.setAlpha(46)
        bot = QColor(col)
        bot.setAlpha(6)
        g.setColorAt(0, top)
        g.setColorAt(0.6, bot)
        p.fillPath(path, g)
        edge = QColor(col)
        edge.setAlpha(120)
        p.setPen(QPen(edge, 1.2))
        p.drawPath(path)
        f = QFont("Be Vietnam Pro")
        f.setWeight(QFont.ExtraBold)
        f.setPixelSize(11)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.0)
        p.setFont(f)
        tw = p.fontMetrics().horizontalAdvance(self.title) + 18
        tag = QRectF(10, 0, tw, 19)
        tp = QPainterPath()
        tp.addRoundedRect(tag, 4, 4)
        p.fillPath(tp, col)
        p.setPen(QColor("#06102e"))
        p.drawText(tag, Qt.AlignCenter, self.title)
        p.end()


class ComingSoon(QWidget):
    def __init__(self, pdef):
        super().__init__()
        v = QVBoxLayout(self)
        v.addStretch()
        t = QLabel(tr(getattr(pdef, "label", pdef)))
        t.setObjectName("h1")
        t.setAlignment(Qt.AlignCenter)
        m = QLabel(tr("Chức năng này đang được hoàn thiện và sẽ có trong bản cập nhật tới.\nTrong lúc chờ, bạn có thể dùng các chức năng Tạo ảnh, Tạo video và Công cụ ở menu bên trái."))
        m.setObjectName("muted")
        m.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        v.addWidget(m)
        v.addStretch()


VOICE_URL = "https://mrhuynh.net/tools/"      # nút "Tạo giọng nói MIỄN PHÍ" trên thanh trên
# Nút liên kết trên thanh trên: mã → (chữ trên nút, icon, màu, link mặc định). Link đổi được ở trang quản trị › Video hướng
# dẫn (cùng bảng "guides" với link video hướng dẫn, khóa là mã ở đây); chưa nhập / không hợp lệ thì dùng link mặc định.
# Phần tử cuối: tên NGẮN dùng khi thanh trên không đủ chỗ (cửa sổ ở bề rộng tối thiểu) – tên đầy đủ vẫn ở chú thích.
LINKS = {
    "link_auto_workflow": ("Auto-WorkFlow trên Flow", "nodes", ("#f59e0b", "#ef4444", "#a855f7"),
                           "https://mrhuynh.net/auto-workflow/", "Auto-WorkFlow"),
    "link_local_video": ("Tạo Video Local không tốn AI", "film", ("#0ea5e9", "#6366f1", "#ec4899"),
                         "https://mrhuynh.net/tools/", "Video Local"),
}
GUIDE_ACCOUNTS = "settings_accounts"         # mã link video hướng dẫn của tab Cài đặt › Tài khoản (nút "Xem hướng dẫn")


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
        self._no_tips = NoButtonTips(self)
        QApplication.instance().installEventFilter(self._no_tips)
        self.setWindowIcon(QIcon(str(assets_dir() / "logo.png")))
        # 11/2026: toàn bộ giao diện rộng thêm 20% (1324 → 1589, mặc định 1484 → 1781); màn hình nhỏ hơn thì vừa màn hình
        min_w, start_w = MIN_W, START_W
        import os
        scr = QApplication.primaryScreen()
        if scr is not None and os.environ.get("VIDEOAI_HEADLESS") != "1":
            avail = scr.availableGeometry()
            min_w = min(min_w, max(1100, avail.width() - 16))
            start_w = min(start_w, avail.width() - 16)
        self.setMinimumSize(min_w, 760)
        self.resize(max(min_w, start_w), 900)

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
        side.setFixedWidth(280)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(10, 10, 10, 10)
        sv.setSpacing(4)
        self.brand = BrandHeader(on_eula=lambda: self.open_eula())
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
        from PySide6.QtWidgets import QFrame, QScrollArea
        page_items = {p.key: (p.key, p.label, p.icon, p.tile) for p in PAGES}
        tool_items = {t[0]: t for t in TOOL_ITEMS + FOOTER_ITEMS if t[0] != "webhook" or show_wh}
        menu_box = QWidget()
        menu_box.setStyleSheet("background:transparent;")
        mv = QVBoxLayout(menu_box)
        mv.setContentsMargins(0, 8, 4, 0)
        mv.setSpacing(12)
        self.sections: dict[str, MenuSection] = {}
        for sec_key, title, col, keys in MENU_SECTIONS:
            sec = MenuSection(tr(title), col)
            for k in keys:
                it = page_items.get(k) or tool_items.get(k)
                if it:
                    sec.add(self._menu_btn(*it))
            if k == "logs" or sec_key == "tools":
                for k2, t in tool_items.items():
                    if k2 not in keys and k2 not in self.menu:
                        sec.add(self._menu_btn(*t))
            self.sections[sec_key] = sec
            mv.addWidget(sec)
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
        sv.addWidget(SocialBar())
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
        content = QWidget()
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        top = QWidget()
        top.setObjectName("topbar")
        top.setFixedHeight(48)
        top.setStyleSheet(f"QWidget#topbar{{background:#080d2c;border-bottom:1px solid {C['border']};}}")
        th = QHBoxLayout(top)
        th.setContentsMargins(18, 0, 14, 0)
        th.setSpacing(8)
        self.page_title = QLabel()
        self.page_title.setStyleSheet("font-size:15px;font-weight:800;color:#e0e7ff;background:transparent;")
        th.addWidget(self.page_title)
        th.addSpacing(10)
        self.b_guide = QPushButton("  " + tr("Xem Video hướng dẫn"))      # link YouTube riêng cho từng chức năng
        self.b_guide.setIcon(QIcon(icon_pixmap("play", "#ffffff", 14)))
        self.b_guide.setCursor(Qt.PointingHandCursor)
        self.b_guide.setFixedHeight(30)
        self.b_guide.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #ff1f3d,stop:1 #c4001a);"
                                   "color:white;border:1px solid rgba(255,255,255,.25);border-radius:5px;padding:0 12px;"
                                   "font-weight:700;font-size:12px;}QPushButton:hover{border:1px solid rgba(255,255,255,.85);}")
        self.b_guide.clicked.connect(self.open_guide)
        self.b_guide.hide()
        th.addWidget(self.b_guide)
        th.addStretch()
        self.b_voice = ShineButton(tr("Tạo giọng nói MIỄN PHÍ"), "mic")   # nổi bật, ngay cạnh nút gói PRO
        self.b_voice.setToolTip(tr("Mở công cụ tạo giọng nói miễn phí của Mr. Huỳnh") + "\n" + VOICE_URL)
        self.b_voice.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(VOICE_URL)))
        th.addWidget(self.b_voice)
        # hai nút liên kết cạnh "Tạo giọng nói MIỄN PHÍ": link sửa được ở trang quản trị (mục Video hướng dẫn, mã ghi trong LINKS)
        self.link_btns = {}
        for key, (text, ic, colors, _url, _short) in LINKS.items():
            b = ShineButton(tr(text), ic, colors)
            b.clicked.connect(lambda _=False, k=key: self.open_link(k))
            th.addWidget(b)
            self.link_btns[key] = b
        self.b_autowf, self.b_local = self.link_btns["link_auto_workflow"], self.link_btns["link_local_video"]
        th.addSpacing(6)
        self.b_lic = QPushButton()                       # thông tin gói bản quyền + thời hạn
        self.b_lic.setCursor(Qt.PointingHandCursor)
        self.b_lic.setFixedHeight(32)
        self.b_lic.clicked.connect(self.open_license)
        th.addWidget(self.b_lic)
        self.b_settings = QPushButton("  " + tr("Cài đặt"))
        self.b_settings.setIcon(QIcon(icon_pixmap("gear", "#e0e7ff", 18)))
        self.b_settings.setCursor(Qt.PointingHandCursor)
        self.b_settings.setFixedHeight(32)
        self.b_settings.setStyleSheet(f"QPushButton{{background:{C['surface-2']};border:1px solid {C['border-input']};border-radius:5px;"
                                      "padding:0 12px;font-weight:700;color:#e0e7ff;}"
                                      f"QPushButton:hover{{border-color:{C['accent']};}}"
                                      "QPushButton:checked{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0e7490,stop:1 #6d28d9);"
                                      "border:1px solid #67e8f9;color:white;}")
        self.b_settings.clicked.connect(self.open_settings)
        th.addWidget(self.b_settings)
        cv.addWidget(top)
        self.stack = QStackedWidget()
        cv.addWidget(self.stack, 1)
        body.addWidget(content, 1)
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
        self._load_guides()
        self._lic_timer = QTimer(self)
        self._lic_timer.setInterval(3 * 3600 * 1000)      # 3 giờ kiểm tra lại 1 lần
        self._lic_timer.timeout.connect(self._lic_tick)
        self._lic_timer.start()
        # theo dõi bản quyền liên tục: kích hoạt xong (kể cả khi cửa sổ Bản quyền / Thanh toán đã đóng) thì cả
        # phần mềm lên PRO ngay, không cần khởi động lại
        self._lic_sig = self._lic_signature()
        self._lic_watch = QTimer(self)
        self._lic_watch.setInterval(1000)
        self._lic_watch.timeout.connect(self._lic_check_change)
        self._lic_watch.start()
        if lic.status.tier == "pro" and lic.status.exp and lic.status.days_left <= 5:
            QTimer.singleShot(1500, lambda: self.ctx.toast("warn", f"Gói Chuyên nghiệp còn {lic.status.days_left} ngày. Bấm nút bản quyền để gia hạn."))
        engine.toast.connect(self.ctx.toast)
        engine.account_updated.connect(lambda _: self._status())
        self._status()
        start = db.get_setting("last_page", "flow_image")
        if (start in PAGE_BY_KEY and not PAGE_BY_KEY[start].ready) or start in DISABLED_TOOLS or start in ("settings", "logs", "eula"):
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
            if key == "lipsync" and pdef.ready:
                from .pages.lipsync_page import LipSyncPage
                return LipSyncPage(self.ctx, pdef)
            if pdef.platform in ("flow", "gpt", "grok", "muse") and pdef.ready:
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
        if key == "download":
            from .pages.download_page import DownloadPage
            return DownloadPage(self.ctx)
        if key == "quick_tools":
            from .pages.quick_tools import QuickToolsPage
            return QuickToolsPage(self.ctx)
        if key == "watermark":
            from .pages.watermark_page import WatermarkPage
            return WatermarkPage(self.ctx)
        return QLabel(key)

    def _popup(self, key: str, title: str, size: tuple[int, int]):
        """Cài đặt và Log chi tiết mở trong cửa sổ riêng (giữ nguyên nội dung giữa các lần mở)."""
        from PySide6.QtWidgets import QDialog
        if not hasattr(self, "_popups"):
            self._popups = {}
        d = self._popups.get(key)
        if d is None:
            d = QDialog(self)
            d.setWindowTitle(f"{tr(title)} · {APP_NAME}")
            d.resize(*size)
            lay = QVBoxLayout(d)
            lay.setContentsMargins(0, 0, 0, 0)
            w = self._make_page(key)
            self.pages[key] = w
            lay.addWidget(w)
            self._popups[key] = d
        d.show()
        d.raise_()
        d.activateWindow()
        return d

    # ---------------- video hướng dẫn (link YouTube theo từng chức năng, sửa ở trang quản trị)
    def _load_guides(self):
        from .license_ui import run_bg
        self.guides = self.lic.guides(online=False)
        self._guide_button()
        if self.lic.enabled:
            def done(g):
                self.guides = g
                self._guide_button()
            run_bg(self, lambda: self.lic.guides(online=True), done, lambda e: None)

    def _guide_url(self, key: str | None = None) -> str:
        key = key or getattr(self, "_cur_page", "")
        g = getattr(self, "guides", {}) or {}
        return (g.get(key) or "").strip()

    def _guide_button(self):
        url = self._guide_url()
        self.b_guide.setVisible(bool(url))
        self.b_guide.setToolTip(url)
        for key, b in getattr(self, "link_btns", {}).items():
            b.setToolTip(tr(LINKS[key][0]) + "\n" + self.link_url(key))
        sp = getattr(self, "pages", {}).get("settings")     # nút "Xem hướng dẫn" ở tab Tài khoản dùng chung bảng link này
        if sp is not None and hasattr(sp, "refresh_guide"):
            sp.refresh_guide()
        self._fit_topbar()

    def _fit_topbar(self):
        """Thanh trên không đủ chỗ cho tên đầy đủ của hai nút liên kết (đo ở bề rộng tối thiểu 1589: thiếu khoảng 120 px,
        chữ trên nút và nút gói bản quyền bị cắt) → dùng tên ngắn; đủ chỗ thì hiện lại tên đầy đủ."""
        btns = getattr(self, "link_btns", None)
        if not btns or getattr(self, "_fitting", False):
            return
        self._fitting = True
        try:
            top = self.b_voice.parentWidget()

            def use(short: bool):
                for key, b in btns.items():
                    t = tr(LINKS[key][4] if short else LINKS[key][0])
                    if b.text() != t:
                        b.setText(t)
                        b.updateGeometry()
                top.layout().invalidate()
            use(False)
            if top.layout().minimumSize().width() > top.width():
                use(True)
        finally:
            self._fitting = False

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_topbar()

    def link_url(self, key: str) -> str:
        """Link của nút liên kết trên thanh trên: lấy ở trang quản trị nếu có (https), không thì link mặc định."""
        u = self._guide_url(key)
        return u if u.lower().startswith("https://") else LINKS[key][3]

    def open_link(self, key: str):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl(self.link_url(key)))

    def open_guide(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        url = self._guide_url()
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def restart_app(self):
        """Mở lại phần mềm để áp dụng ngôn ngữ / bộ màu — liền mạch: không màn hình chào, giữ vị trí,
        kích thước cửa sổ và trang đang mở, mở lại Cài đặt nếu đang mở."""
        import sys
        from PySide6.QtCore import QProcess
        pops = getattr(self, "_popups", {})
        self.db.set_setting("restart_state", {
            "geom": bytes(self.saveGeometry().toHex()).decode(),
            "settings": bool(pops.get("settings") and pops["settings"].isVisible()),
            "settings_geom": bytes(pops["settings"].saveGeometry().toHex()).decode() if pops.get("settings") else "",
            "settings_tab": getattr(self.pages.get("settings"), "current_tab", lambda: 0)()})
        args = [a for a in (sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv) if a != "--restarted"]
        QProcess.startDetached(sys.executable, args + ["--restarted"])
        self.close()
        QApplication.quit()

    def open_settings(self):
        return self._popup("settings", "Cài đặt", (1180, 760))

    def open_logs(self):
        return self._popup("logs", "Log chi tiết", (1100, 700))

    def go(self, key):
        if key in ("settings", "logs"):
            (self.open_settings if key == "settings" else self.open_logs)()
            cur = self.db.get_setting("last_page", "flow_image")
            if cur in self.menu and cur not in ("settings", "logs"):
                self.menu[cur].setChecked(True)
            return
        if key == "eula":
            self.open_eula()
            cur = self.db.get_setting("last_page", "flow_image")
            if cur in self.menu:
                self.menu[cur].setChecked(True)
            return
        self.page(key)
        self.stack.setCurrentWidget(self.pages[key])
        if key in self.menu:
            self.menu[key].setChecked(True)
        else:                                   # Cài đặt (nút góc trên): bỏ chọn menu bên trái
            self.group.setExclusive(False)
            for b in self.group.buttons():
                b.setChecked(False)
            self.group.setExclusive(True)
        names = {p.key: p.label for p in PAGES}
        names.update({k: n for k, n, _, _ in TOOL_ITEMS + FOOTER_ITEMS})
        names["settings"] = "Cài đặt"
        self.page_title.setText(tr(names.get(key, "")))
        self._cur_page = key
        if hasattr(self, "b_guide"):
            self._guide_button()
        self.db.set_setting("last_page", key)

    def page(self, key):
        """Trang theo khóa (tạo nếu chưa có) mà không chuyển sang trang đó."""
        if key not in self.pages:
            w = self._make_page(key)
            self.pages[key] = w
            self.stack.addWidget(w)
        return self.pages[key]

    def show_task(self, page_key: str, job_id: str, group: str):
        """Mở trang chứa tác vụ, lọc đúng nhóm trạng thái và chọn sẵn dòng của tác vụ đó."""
        self.go(page_key)
        pg = self.pages.get(page_key)
        if hasattr(pg, "focus_job"):
            pg.focus_job(job_id, group)

    # ------------------------------------------------------------ cập nhật online
    # ---------------- bản quyền
    def _lic_button(self):
        st = self.lic.status
        self._apply_tier()
        if st.kind == "dev":
            self.b_lic.setText("  PRO · " + tr("Bản phát triển"))
            self.brand.set_plan("PRO")
            pro, soon = True, False
        else:
            pro = st.tier == "pro"
            self.brand.set_plan("PRO" if pro else "FREE")
            soon = bool(pro and st.exp and st.days_left <= 5)
            if pro:
                left = tr("vĩnh viễn") if st.lifetime else f"{tr('còn')} {st.days_left} {tr('ngày')}"
                self.b_lic.setText(f"  PRO · {tr(st.plan_name)} · {left}" + ("  ·  " + tr("Gia hạn") if soon else ""))
            else:
                self.b_lic.setText("  FREE · " + tr("Gói Miễn phí") + "  ·  " + tr("Nâng cấp"))
        self.b_lic.setIcon(QIcon(icon_pixmap("shield", "#ffffff", 16)))
        if pro and not soon:
            bg = "qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #0e7490,stop:1 #4338ca)"
        else:
            bg = "qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #f59e0b,stop:1 #db2777)"
        self.b_lic.setToolTip(tr("Gói bản quyền đang dùng · bấm để xem các gói, nhập key, gia hạn"))
        self.b_lic.setStyleSheet(f"QPushButton{{background:{bg};color:white;border:1px solid rgba(255,255,255,.25);"
                                 "border-radius:5px;padding:0 12px;font-weight:700;font-size:12px;}"
                                 "QPushButton:hover{border:1px solid rgba(255,255,255,.85);}")

    def _lic_signature(self):
        st = self.lic.status
        return (st.tier, st.kind, st.exp, getattr(st, "plan_name", ""), st.ok)

    def _lic_check_change(self):
        sig = self._lic_signature()
        if sig == self._lic_sig:
            return
        was_pro = bool(self._lic_sig and self._lic_sig[0] == "pro")
        self._lic_sig = sig
        self._lic_button()
        if sig[0] == "pro" and not was_pro:
            self.ctx.toast("ok", tr("Đã kích hoạt gói Chuyên nghiệp (PRO) – dùng được ngay, không cần khởi động lại."))

    def _apply_tier(self):
        """Gói Miễn phí: toàn phần mềm chỉ chạy 1 tác vụ tại một thời điểm (khóa cả ở bộ máy chạy)."""
        self.ctx.engine.max_total = 0 if self.lic.status.tier == "pro" else 1
        for pg in self.pages.values():
            if hasattr(pg, "apply_tier"):
                pg.apply_tier()
        from PySide6.QtWidgets import QApplication
        for wd in QApplication.topLevelWidgets():         # hộp đang mở (Quy trình tự động…) cũng bỏ giới hạn ngay
            if wd is not self and wd.isVisible() and hasattr(wd, "apply_tier"):
                try:
                    wd.apply_tier()
                except Exception:
                    pass

    def is_pro(self) -> bool:
        return self.lic.status.tier == "pro"

    def upsell(self, reason: str, detail: str | None = None):
        """Hộp mời nâng cấp PRO ngắn gọn: lý do 1 dòng + 3 lợi ích + nút "Nâng cấp PRO ngay" nổi bật."""
        from .upsell import UpsellDialog
        d = UpsellDialog(self, reason, detail)
        d.exec()
        if d.upgrade:
            self.open_license()

    POLICY_URL = "https://policies.google.com/terms/generative-ai/use-policy"

    def ensure_flow_rights(self) -> bool:
        """Google Flow hỏi "Quyền sử dụng video / hình ảnh này" mỗi khi tải tệp lên. Tools hỏi người dùng MỘT lần,
        người dùng đồng ý thì tools tự bấm "Tôi đồng ý, không hiện lại" trên Flow (không tự đồng ý thay người dùng)."""
        if self.db.get_setting("flow_rights_ok", False):
            return True
        from PySide6.QtWidgets import QMessageBox
        m = QMessageBox(self)
        m.setWindowTitle(tr("Quyền sử dụng nội dung tải lên"))
        m.setIcon(QMessageBox.Information)
        m.setTextFormat(Qt.RichText)
        m.setText(tr("Google Flow yêu cầu xác nhận trước khi tải ảnh / video lên:") + "<br><br><i>" +
                  tr("Hãy đảm bảo rằng bạn có các quyền cần thiết đối với mọi nội dung hoặc tệp mà bạn tải lên, kể cả "
                     "nội dung về trẻ vị thành niên. Không được tạo nội dung vi phạm quyền của người khác, chẳng hạn như "
                     "nội dung lừa gạt, quấy rối hoặc gây hại. Khi sử dụng Flow, bạn phải tuân thủ") +
                  f' <a href="{self.POLICY_URL}">' + tr("Chính sách về các hành vi bị cấm của Google") + "</a>.</i><br><br>" +
                  tr("Bấm \"Tôi đồng ý\" để xác nhận. Tools sẽ tự bấm đồng ý giúp bạn trên Flow ở các lần tải lên sau."))
        b_ok = m.addButton(tr("Tôi đồng ý"), QMessageBox.AcceptRole)
        m.addButton(tr("Huỷ"), QMessageBox.RejectRole)
        m.exec()
        if m.clickedButton() is b_ok:
            self.db.set_setting("flow_rights_ok", True)
            return True
        self.ctx.toast("info", tr("Chưa xác nhận quyền sử dụng – tác vụ có tải ảnh / video lên Flow chưa được chạy."))
        return False

    TERMS_URL = "https://policies.google.com/terms"
    PRIVACY_URL = "https://policies.google.com/privacy"

    def ensure_flow_terms(self) -> bool:
        """Tài khoản Google lần đầu vào Flow phải chấp nhận Điều khoản & Chính sách của Google, rồi Flow mới cho tạo.
        Tools hỏi người dùng MỘT lần; người dùng đồng ý thì tools tự tick ô bắt buộc + bấm Đồng ý / Tiếp tục,
        bỏ qua màn chào và tạo Dự án mới. Ô nhận email quảng cáo luôn để trống."""
        if self.db.get_setting("flow_terms_ok", False):
            return True
        from PySide6.QtWidgets import QMessageBox
        m = QMessageBox(self)
        m.setWindowTitle(tr("Điều khoản Google Flow"))
        m.setIcon(QMessageBox.Information)
        m.setTextFormat(Qt.RichText)
        m.setText(tr("Với tài khoản Google lần đầu dùng Flow, Google yêu cầu chấp nhận điều khoản trước khi tạo ảnh / video:") +
                  f'<br><br>• <a href="{self.TERMS_URL}">' + tr("Điều khoản dịch vụ của Google") + "</a>" +
                  f'<br>• <a href="{self.PRIVACY_URL}">' + tr("Chính sách quyền riêng tư của Google") + "</a>" +
                  f'<br>• <a href="{self.POLICY_URL}">' + tr("Chính sách về các hành vi bị cấm của Google") + "</a><br><br>" +
                  tr("Bấm \"Tôi đồng ý\" để chấp nhận. Tools sẽ tự xác nhận giúp bạn trên Flow, bỏ qua màn chào và tạo "
                     "dự án mới. Tools không đăng ký nhận email quảng cáo."))
        b_ok = m.addButton(tr("Tôi đồng ý"), QMessageBox.AcceptRole)
        m.addButton(tr("Huỷ"), QMessageBox.RejectRole)
        m.exec()
        if m.clickedButton() is b_ok:
            self.db.set_setting("flow_terms_ok", True)
            return True
        self.ctx.toast("info", tr("Chưa đồng ý điều khoản Google Flow – tác vụ Flow chưa được chạy."))
        return False

    def open_eula(self, first_run: bool = False) -> bool:
        from .eula_ui import EulaDialog
        return bool(EulaDialog(self, first_run).exec())

    def open_license(self):
        from .license_ui import LicenseDialog
        LicenseDialog(self, self.lic).exec()
        self._lic_sig = self._lic_signature()
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
        att = self.db.get_setting("update_attempt", {}) or {}
        if att and att.get("from") != APP_VERSION:          # đã lên bản mới → xóa dấu lần cài
            self.db.set_setting("update_attempt", {})
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
        try:                                   # SYNC API chạy cùng ứng dụng: tắt API HTTP + gỡ biểu tượng ở khay hệ thống
            sync = getattr(self.ctx, "sync_api", None)
            if sync is not None:
                sync.shutdown()
        except Exception:
            pass
        self.ctx.engine.shutdown()
        super().closeEvent(e)
