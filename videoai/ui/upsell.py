"""Hộp mời nâng cấp PRO: ngắn gọn – 1 dòng lý do, 3 lợi ích, nút nâng cấp nổi bật."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from .theme import icon_pixmap
from .widgets import ShineButton
from ..core.i18n import tr

BENEFITS = ("Chạy hàng loạt – không giới hạn số prompt",
            "Chạy song song nhiều tài khoản – nhanh gấp nhiều lần",
            "AI Agent viết kịch bản nhiều cảnh, sửa hàng loạt prompt")


class UpsellDialog(QDialog):
    def __init__(self, parent, reason: str, detail: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Nâng cấp PRO"))
        self.setModal(True)
        self.setFixedWidth(470)
        self.upgrade = False
        self.setStyleSheet("QDialog{background:#0b1035;} QLabel{background:transparent;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        bar = QFrame()                                   # dải màu trên cùng
        bar.setFixedHeight(5)
        bar.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #f59e0b,stop:0.5 #ec4899,stop:1 #8b5cf6);")
        v.addWidget(bar)
        body = QVBoxLayout()
        body.setContentsMargins(26, 22, 26, 20)
        body.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        ic = QLabel()
        ic.setFixedSize(46, 46)
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(icon_pixmap("shield", "#ffffff", 24))
        ic.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #f59e0b,stop:1 #db2777);border-radius:23px;")
        head.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(2)
        t1 = QLabel(tr("Mở khóa đầy đủ với gói PRO"))
        t1.setStyleSheet("color:#ffffff;font-size:17px;font-weight:800;")
        t2 = QLabel(reason)
        t2.setWordWrap(True)
        t2.setStyleSheet("color:#fbbf24;font-size:12.5px;font-weight:700;")
        tv.addWidget(t1)
        tv.addWidget(t2)
        head.addLayout(tv, 1)
        body.addLayout(head)
        if detail:
            d = QLabel(detail)
            d.setWordWrap(True)
            d.setStyleSheet("color:#a5b4fc;font-size:12px;")
            body.addWidget(d)
        box = QFrame()
        box.setStyleSheet("QFrame{background:#121a4d;border:1px solid #26357f;border-radius:10px;}")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(14, 12, 14, 12)
        bv.setSpacing(8)
        for b in BENEFITS:
            row = QHBoxLayout()
            row.setSpacing(8)
            ck = QLabel()
            ck.setPixmap(icon_pixmap("check", "#4ade80", 16))
            ck.setStyleSheet("border:none;")
            tx = QLabel(tr(b))
            tx.setStyleSheet("color:#e0e7ff;font-size:12.5px;border:none;")
            row.addWidget(ck)
            row.addWidget(tx, 1)
            bv.addLayout(row)
        body.addWidget(box)
        self.b_up = ShineButton(tr("Nâng cấp PRO ngay"), "shield", ("#f59e0b", "#ec4899", "#8b5cf6"))
        self.b_up.setFixedHeight(46)
        f = self.b_up.font()
        f.setPointSizeF(f.pointSizeF() + 2)
        self.b_up.setFont(f)
        self.b_up.clicked.connect(self._go)
        body.addWidget(self.b_up)
        self.b_later = QPushButton(tr("Để sau"))
        self.b_later.setCursor(Qt.PointingHandCursor)
        self.b_later.setFlat(True)
        self.b_later.setStyleSheet("QPushButton{color:#7f8bc4;border:none;background:transparent;font-size:12px;}"
                                   "QPushButton:hover{color:#c7d2fe;text-decoration:underline;}")
        self.b_later.clicked.connect(self.reject)
        body.addWidget(self.b_later, 0, Qt.AlignHCenter)
        v.addLayout(body)
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(30)
        sh.setColor(QColor(0, 0, 0, 160))

    def _go(self):
        self.upgrade = True
        self.accept()
