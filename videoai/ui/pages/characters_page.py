"""Nhân Vật: thư viện nhân vật dùng lại trong prompt bằng @Tên."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QVBoxLayout, QWidget)

from ..widgets import Card, button, field, label
from ...core.i18n import tr


class CharactersPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.chars = ctx.characters
        self.cur: dict | None = None
        self.images: list[str] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        head = QHBoxLayout()
        head.addWidget(label("Nhân vật", "h1"))
        head.addStretch()
        b_new = button("Nhân vật mới", "primary", "plus")
        b_new.clicked.connect(self.new)
        head.addWidget(b_new)
        root.addLayout(head)
        hint = label("Tạo nhân vật một lần, rồi gõ @Tên trong prompt ở bất kỳ trang nào. Ứng dụng sẽ chèn mô tả "
                     "và gửi kèm ảnh nhân vật làm tham chiếu để giữ nhân vật nhất quán giữa các cảnh.", "muted")
        hint.setWordWrap(True)
        root.addWidget(hint)
        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)
        self.list = QListWidget()
        self.list.setFixedWidth(300)
        self.list.setIconSize(QSize(48, 48))
        self.list.currentRowChanged.connect(self._pick)
        body.addWidget(self.list)
        card = Card("Thông tin nhân vật", "users", icon_color="#f9a8d4")
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("Tên không dấu cách, vd: Minh, CoGaiAoDai"))
        self.desc = QPlainTextEdit()
        self.desc.setPlaceholderText(tr("Mô tả ngoại hình cố định: tuổi, tóc, khuôn mặt, trang phục, phong cách…"))
        self.desc.setFixedHeight(130)
        self.imgs = QListWidget()
        self.imgs.setViewMode(QListWidget.IconMode)
        self.imgs.setIconSize(QSize(110, 110))
        self.imgs.setFixedHeight(150)
        card.add(field("Tên (dùng @Tên trong prompt)", self.name))
        card.add(field("Mô tả", self.desc))
        card.add(field("Ảnh tham chiếu (1–3 ảnh rõ mặt)", self.imgs))
        r = QHBoxLayout()
        b_img = button("Thêm ảnh", "chip", "plus", "#67e8f9")
        b_img.clicked.connect(self.add_img)
        b_rm = button("Bỏ ảnh đã chọn", "chip", "x", "#fb7185")
        b_rm.clicked.connect(self.rm_img)
        r.addWidget(b_img)
        r.addWidget(b_rm)
        r.addStretch()
        card.add(r)
        r2 = QHBoxLayout()
        b_save = button("Lưu nhân vật", "primary", "save")
        b_save.clicked.connect(self.save)
        b_del = button("Xóa", "stop", "trash", "#fb7185")
        b_del.clicked.connect(self.delete)
        r2.addWidget(b_save)
        r2.addWidget(b_del)
        r2.addStretch()
        card.add(r2)
        card.body_layout.addStretch()
        body.addWidget(card, 1)
        self.reload()

    def reload(self):
        self.data = self.chars.all()
        self.list.clear()
        for c in self.data:
            ic = QIcon(QPixmap(c["images"][0])) if c["images"] else QIcon()
            it = QListWidgetItem(ic, f"@{c['name']}")
            self.list.addItem(it)
        if not self.data:
            self.new()

    def _pick(self, i):
        if 0 <= i < len(self.data):
            self.cur = self.data[i]
            self.name.setText(self.cur["name"])
            self.desc.setPlainText(self.cur["description"])
            self.images = list(self.cur["images"])
            self._imgs()

    def _imgs(self):
        self.imgs.clear()
        for p in self.images:
            it = QListWidgetItem(QIcon(QPixmap(p)), Path(p).name[:14])
            it.setToolTip(p)
            self.imgs.addItem(it)

    def new(self):
        self.cur = None
        self.name.clear()
        self.desc.clear()
        self.images = []
        self._imgs()
        self.list.clearSelection()
        self.name.setFocus()

    def add_img(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr("Chọn ảnh"), "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
        self.images += [f for f in fs if f not in self.images]
        self._imgs()

    def rm_img(self):
        for it in self.imgs.selectedItems():
            self.images.remove(it.toolTip())
        self._imgs()

    def save(self):
        n = self.name.text().strip().replace(" ", "")
        if not n:
            self.ctx.toast("warn", tr("Nhập tên nhân vật."))
            return
        try:
            self.chars.save(n, self.desc.toPlainText().strip(), self.images, self.cur["id"] if self.cur else None)
        except Exception:
            self.ctx.toast("error", tr("Tên này đã có. Chọn tên khác."))
            return
        self.ctx.toast("ok", tr("Đã lưu") + f" @{n}")
        self.reload()

    def delete(self):
        if self.cur and QMessageBox.question(self, tr("Xóa"), tr("Xóa nhân vật") + f" @{self.cur['name']}?") == QMessageBox.Yes:
            self.chars.delete(self.cur["id"])
            self.reload()
