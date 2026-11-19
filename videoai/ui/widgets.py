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
