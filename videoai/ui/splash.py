"""Màn hình khởi động động: dải phim chạy, vòng sáng xoay quanh logo, chữ VIDEO AI chuyển màu có vệt sáng,
hạt sáng bay, nút play nhịp đập, thanh tiến trình chuyển màu + dòng trạng thái."""
from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QEventLoop, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QGuiApplication, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QWidget

from ..core.paths import APP_VERSION, assets_dir

W, H = 680, 400


class AnimatedSplash(QWidget):
    MIN_SHOW = 2.4   # giây: thời gian tối thiểu để thấy trọn hiệu ứng

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(W, H)
        self.logo = QPixmap(str(assets_dir() / "logo.png"))
        self.msg = "Đang khởi động…"
        self.progress = 0.05
        self._shown = 0.0
        self._t0 = time.time()
        rnd = random.Random(7)
        self.particles = [(rnd.uniform(0, W), rnd.uniform(0, H), rnd.uniform(0.6, 2.2), rnd.uniform(8, 30), rnd.random())
                          for _ in range(46)]
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(16)
        scr = QGuiApplication.primaryScreen()
        if scr:
            g = scr.availableGeometry()
            self.move(g.center().x() - W // 2, g.center().y() - H // 2)

    # API giống QSplashScreen
    def showMessage(self, text: str, *_):
        self.msg = text
        self.progress = min(0.95, self.progress + 0.22)
        self.repaint()

    def show(self):
        super().show()
        self._shown = time.time()
        self.pump(0.15)

    def pump(self, seconds: float):
        loop = QEventLoop()
        QTimer.singleShot(int(seconds * 1000), loop.quit)
        loop.exec()

    def finish(self, win=None):
        left = self.MIN_SHOW - (time.time() - self._shown)
        self.msg = "Sẵn sàng!"
        if left > 0:
            end = time.time() + left
            while time.time() < end:
                self.progress = min(1.0, self.progress + (1 - self.progress) * 0.08)
                self.pump(0.03)
        self.progress = 1.0
        for k in range(10):     # mờ dần
            self.setWindowOpacity(1 - k / 10)
            self.pump(0.025)
        self.timer.stop()
        self.close()

    # ------------------------------------------------------------------ vẽ
    def paintEvent(self, _):
        t = time.time() - self._t0
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        card = QRectF(8, 8, W - 16, H - 16)
        clip = QPainterPath()
        clip.addRoundedRect(card, 14, 14)
        p.setClipPath(clip)

        bg = QLinearGradient(card.topLeft(), card.bottomRight())
        bg.setColorAt(0, QColor("#050a26"))
        bg.setColorAt(0.55, QColor("#0d1150"))
        bg.setColorAt(1, QColor("#2a0b45"))
        p.fillRect(card, bg)
        # quầng sáng chạy
        for cx, cy, col, ph in ((0.25, 0.3, "#22d3ee", 0.0), (0.8, 0.65, "#d946ef", 2.0), (0.55, 0.15, "#6366f1", 4.0)):
            x = card.left() + card.width() * (cx + 0.06 * math.sin(t * 0.8 + ph))
            y = card.top() + card.height() * (cy + 0.06 * math.cos(t * 0.7 + ph))
            rg = QRadialGradient(QPointF(x, y), 230)
            c = QColor(col)
            c.setAlpha(70)
            rg.setColorAt(0, c)
            c2 = QColor(col)
            c2.setAlpha(0)
            rg.setColorAt(1, c2)
            p.fillRect(card, rg)
        # hạt sáng bay lên
        for x, y, r, sp, ph in self.particles:
            yy = (y - t * sp) % H
            a = int(90 + 120 * (0.5 + 0.5 * math.sin(t * 3 + ph * 6)))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(170, 230, 255, a))
            p.drawEllipse(QPointF(x, yy), r, r)
        # dải phim chạy ở dưới
        self._film(p, card, t)

        # logo + vòng sáng xoay
        cx, cy = card.left() + 150, card.top() + 165
        pulse = 1 + 0.035 * math.sin(t * 4)
        size = 128 * pulse
        lr = QRectF(cx - size / 2, cy - size / 2, size, size)
        glow = QRadialGradient(lr.center(), size * 0.95)
        glow.setColorAt(0, QColor(34, 211, 238, 110))
        glow.setColorAt(1, QColor(34, 211, 238, 0))
        p.setBrush(glow)
        p.drawEllipse(lr.center(), size * 0.95, size * 0.95)
        ring = QConicalGradient(lr.center(), -t * 140)
        for pos, col in ((0, "#22d3ee"), (0.33, "#6366f1"), (0.66, "#d946ef"), (1, "#22d3ee")):
            ring.setColorAt(pos, QColor(col))
        p.setPen(QPen(ring, 4))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(lr.adjusted(-6, -6, 6, 6), 24, 24)
        lc = QPainterPath()
        lc.addRoundedRect(lr, 18, 18)
        p.save()
        p.setClipPath(lc, Qt.IntersectClip)
        p.drawPixmap(lr.toRect(), self.logo)
        p.restore()

        # chữ VIDEO AI
        x0 = cx + 95
        f = QFont("Montserrat")
        f.setWeight(QFont.Black)
        f.setPixelSize(58)
        path = QPainterPath()
        path.addText(QPointF(x0, cy - 4), f, "VIDEO AI")
        br = path.boundingRect()
        g = QLinearGradient(br.topLeft(), br.topRight())
        shift = 0.15 * math.sin(t * 1.5)
        g.setColorAt(0, QColor("#67e8f9"))
        g.setColorAt(max(0.05, min(0.95, 0.5 + shift)), QColor("#818cf8"))
        g.setColorAt(1, QColor("#f472b6"))
        sh = QColor("#22d3ee")
        sh.setAlpha(60)
        p.setPen(QPen(sh, 7, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.fillPath(path, g)
        sx = br.left() - 60 + (br.width() + 120) * ((t * 0.55) % 1.0)
        shine = QLinearGradient(QPointF(sx - 30, 0), QPointF(sx + 30, 0))
        shine.setColorAt(0, QColor(255, 255, 255, 0))
        shine.setColorAt(0.5, QColor(255, 255, 255, 190))
        shine.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, shine)

        # nhãn Mr. Huỳnh + khẩu hiệu
        f2 = QFont("Be Vietnam Pro")
        f2.setWeight(QFont.ExtraBold)
        f2.setPixelSize(17)
        p.setFont(f2)
        tw = p.fontMetrics().horizontalAdvance("Mr. Huỳnh") + 26
        pill = QRectF(x0 + 2, cy + 10, tw, 30)
        pg = QLinearGradient(pill.topLeft(), pill.topRight())
        pg.setColorAt(0, QColor("#f97316"))
        pg.setColorAt(1, QColor("#ec4899"))
        pp = QPainterPath()
        pp.addRoundedRect(pill, 6, 6)
        p.fillPath(pp, pg)
        p.setPen(QColor("white"))
        p.drawText(pill, Qt.AlignCenter, "Mr. Huỳnh")
        # nút play nhịp đập
        pc = QPointF(pill.right() + 30, pill.center().y())
        pr = 15 + 2 * math.sin(t * 5)
        p.setPen(QPen(QColor(255, 255, 255, 180), 2))
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawEllipse(pc, pr, pr)
        tri = QPainterPath()
        tri.moveTo(pc.x() - 5, pc.y() - 7)
        tri.lineTo(pc.x() + 8, pc.y())
        tri.lineTo(pc.x() - 5, pc.y() + 7)
        tri.closeSubpath()
        p.fillPath(tri, QColor("white"))
        f3 = QFont("Be Vietnam Pro")
        f3.setWeight(QFont.DemiBold)
        f3.setPixelSize(14)
        p.setFont(f3)
        p.setPen(QColor("#c7d2fe"))
        p.drawText(QPointF(x0 + 2, cy + 66), "Tạo ảnh & video AI hàng loạt · Google Flow")

        # thanh tiến trình
        bar = QRectF(card.left() + 40, card.bottom() - 108, card.width() - 80, 6)
        bp = QPainterPath()
        bp.addRoundedRect(bar, 3, 3)
        p.fillPath(bp, QColor(255, 255, 255, 28))
        fill = QRectF(bar.left(), bar.top(), bar.width() * self.progress, bar.height())
        fp = QPainterPath()
        fp.addRoundedRect(fill, 3, 3)
        gg = QLinearGradient(bar.topLeft(), bar.topRight())
        gg.setColorAt(0, QColor("#22d3ee"))
        gg.setColorAt(0.5, QColor("#6366f1"))
        gg.setColorAt(1, QColor("#d946ef"))
        p.fillPath(fp, gg)
        f4 = QFont("Be Vietnam Pro")
        f4.setPixelSize(12)
        p.setFont(f4)
        p.setPen(QColor("#9aa6d6"))
        dots = "." * (int(t * 3) % 4)
        p.drawText(QRectF(bar.left(), bar.bottom() + 6, bar.width(), 18), Qt.AlignLeft | Qt.AlignVCenter,
                   self.msg.rstrip(".…") + dots)
        p.drawText(QRectF(bar.left(), bar.bottom() + 6, bar.width(), 18), Qt.AlignRight | Qt.AlignVCenter,
                   f"v{APP_VERSION}  ·  {int(self.progress * 100)}%")
        p.setClipping(False)
        # viền thẻ
        edge = QLinearGradient(card.topLeft(), card.bottomRight())
        edge.setColorAt(0, QColor(103, 232, 249, 160))
        edge.setColorAt(1, QColor(217, 70, 239, 160))
        p.setPen(QPen(edge, 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawPath(clip)
        p.end()

    def _film(self, p: QPainter, card: QRectF, t: float):
        top = card.bottom() - 70
        h = 58
        strip = QRectF(card.left(), top, card.width(), h)
        p.fillRect(strip, QColor(0, 0, 0, 120))
        fw, gap = 84, 10
        off = (t * 60) % (fw + gap)
        cols = ["#0e7490", "#4338ca", "#7e22ce", "#be185d", "#0369a1", "#6d28d9"]
        x = card.left() - (fw + gap) + off
        k = int(t * 60 // (fw + gap))
        while x < card.right():
            fr = QRectF(x, top + 12, fw, h - 24)
            g = QLinearGradient(fr.topLeft(), fr.bottomRight())
            c = QColor(cols[(k) % len(cols)])
            c.setAlpha(150)
            g.setColorAt(0, c)
            g.setColorAt(1, QColor(255, 255, 255, 25))
            fp = QPainterPath()
            fp.addRoundedRect(fr, 3, 3)
            p.fillPath(fp, g)
            x += fw + gap
            k -= 1
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        hx = card.left() - 18 + (t * 60) % 18
        while hx < card.right():
            p.drawRoundedRect(QRectF(hx, top + 3, 8, 5), 1.5, 1.5)
            p.drawRoundedRect(QRectF(hx, top + h - 8, 8, 5), 1.5, 1.5)
            hx += 18
