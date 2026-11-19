"""Cửa sổ Thông tin bản quyền (EULA)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout

from .theme import C
from ..core.eula import EULA_DATE, EULA_HTML, EULA_VERSION, OWNER, PRODUCT
from ..core.paths import APP_VERSION, assets_dir


class EulaDialog(QDialog):
    def __init__(self, parent=None, first_run: bool = False):
        super().__init__(parent)
        self.first_run = first_run
        self.setWindowTitle(f"Thông tin bản quyền · {PRODUCT}")
        self.resize(820, 680)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 18, 22, 16)
        v.setSpacing(10)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(assets_dir() / "logo.png")).scaled(54, 54, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(logo)
        tv = QVBoxLayout()
        t = QLabel(f"{PRODUCT}")
        t.setStyleSheet("font-size:19px;font-weight:800;")
        sub = QLabel(f"Phiên bản {APP_VERSION} · © 2026 {OWNER} · Bảo lưu mọi quyền")
        sub.setObjectName("muted")
        tv.addWidget(t)
        tv.addWidget(sub)
        head.addLayout(tv, 1)
        lic = QLabel("PHẦN MỀM THƯƠNG MẠI\nNGHIÊM CẤM SAO CHÉP")
        lic.setAlignment(Qt.AlignCenter)
        lic.setStyleSheet(f"color:{C['danger']};border:1.5px solid {C['danger']};border-radius:5px;padding:6px 10px;"
                          "font-weight:800;font-size:11px;")
        head.addWidget(lic)
        v.addLayout(head)

        self.text = QTextBrowser()
        self.text.setOpenExternalLinks(True)
        self.text.document().setDefaultStyleSheet(
            "h2{color:#67e8f9;} h3{color:#c4b5fd;margin-top:14px;margin-bottom:4px;} p,li{line-height:150%;} b{color:#ffffff;}")
        self.text.setHtml(EULA_HTML)
        self.text.setStyleSheet(f"QTextBrowser{{background:{C['surface']};border:1px solid {C['border']};border-radius:6px;"
                                "padding:14px 18px;font-size:13px;color:#dbe2ff;}")
        v.addWidget(self.text, 1)

        foot = QHBoxLayout()
        info = QLabel(f"Thỏa thuận phiên bản {EULA_VERSION} · {EULA_DATE}")
        info.setObjectName("faint")
        foot.addWidget(info)
        foot.addStretch()
        if first_run:
            self.agree = QCheckBox("Tôi đã đọc kỹ và đồng ý toàn bộ Thỏa thuận")
            self.agree.setEnabled(False)
            self.agree.toggled.connect(lambda on: self.b_ok.setEnabled(on))
            foot.addWidget(self.agree)
            b_no = QPushButton("Không đồng ý · Thoát")
            b_no.clicked.connect(self.reject)
            self.b_ok = QPushButton("Đồng ý & tiếp tục")
            self.b_ok.setProperty("kind", "primary")
            self.b_ok.setEnabled(False)
            self.b_ok.clicked.connect(self.accept)
            foot.addWidget(b_no)
            foot.addWidget(self.b_ok)
            self.hint = QLabel("Cuộn xuống cuối để đọc hết thỏa thuận")
            self.hint.setObjectName("faint")
            v.addWidget(self.hint)
            sb = self.text.verticalScrollBar()
            sb.valueChanged.connect(self._scrolled)
            sb.rangeChanged.connect(lambda *_: self._scrolled())
        else:
            b = QPushButton("Đóng")
            b.setProperty("kind", "primary")
            b.clicked.connect(self.accept)
            foot.addWidget(b)
        v.addLayout(foot)

    def _scrolled(self, *_):
        sb = self.text.verticalScrollBar()
        if sb.maximum() == 0 or sb.value() >= sb.maximum() - 8:
            self.agree.setEnabled(True)
            self.hint.setText("")
