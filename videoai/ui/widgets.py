"""Các thành phần giao diện dùng chung."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFileDialog, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QSizePolicy,
                               QTextEdit, QToolButton, QVBoxLayout, QWidget)

from .theme import C, G, TOKENS, gradient, icon, icon_pixmap
from ..core.i18n import tr

TILES = G["icon-tiles"]


def button(text: str, kind: str | None = None, icon_name: str | None = None, icon_color: str = "#ffffff") -> QPushButton:
    b = QPushButton(tr(text))
    if kind:
        b.setProperty("kind", kind)
    if icon_name:
        b.setIcon(icon(icon_name, icon_color, 16))
        b.setIconSize(QSize(16, 16))
    b.setCursor(Qt.PointingHandCursor)
    return b


def icon_button(name: str, tip: str, color: str = "#aab4e8") -> QPushButton:
    b = QPushButton()
    b.setProperty("kind", "icon")
    b.setIcon(icon(name, color, 14))
    b.setFixedSize(28, 28)
    b.setToolTip(tr(tip))
    b.setAccessibleName(tr(tip))
    b.setCursor(Qt.PointingHandCursor)
    return b


def label(text: str, obj: str | None = None) -> QLabel:
    l = QLabel(tr(text))
    if obj:
        l.setObjectName(obj)
    return l


def field(title: str, w: QWidget) -> QWidget:
    box = QWidget()
    v = QVBoxLayout(box)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(4)
    lab = label(title, "fieldLabel")
    lab.setBuddy(w)
    v.addWidget(lab)
    v.addWidget(w)
    return box


def combo(items: list[str], current: str | None = None) -> QComboBox:
    c = QComboBox()
    c.addItems([tr(i) for i in items])
    if current:
        i = c.findText(tr(current))
        if i >= 0:
            c.setCurrentIndex(i)
    c.setCursor(Qt.PointingHandCursor)
    return c


# ------------------------------------------------------------------ menu
class MenuButton(QAbstractButton):
    """Nút menu trực quan: ô icon gradient + nhãn; nút đang chọn được tô gradient và phát sáng."""

    def __init__(self, text: str, icon_name: str, tile: int, parent=None):
        super().__init__(parent)
        self.setText(tr(text))
        self.icon_name = icon_name
        self.tile = TILES[tile % len(TILES)]
        self.badge = 0
        self.soon = False
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(35)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setAccessibleName(self.text())
        self._hover = False
        self.setFocusPolicy(Qt.TabFocus)

    def set_badge(self, n: int):
        self.badge = n
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def sizeHint(self):
        return QSize(256, 37)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 5.5, 5.5)
        if self.isChecked():
            p.fillPath(path, gradient(r, G["active"]))
            p.setPen(QPen(QColor(103, 232, 249, 150), 1))
            p.drawPath(path)
        else:
            p.fillPath(path, QColor(C["surface-2"]))
            pen = QColor(C["accent"]) if (self._hover or self.hasFocus()) else QColor(C["border"])
            if self._hover and not self.hasFocus():
                pen.setAlpha(160)
            p.setPen(QPen(pen, 2 if self.hasFocus() else 1))
            p.drawPath(path)
        # ô icon
        tr_ = QRectF(r.left() + 6, r.center().y() - 13, 26, 26)
        tp = QPainterPath()
        tp.addRoundedRect(tr_, 4.5, 4.5)
        if self.isChecked():
            p.fillPath(tp, QColor(255, 255, 255, 56))
        else:
            p.fillPath(tp, gradient(tr_, self.tile, horizontal=False))
        pm = icon_pixmap(self.icon_name, "#ffffff", 16)
        p.drawPixmap(int(tr_.center().x() - 8), int(tr_.center().y() - 8), pm)
        # chữ
        f = QFont(self.font())
        f.setPointSizeF(9.6)
        f.setWeight(QFont.Bold if self.isChecked() else QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor("#ffffff" if self.isChecked() else "#e8eeff"))
        p.drawText(QRectF(tr_.right() + 10, r.top(), r.width() - (96 if self.soon else 60), r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, p.fontMetrics().elidedText(self.text(), Qt.ElideRight, int(r.width() - (96 if self.soon else 60))))
        if self.soon and not self.badge:
            f2 = QFont(self.font())
            f2.setPointSizeF(7.2)
            p.setFont(f2)
            t = tr("sắp có")
            bw = p.fontMetrics().horizontalAdvance(t) + 10
            br = QRectF(r.right() - bw - 6, r.center().y() - 8, bw, 16)
            bp = QPainterPath()
            bp.addRoundedRect(br, 3, 3)
            p.setPen(QPen(QColor("#33407e"), 1))
            p.drawPath(bp)
            p.setPen(QColor(C["text-faint"]))
            p.drawText(br, Qt.AlignCenter, t)
        # badge
        if self.badge:
            t = str(self.badge)
            bw = 12 + 7 * len(t)
            br = QRectF(r.right() - bw - 8, r.center().y() - 9, bw, 18)
            bp = QPainterPath()
            bp.addRoundedRect(br, 4.5, 4.5)
            p.fillPath(bp, QColor("#ffffff" if self.isChecked() else C["accent-3"]))
            f.setPointSizeF(8.5)
            f.setWeight(QFont.Bold)
            p.setFont(f)
            p.setPen(QColor("#7e22ce" if self.isChecked() else "#ffffff"))
            p.drawText(br, Qt.AlignCenter, t)
        p.end()


# ------------------------------------------------------------------ thống kê
class StatCard(QFrame):
    clicked = Signal(str)
    STYLE = {
        "running": ("info", "info-bg", "#1d3d6b", "play", "Đang chạy"),
        "queued": ("warning", "warning-bg", "#5a4416", "clock", "Hàng đợi"),
        "done": ("success", "success-bg", "#1b5444", "check", "Hoàn thành"),
        "failed": ("danger", "danger-bg", "#62202f", "alert", "Lỗi"),
        "accounts": ("violet", "violet-bg", "#4b2a7a", "user_ok", "Tài khoản"),
    }

    def __init__(self, key: str):
        super().__init__()
        self.key = key
        fg, bg, bd, ic, text = self.STYLE[key]
        self.setStyleSheet(f"QFrame{{background:{C[bg]};border:1px solid {bd};border-radius:6px;}}"
                           f"QLabel{{background:transparent;border:none;color:{C[fg]};}}")
        self.setCursor(Qt.PointingHandCursor)
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(10)
        ib = QLabel()
        ib.setFixedSize(34, 34)
        ib.setAlignment(Qt.AlignCenter)
        ib.setStyleSheet(f"background:{bd};border-radius:5px;")
        ib.setPixmap(icon_pixmap(ic, C[fg], 18))
        h.addWidget(ib)
        v = QVBoxLayout()
        v.setSpacing(0)
        self.value = QLabel("0")
        self.value.setStyleSheet(f"font-size:21px;font-weight:700;color:{C[fg]};")
        cap = QLabel(tr(text))
        cap.setStyleSheet(f"font-size:11px;color:{C[fg]};")
        v.addWidget(self.value)
        v.addWidget(cap)
        h.addLayout(v)
        h.addStretch()
        self.setAccessibleName(tr(text))

    def set(self, n: int):
        self.value.setText(str(n))

    def mousePressEvent(self, e):
        self.clicked.emit(self.key)


class GradientBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(6)
        self.value = 0.0

    def set(self, v: float):
        self.value = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        bg = QPainterPath()
        bg.addRoundedRect(r, 3, 3)
        p.fillPath(bg, QColor(C["surface-2"]))
        if self.value > 0:
            fr = QRectF(r.left(), r.top(), r.width() * self.value, r.height())
            fp = QPainterPath()
            fp.addRoundedRect(fr, 3, 3)
            p.fillPath(fp, gradient(r, G["progress"]))
        p.end()


# ------------------------------------------------------------------ card
class Card(QFrame):
    """Khung có tiêu đề + icon; collapsible=True thì bấm tiêu đề để thu gọn."""

    def __init__(self, title: str, icon_name: str = "sliders", collapsible: bool = False, collapsed: bool = False,
                 icon_color: str | None = None):
        super().__init__()
        self.setObjectName("card")
        self._v = QVBoxLayout(self)
        self._v.setContentsMargins(14, 10, 14, 10)
        self._v.setSpacing(8)
        head = QWidget()
        hl = QHBoxLayout(head)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(10)
        ib = QLabel()
        ib.setFixedSize(28, 28)
        ib.setAlignment(Qt.AlignCenter)
        ib.setStyleSheet("background:#16307a;border-radius:4px;")
        ib.setPixmap(icon_pixmap(icon_name, icon_color or "#67e8f9", 16))
        hl.addWidget(ib)
        t = QLabel(tr(title))
        t.setObjectName("h2")
        hl.addWidget(t)
        hl.addStretch()
        self.head_layout = hl                      # chỗ đặt nút phụ bên phải tiêu đề
        self.body = QWidget()
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(8)
        self._v.addWidget(head)
        self._v.addWidget(self.body)
        if collapsible:
            self.arrow = QLabel()
            hl.addWidget(self.arrow)
            head.setCursor(Qt.PointingHandCursor)
            head.mousePressEvent = lambda e: self.toggle()
            self.set_collapsed(collapsed)

    def toggle(self):
        self.set_collapsed(self.body.isVisible())

    def set_collapsed(self, c: bool):
        self.body.setVisible(not c)
        self.arrow.setPixmap(icon_pixmap("chev_right" if c else "chev_down", C["text-faint"], 14))

    def add(self, w):
        if isinstance(w, QWidget):
            self.body_layout.addWidget(w)
        else:
            self.body_layout.addLayout(w)
        return w


# ------------------------------------------------------------------ prompt editor
class _LineArea(QWidget):
    def __init__(self, ed):
        super().__init__(ed)
        self.ed = ed

    def sizeHint(self):
        return QSize(self.ed.line_area_width(), 0)

    def paintEvent(self, e):
        self.ed.paint_lines(e)


class _AtHighlighter(QSyntaxHighlighter):
    def highlightBlock(self, text):
        import re
        f = QTextCharFormat()
        f.setForeground(QColor("#93c5fd"))
        f.setBackground(QColor("#1f2f6a"))
        for m in re.finditer(r"@[\wÀ-ỹ]+", text):
            self.setFormat(m.start(), m.end() - m.start(), f)


class PromptEditor(QPlainTextEdit):
    """Ô nhập danh sách prompt có số dòng, tô màu @nhân_vật, kéo-thả file."""
    files_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setPlaceholderText(tr("Nhập danh sách prompt vào đây (mỗi dòng một prompt). Gõ @Tên để chèn nhân vật."))
        self.la = _LineArea(self)
        self.blockCountChanged.connect(lambda _: self.setViewportMargins(self.line_area_width(), 0, 0, 0))
        self.updateRequest.connect(self._upd)
        self.setViewportMargins(self.line_area_width(), 0, 0, 0)
        self.hl = _AtHighlighter(self.document())
        self.setAcceptDrops(True)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth)

    def line_area_width(self):
        return 14 + self.fontMetrics().horizontalAdvance("9") * max(2, len(str(self.blockCount())))

    def _upd(self, rect, dy):
        if dy:
            self.la.scroll(0, dy)
        else:
            self.la.update(0, rect.y(), self.la.width(), rect.height())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        cr = self.contentsRect()
        self.la.setGeometry(QRect(cr.left(), cr.top(), self.line_area_width(), cr.height()))

    def paint_lines(self, e):
        p = QPainter(self.la)
        p.setPen(QColor("#5d64a0"))
        block = self.firstVisibleBlock()
        n = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        shown = 0
        while block.isValid() and top <= e.rect().bottom():
            if block.isVisible() and bottom >= e.rect().top() and block.text().strip():
                shown += 1
                p.drawText(0, top, self.la.width() - 6, self.fontMetrics().height(), Qt.AlignRight, str(n + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            n += 1
        p.end()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.files_dropped.emit([u.toLocalFile() for u in e.mimeData().urls()])
        else:
            super().dropEvent(e)


# ------------------------------------------------------------------ chọn file/thư mục
class PathPicker(QWidget):
    changed = Signal(str)

    def __init__(self, path: str = "", directory: bool = True, filt: str = ""):
        super().__init__()
        self.directory = directory
        self.filt = filt
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.edit = QLineEdit(path)
        self.edit.textChanged.connect(self.changed)
        b = icon_button("folder", "Chọn thư mục" if directory else "Chọn tệp", "#67e8f9")
        b.setFixedSize(34, 34)
        b.clicked.connect(self.pick)
        h.addWidget(self.edit, 1)
        h.addWidget(b)

    def pick(self):
        if self.directory:
            p = QFileDialog.getExistingDirectory(self, tr("Chọn thư mục"), self.edit.text())
        else:
            p, _ = QFileDialog.getOpenFileName(self, tr("Chọn tệp"), self.edit.text(), self.filt)
        if p:
            self.edit.setText(p)

    def text(self) -> str:
        return self.edit.text().strip()


class FrameSlot(QLabel):
    """Ô kéo-thả / bấm để chọn ảnh (khung đầu, khung cuối, ảnh tham chiếu)."""
    changed = Signal(str)

    def __init__(self, title: str):
        super().__init__()
        self.title = tr(title)
        self.path = ""
        self.setAcceptDrops(True)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(72)
        self.setCursor(Qt.PointingHandCursor)
        self.setWordWrap(True)
        self._paint()

    def _paint(self):
        if self.path:
            pm = QPixmap(self.path)
            if not pm.isNull():
                self.setPixmap(pm.scaled(140, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.setToolTip(self.path)
        else:
            self.setPixmap(QPixmap())
            self.setText("+ " + self.title)
        self.setStyleSheet(f"QLabel{{border:1.5px dashed #33407e;border-radius:4px;color:{C['text-faint']};font-size:11px;}}"
                           f"QLabel:hover{{border-color:{C['accent']};}}")

    def set_path(self, p: str):
        self.path = p
        if not p:
            self.clear()
        self._paint()
        self.changed.emit(p)

    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self.set_path("")
            return
        p, _ = QFileDialog.getOpenFileName(self, self.title, "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
        if p:
            self.set_path(p)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            self.set_path(urls[0].toLocalFile())




# ------------------------------------------------------------------ toast
class Toast(QLabel):
    COLORS = {"info": ("info", "info-bg"), "ok": ("success", "success-bg"),
              "warn": ("warning", "warning-bg"), "error": ("danger", "danger-bg")}

    def __init__(self, parent, kind: str, text: str):
        super().__init__(text, parent)
        fg, bg = self.COLORS.get(kind, self.COLORS["info"])
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.setStyleSheet(f"background:{C[bg]};color:{C[fg]};border:1px solid {C[fg]};border-radius:5px;padding:10px 14px;font-weight:600;")
        self.adjustSize()
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(24)
        sh.setColor(QColor(0, 0, 0, 160))
        sh.setOffset(0, 6)
        self.setGraphicsEffect(sh)

    @staticmethod
    def show_msg(parent, kind: str, text: str, ms: int = 4500):
        t = Toast(parent, kind, text)
        stack = [w for w in parent.findChildren(Toast) if w is not t and w.isVisible()]
        y = parent.height() - 50 - t.height() - sum(w.height() + 8 for w in stack)
        t.move(parent.width() - t.width() - 24, max(40, y))
        t.show()
        t.raise_()
        QTimer.singleShot(ms, t.deleteLater)


class ShineButton(QAbstractButton):
    """Nút nổi bật: nền gradient sáng, vệt sáng chạy ngang và quầng sáng nhấp nháy nhẹ (dùng cho "Tạo giọng nói MIỄN PHÍ")."""

    def __init__(self, text: str, icon_name: str = "mic", colors=("#22c55e", "#06b6d4", "#a855f7"), parent=None):
        super().__init__(parent)
        self.setText(text)
        self._icon = icon_pixmap(icon_name, "#ffffff", 16)
        self._colors = [QColor(c) for c in colors]
        self._phase = 0.0
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(32)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(max(9.5, f.pointSizeF() + 0.5))
        self.setFont(f)
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setColor(QColor(34, 211, 238, 200))
        self._glow.setBlurRadius(14)
        self.setGraphicsEffect(self._glow)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def sizeHint(self):
        w = self.fontMetrics().horizontalAdvance(self.text()) + 16 + 8 + 28
        return QSize(w, 32)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _tick(self):
        if not self.isVisible():
            return
        self._phase = (self._phase + 0.012) % 1.0
        import math
        k = (math.sin(self._phase * 2 * math.pi * 2) + 1) / 2            # nhấp nháy 2 lần mỗi chu kỳ
        self._glow.setBlurRadius(10 + 16 * k)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, 6, 6)
        from PySide6.QtGui import QLinearGradient
        g = QLinearGradient(r.topLeft(), r.topRight())
        n = len(self._colors)
        for i, c in enumerate(self._colors):
            g.setColorAt(i / (n - 1), c.lighter(115) if self.underMouse() else c)
        p.fillPath(path, g)
        # vệt sáng chạy ngang (chiếm ~40% chu kỳ, phần còn lại nghỉ)
        t = self._phase / 0.4
        if t <= 1.0:
            x = r.left() - 40 + (r.width() + 80) * t
            sg = QLinearGradient(x - 30, 0, x + 30, 0)
            sg.setColorAt(0, QColor(255, 255, 255, 0))
            sg.setColorAt(0.5, QColor(255, 255, 255, 110))
            sg.setColorAt(1, QColor(255, 255, 255, 0))
            p.save()
            p.setClipPath(path)
            p.fillRect(r, sg)
            p.restore()
        p.setPen(QPen(QColor(255, 255, 255, 230 if self.underMouse() else 140), 1.2))
        p.drawPath(path)
        fm = self.fontMetrics()
        tw = fm.horizontalAdvance(self.text())
        x0 = r.center().x() - (16 + 8 + tw) / 2
        p.drawPixmap(int(x0), int(r.center().y() - 8), self._icon)
        p.setPen(QColor(0, 0, 0, 90))
        p.drawText(QRectF(x0 + 24 + 1, r.top() + 1, tw + 4, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(x0 + 24, r.top(), tw + 4, r.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        p.end()


class AIButton(QAbstractButton):
    """Nút "Quy trình tự động" – kiểu Mạch dữ liệu: khuôn nút cũ (viền vàng, bo góc), nền lưới chấm nơ-ron mờ,
    một tia sáng chạy dọc theo viền như dữ liệu đang truyền (~3 giây / vòng), quầng sáng vàng – hồng thở nhẹ,
    chữ trắng đậm + nhãn "AI" vàng. Rê chuột: sáng mạnh hơn. busy=True: chạy nhanh gấp đôi."""

    NODES = [(0.08, 0.30), (0.20, 0.78), (0.33, 0.22), (0.47, 0.70), (0.58, 0.28), (0.71, 0.80), (0.83, 0.25),
             (0.94, 0.68)]

    def __init__(self, text: str, icon_name: str = "clapper", parent=None, height: int = 32, chip: bool = True,
                 elide: bool = True, grow: float = 1.0, fixed: bool = False):
        super().__init__(parent)
        self.setText(text)
        self._icon = icon_pixmap(icon_name, "#fde68a", 15)
        self._phase = 0.0
        self.busy = False
        self._h = height
        self._chip = chip
        self._elide = elide
        self._fixed = fixed
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(height)
        f = QFont(self.font())
        f.setBold(True)
        f.setPointSizeF(max(9.5, f.pointSizeF() + grow))
        self.setFont(f)
        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setColor(QColor(245, 158, 11, 200))
        self._glow.setBlurRadius(14)
        self.setGraphicsEffect(self._glow)
        if fixed:
            self._fit()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    def _chip_w(self) -> int:
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, self.font().pointSizeF() - 3))
        from PySide6.QtGui import QFontMetrics
        return QFontMetrics(f).horizontalAdvance("AI") + 10

    def _fit(self):
        """fixed=True: rộng vừa khít nội dung (+22 px) – cùng một độ rộng ở mọi trang, chữ luôn hiện đủ."""
        self.setFixedWidth(int(self._content_w()) + 22)

    def setText(self, text):
        super().setText(text)
        if getattr(self, "_fixed", False):
            self._fit()

    def sizeHint(self):
        return QSize(int(self._content_w()) + 36, self._h)

    def _content_w(self) -> float:
        # nhãn "AI" là huy hiệu nhỏ đè lên góc phải trên viền → không chiếm chỗ của chữ
        return 15 + 7 + self.fontMetrics().horizontalAdvance(self.text())

    def minimumSizeHint(self):
        return self.sizeHint() if not self._elide else QSize(min(self.sizeHint().width(), 120), self._h)

    def _tick(self):
        if not self.isVisible():
            return
        self._phase = (self._phase + (0.022 if self.busy else 0.011)) % 1.0
        import math
        k = (math.sin(self._phase * 2 * math.pi) + 1) / 2
        hover = self.underMouse()
        if not self.isEnabled() and not self.busy:
            self._glow.setBlurRadius(4)
            self.update()
            return
        self._glow.setBlurRadius((16 if hover else 10) + (14 if hover else 9) * k)
        a = 230 if hover else 185
        # quầng sáng vàng → hồng nhẹ theo nhịp
        self._glow.setColor(QColor(int(245 - 9 * k), int(158 - 44 * k), int(11 + 171 * k * 0.6), a))
        self.update()

    def paintEvent(self, _e):
        import math
        from PySide6.QtGui import QLinearGradient, QRadialGradient
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        top = 7 if self._chip else 3
        r = QRectF(self.rect()).adjusted(3, top, -3, -3)
        path = QPainterPath()
        path.addRoundedRect(r, 7, 7)
        hover = self.underMouse()
        bg = QLinearGradient(r.topLeft(), r.bottomLeft())
        bg.setColorAt(0, QColor("#2a2210" if hover else "#221b0b"))
        bg.setColorAt(1, QColor("#15110a"))
        p.fillPath(path, bg)
        # lưới nơ-ron mờ
        p.save()
        p.setClipPath(path)
        pts = [(r.left() + x * r.width(), r.top() + y * r.height()) for x, y in self.NODES]
        p.setPen(QPen(QColor(251, 191, 36, 34), 1))
        for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
            p.drawLine(int(x1), int(y1), int(x2), int(y2))
        cols = [QColor(251, 191, 36), QColor(244, 114, 182), QColor(34, 211, 238)]
        for i, (x, y) in enumerate(pts):
            c = QColor(cols[i % 3])
            c.setAlpha(int(70 + 50 * (math.sin(self._phase * 2 * math.pi * 2 + i) + 1) / 2))
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawEllipse(QRectF(x - 1.4, y - 1.4, 2.8, 2.8))
        p.restore()
        # viền vàng
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#fbbf24" if hover else "#f59e0b"), 1.5))
        p.drawPath(path)
        # tia sáng chạy dọc viền (đuôi mờ dần)
        per = max(1.0, path.length())
        for i in range(14):
            t = (self._phase - i * 2.2 / per) % 1.0          # đuôi dài ~30 px dù nút rộng hay hẹp
            pt = path.pointAtPercent(t)
            a = int(255 * (1 - i / 14) ** 1.6)
            rad = 2.4 - i * 0.12
            g = QRadialGradient(pt, rad * 2.6)
            head = QColor(255, 255, 255, a) if i < 3 else QColor(253, 230, 138, a)
            g.setColorAt(0, head)
            g.setColorAt(0.45, QColor(244, 114, 182, int(a * 0.45)))
            g.setColorAt(1, QColor(244, 114, 182, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(pt, rad * 2.6, rad * 2.6)
        # icon + chữ + nhãn AI (căn giữa khi nút rộng)
        x = max(r.left() + (5 if self._fixed else 11), r.center().x() - self._content_w() / 2)
        cy = r.center().y()
        p.drawPixmap(int(x), int(cy - self._icon.height() / (2 * self._icon.devicePixelRatio())), self._icon)
        x += 15 + 7
        fm = self.fontMetrics()
        room = r.right() - (2 if self._fixed else 8) - x
        text = self.text() if not self._elide else fm.elidedText(self.text(), Qt.ElideRight, int(max(20, room)))
        tw = fm.horizontalAdvance(text)
        ty = cy + (fm.ascent() - fm.descent()) / 2
        p.setFont(self.font())
        p.setPen(QColor(0, 0, 0, 200))
        p.drawText(int(x), int(ty + 1), text)
        p.setPen(QColor("#ffffff") if self.isEnabled() or self.busy else QColor("#b8b0a0"))
        p.drawText(int(x), int(ty), text)
        if not self._chip:
            p.end()
            return
        cw = self._chip_w()
        chip = QRectF(r.right() - cw - 6, 0.5, cw, 13)
        cg = QLinearGradient(chip.topLeft(), chip.topRight())
        cg.setColorAt(0, QColor("#fde68a"))
        cg.setColorAt(1, QColor("#fbbf24"))
        cp = QPainterPath()
        cp.addRoundedRect(chip, 4, 4)
        p.fillPath(cp, cg)
        cf = QFont(self.font())
        cf.setPointSizeF(max(6.5, self.font().pointSizeF() - 3.5))
        cf.setWeight(QFont.Black)
        p.setFont(cf)
        p.setPen(QColor("#1d1a10"))
        p.drawText(chip, Qt.AlignCenter, "AI")
        p.end()


class AIWorking(QWidget):
    """Hiệu ứng "AI Agent đang làm việc" (không chữ): mạng nơ-ron với xung dữ liệu chạy dọc các nhánh, lõi sáng
    nhịp thở có 2 vòng quỹ đạo xoay ngược nhau, sóng quét ngang và các hàng "prompt" đang được dệt dần."""

    STYLES = ("neural", "scan", "orb")

    def __init__(self, parent=None, style: str = "scan"):
        super().__init__(parent)
        import random
        rnd = random.Random(7)
        self.style = style if style in self.STYLES else "scan"
        self.rain = [(rnd.random(), rnd.uniform(0.15, 0.5), rnd.uniform(8, 30)) for _ in range(46)]
        self._t = 0.0
        self.nodes = [(rnd.uniform(0.06, 0.94), rnd.uniform(0.08, 0.92)) for _ in range(34)]
        self.edges = []
        for i, (x, y) in enumerate(self.nodes):
            near = sorted(range(len(self.nodes)), key=lambda j: (self.nodes[j][0] - x) ** 2 + (self.nodes[j][1] - y) ** 2)
            for j in near[1:3]:
                if (j, i) not in self.edges:
                    self.edges.append((i, j))
        self.pulses = [(rnd.randrange(len(self.edges)), rnd.random(), rnd.uniform(0.35, 0.8)) for _ in range(22)]
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, e):
        self._timer.start(33)
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _tick(self):
        self._t += 0.033
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#070b24"))
        getattr(self, "_paint_" + self.style)(p, self.width(), self.height(), self._t)
        p.end()

    # ---- B: quét dữ liệu – mưa dữ liệu + các thẻ prompt "khung xương" lấp lánh + tia laser quét dọc
    def _paint_scan(self, p, w, h, t):
        import math
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QLinearGradient, QPen
        for x, sp, ln in self.rain:                      # mưa dữ liệu
            y = ((t * sp + x * 3.1) % 1.2) * h - ln * 4
            g = QLinearGradient(QPointF(0, y), QPointF(0, y + ln * 4))
            g.setColorAt(0, QColor(34, 211, 238, 0))
            g.setColorAt(1, QColor(34, 211, 238, 120))
            p.setPen(QPen(g, 1.6))
            p.drawLine(QPointF(x * w, y), QPointF(x * w, y + ln * 4))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(165, 243, 252, 200))
            p.drawEllipse(QPointF(x * w, y + ln * 4), 1.6, 1.6)
        cw, x0 = w * 0.8, w * 0.1
        n = 5
        top = h * 0.1
        ch = (h * 0.8 - (n - 1) * 14) / n
        laser = top + ((t * 0.28) % 1.0) * (n * (ch + 14))
        for i in range(n):                               # thẻ prompt khung xương
            y = top + i * (ch + 14)
            r = QRectF(x0, y, cw, ch)
            lit = abs((y + ch / 2) - laser) < ch
            p.setPen(QPen(QColor(99, 102, 241, 200 if lit else 70), 1.2))
            p.setBrush(QColor(16, 24, 72, 220))
            p.drawRoundedRect(r, 10, 10)
            p.setPen(Qt.NoPen)
            for k, fw in enumerate((0.35, 0.9, 0.75)):
                bar = QRectF(x0 + 16, y + 14 + k * (ch - 28) / 2.4, (cw - 32) * fw, 7 if k else 9)
                sh = QLinearGradient(QPointF(x0 + ((t * 0.6 + i * 0.15) % 1.6 - 0.3) * cw, 0),
                                     QPointF(x0 + ((t * 0.6 + i * 0.15) % 1.6 - 0.1) * cw, 0))
                sh.setColorAt(0, QColor(42, 61, 143, 150))
                sh.setColorAt(0.5, QColor(167, 139, 250, 230) if lit else QColor(99, 102, 241, 170))
                sh.setColorAt(1, QColor(42, 61, 143, 150))
                p.setBrush(sh)
                p.drawRoundedRect(bar, 4, 4)
        g = QLinearGradient(QPointF(0, laser - 26), QPointF(0, laser + 2))       # tia laser
        g.setColorAt(0, QColor(217, 70, 239, 0))
        g.setColorAt(1, QColor(217, 70, 239, 90))
        p.fillRect(QRectF(0, laser - 26, w, 28), g)
        lg = QLinearGradient(QPointF(0, 0), QPointF(w, 0))
        lg.setColorAt(0, QColor(34, 211, 238, 0))
        lg.setColorAt(0.5, QColor("#f0abfc"))
        lg.setColorAt(1, QColor(34, 211, 238, 0))
        p.setPen(QPen(lg, 2))
        p.drawLine(QPointF(0, laser), QPointF(w, laser))

    # ---- C: lõi năng lượng – khối sáng biến hình nhiều lớp màu, sóng lan tỏa và hạt bay quanh
    def _paint_orb(self, p, w, h, t):
        import math
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPainterPath, QPen, QRadialGradient
        c = QPointF(w / 2, h / 2)
        R = min(w, h) * 0.2
        for k in range(4):                               # sóng lan tỏa
            q = (t * 0.35 + k / 4) % 1.0
            cc = QColor(99, 102, 241, int(120 * (1 - q)))
            p.setPen(QPen(cc, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, R * (1 + 1.6 * q), R * (1 + 1.6 * q))
        for layer, (col, amp, spd, ph) in enumerate((("#22d3ee", 0.16, 1.1, 0.0), ("#a855f7", 0.2, -0.8, 1.3),
                                                     ("#ec4899", 0.13, 1.5, 2.1))):
            path = QPainterPath()                        # khối sáng biến hình
            for i in range(73):
                a = i / 72 * 2 * math.pi
                rr = R * (1 + amp * math.sin(3 * a + t * spd * 2 + ph) * math.cos(2 * a - t * spd + ph))
                pt = QPointF(c.x() + rr * math.cos(a), c.y() + rr * math.sin(a))
                path.moveTo(pt) if i == 0 else path.lineTo(pt)
            g = QRadialGradient(c, R * 1.3)
            cc = QColor(col)
            cc.setAlpha(150)
            g.setColorAt(0, QColor(255, 255, 255, 200))
            g.setColorAt(0.5, cc)
            cc2 = QColor(col)
            cc2.setAlpha(0)
            g.setColorAt(1, cc2)
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawPath(path)
        for i in range(26):                              # hạt bay quanh
            a = i * 0.83 + t * (0.6 + (i % 5) * 0.15) * (1 if i % 2 else -1)
            rr = R * (1.55 + 0.45 * math.sin(t * 1.3 + i))
            pt = QPointF(c.x() + rr * math.cos(a), c.y() + rr * 0.8 * math.sin(a))
            cc = QColor("#67e8f9" if i % 3 else "#f0abfc")
            cc.setAlpha(int(140 + 110 * math.sin(t * 3 + i) ** 2))
            p.setBrush(cc)
            p.drawEllipse(pt, 2.2, 2.2)

    # ---- A: mạng nơ-ron
    def _paint_neural(self, p, w, h, t):
        import math
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QConicalGradient, QLinearGradient, QPen, QRadialGradient
        pt = [QPointF(x * w, y * h) for x, y in self.nodes]
        # nhánh nơ-ron
        for a, b in self.edges:
            c = QColor(99, 102, 241, 55)
            p.setPen(QPen(c, 1))
            p.drawLine(pt[a], pt[b])
        # xung dữ liệu chạy dọc nhánh
        cols = ("#22d3ee", "#a78bfa", "#f0abfc")
        for k, (e, off, sp) in enumerate(self.pulses):
            a, b = self.edges[e]
            q = (off + t * sp) % 1.0
            for j in range(5):
                qq = max(0.0, q - j * 0.035)
                x = pt[a].x() + (pt[b].x() - pt[a].x()) * qq
                y = pt[a].y() + (pt[b].y() - pt[a].y()) * qq
                cc = QColor(cols[k % 3])
                cc.setAlpha(int(230 * (1 - j / 5)))
                p.setPen(Qt.NoPen)
                p.setBrush(cc)
                p.drawEllipse(QPointF(x, y), 2.4 - j * 0.35, 2.4 - j * 0.35)
        # nút mạng nhấp nháy
        for i, q in enumerate(pt):
            a_ = 0.35 + 0.65 * max(0.0, math.sin(t * 2.2 + i * 1.7))
            cc = QColor("#67e8f9" if i % 3 else "#c4b5fd")
            cc.setAlpha(int(200 * a_))
            p.setBrush(cc)
            p.drawEllipse(q, 2.2 + 1.2 * a_, 2.2 + 1.2 * a_)
        # sóng quét ngang
        sx = (t * 0.35 % 1.0) * (w + 240) - 120
        g = QLinearGradient(QPointF(sx - 120, 0), QPointF(sx + 120, 0))
        g.setColorAt(0, QColor(34, 211, 238, 0))
        g.setColorAt(0.5, QColor(34, 211, 238, 38))
        g.setColorAt(1, QColor(34, 211, 238, 0))
        p.fillRect(self.rect(), g)
        # lõi AI ở giữa: quầng sáng thở + 2 vòng quỹ đạo
        c = QPointF(w / 2, h * 0.42)
        r = min(w, h) * 0.11
        br = 0.5 + 0.5 * math.sin(t * 2.6)
        halo = QRadialGradient(c, r * 2.4)
        halo.setColorAt(0, QColor(167, 139, 250, int(150 + 80 * br)))
        halo.setColorAt(0.45, QColor(99, 102, 241, 70))
        halo.setColorAt(1, QColor(7, 11, 36, 0))
        p.setBrush(halo)
        p.drawEllipse(c, r * 2.4, r * 2.4)
        for k, (rad, spd, wd) in enumerate(((r * 1.35, 90, 2.6), (r * 1.75, -60, 1.8))):
            ring = QConicalGradient(c, t * spd)
            ring.setColorAt(0, QColor("#22d3ee"))
            ring.setColorAt(0.35, QColor(34, 211, 238, 0))
            ring.setColorAt(0.5, QColor("#d946ef"))
            ring.setColorAt(0.85, QColor(217, 70, 239, 0))
            ring.setColorAt(1, QColor("#22d3ee"))
            p.setPen(QPen(ring, wd))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(c, rad, rad * (0.92 if k else 1.0))
        core = QRadialGradient(c, r * (0.75 + 0.08 * br))
        core.setColorAt(0, QColor("#ffffff"))
        core.setColorAt(0.35, QColor("#a5f3fc"))
        core.setColorAt(1, QColor(99, 102, 241, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(core)
        p.drawEllipse(c, r * 0.8, r * 0.8)
        # các hàng "prompt" đang được dệt dần (thanh sáng, không chữ)
        top = h * 0.68
        for i in range(4):
            y = top + i * 22
            full = w * (0.62 - 0.08 * (i % 2))
            x0 = (w - full) / 2
            prog = (t * 0.45 - i * 0.22) % 1.4
            ln = max(0.0, min(1.0, prog)) * full
            p.setBrush(QColor(42, 61, 143, 110))
            p.drawRoundedRect(QRectF(x0, y, full, 8), 4, 4)
            if ln > 2:
                gg = QLinearGradient(QPointF(x0, 0), QPointF(x0 + full, 0))
                gg.setColorAt(0, QColor("#22d3ee"))
                gg.setColorAt(0.5, QColor("#6366f1"))
                gg.setColorAt(1, QColor("#d946ef"))
                p.setBrush(gg)
                p.drawRoundedRect(QRectF(x0, y, ln, 8), 4, 4)
                p.setBrush(QColor(255, 255, 255, 220))
                p.drawEllipse(QPointF(x0 + ln, y + 4), 3.2, 3.2)


class FreeNote(QFrame):
    """Dải báo giới hạn gói Miễn phí + nút "Nâng cấp PRO" (mở hộp kích hoạt bản quyền)."""

    def __init__(self, text: str, on_upgrade, parent=None):
        super().__init__(parent)
        self.setObjectName("freeNote")
        self.setStyleSheet("QFrame#freeNote{background:#2e2410;border:1px solid #5a4416;border-radius:6px;}")
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 5, 6, 5)
        h.setSpacing(8)
        ic = QLabel("🔒")
        ic.setStyleSheet("background:transparent;border:none;font-size:13px;")
        h.addWidget(ic)
        self.lbl = QLabel(tr(text))
        self.lbl.setWordWrap(True)
        self.lbl.setStyleSheet("background:transparent;border:none;color:#fbbf24;font-size:12px;font-weight:600;")
        h.addWidget(self.lbl, 1)
        self.btn = QPushButton(tr("Nâng cấp PRO"))
        self.btn.setCursor(Qt.PointingHandCursor)
        self.btn.setFixedHeight(26)
        self.btn.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #f59e0b,stop:1 #f97316);"
                               "color:#1a1206;border:none;border-radius:5px;padding:0 10px;font-weight:800;font-size:12px;}"
                               "QPushButton:hover{background:#fbbf24;}")
        self.btn.clicked.connect(lambda *_: on_upgrade())
        h.addWidget(self.btn)

    def setText(self, t: str):
        self.lbl.setText(t)
