"""Giao diện kho ảnh tham chiếu: lưới ảnh dùng chung, hộp chọn ảnh, trang Kho ảnh tham chiếu."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
                               QStyledItemDelegate, QStyle, QVBoxLayout, QWidget)

from .theme import C, icon, icon_pixmap
from .widgets import Card, button, field, label
from ..core.i18n import tr
from ..services.refs import GROUPS, IMG_EXT

_PIX: dict[tuple[str, int], QPixmap] = {}


def thumb(path: str, size: int) -> QPixmap:
    k = (path, size)
    if k not in _PIX:
        pm = QPixmap(path)
        if pm.isNull():
            pm = QPixmap(size, size)
            pm.fill(QColor(C["surface-2"]))
        else:
            pm = pm.scaled(size * 2, size * 2, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        _PIX[k] = pm
    return _PIX[k]


def cover_rect(pm: QPixmap, w: int, h: int):
    """Vùng giữa của ảnh có cùng tỷ lệ với ô cần vẽ (kiểu object-fit: cover)."""
    from PySide6.QtCore import QRectF
    sw, sh = pm.width(), pm.width() * h / max(1, w)
    if sh > pm.height():
        sh = pm.height()
        sw = sh * w / max(1, h)
    return QRectF((pm.width() - sw) / 2, (pm.height() - sh) / 2, sw, sh)


class _RefDelegate(QStyledItemDelegate):
    """Ô ảnh: ảnh bo góc, nhãn @Tên, nhóm, ô tick ở góc."""

    def __init__(self, parent, tile: int, show_meta: bool):
        super().__init__(parent)
        self.tile = tile
        self.meta = show_meta

    def sizeHint(self, opt, idx):
        return QSize(self.tile + 12, self.tile + (52 if self.meta else 12))

    def editorEvent(self, event, model, opt, idx):
        return False   # ô tick được đổi qua RefGrid.itemClicked (tránh Qt tự đổi thêm lần nữa)

    def paint(self, p: QPainter, opt, idx):
        r = idx.data(Qt.UserRole + 1)
        if not r:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        from PySide6.QtCore import QRectF
        rect = QRectF(opt.rect).adjusted(6, 6, -6, -6)
        cs = idx.data(Qt.CheckStateRole)
        checked = cs is not None and Qt.CheckState(cs) == Qt.Checked
        selected = bool(opt.state & QStyle.State_Selected)
        img = rect.adjusted(0, 0, 0, -(40 if self.meta else 0))
        path = QPainterPath()
        path.addRoundedRect(img, 5, 5)
        p.setClipPath(path)
        pm = thumb(r["path"], self.tile)
        p.drawPixmap(img, pm, cover_rect(pm, img.width(), img.height()))
        p.setClipping(False)
        if checked or selected:
            p.setPen(QColor(C["accent"]))
            pen = p.pen()
            pen.setWidth(3)
            p.setPen(pen)
            p.drawPath(path)
        # nhãn @Tên trên ảnh
        f = QFont(opt.font)
        f.setBold(True)
        f.setPointSizeF(8.4)
        p.setFont(f)
        t = "@" + r["name"]
        w = min(img.width() - 12, p.fontMetrics().horizontalAdvance(t) + 12)
        lab = img.adjusted(6, img.height() - 26, 0, -6)
        lab.setWidth(w)
        lp = QPainterPath()
        lp.addRoundedRect(lab, 3, 3)
        p.fillPath(lp, QColor(5, 8, 32, 210))
        p.setPen(QColor("#93c5fd"))
        p.drawText(lab, Qt.AlignCenter, p.fontMetrics().elidedText(t, Qt.ElideRight, w - 8))
        # ô tick
        if idx.flags() & Qt.ItemIsUserCheckable:
            cb = img.adjusted(img.width() - 26, 6, -6, -(img.height() - 26))
            cp = QPainterPath()
            cp.addRoundedRect(cb, 5, 5)
            p.fillPath(cp, QColor(C["accent-2"]) if checked else QColor(11, 16, 48, 200))
            p.setPen(QColor(C["accent"] if checked else "#5b51c9"))
            p.drawPath(cp)
            if checked:
                p.drawPixmap(int(cb.x() + 2), int(cb.y() + 2), icon_pixmap("check2", "#ffffff", 16))
        if self.meta:
            f.setPointSizeF(8.2)
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(C["text-faint"]))
            info = rect.adjusted(2, rect.height() - 36, -2, 0)
            p.drawText(info, Qt.AlignLeft | Qt.AlignTop, r["grp"])
            p.setPen(QColor(C["text-muted"]))
            d = r["description"] or tr("(chưa có mô tả)")
            p.drawText(info.adjusted(0, 16, 0, 0), Qt.AlignLeft | Qt.AlignTop,
                       p.fontMetrics().elidedText(d, Qt.ElideRight, info.width()))
        p.restore()


class RefGrid(QListWidget):
    """Lưới ảnh tham chiếu, có thể tick chọn nhiều; kéo-thả ảnh từ máy vào để thêm."""
    files_dropped = Signal(list)

    def __init__(self, lib, tile: int = 150, checkable: bool = True, meta: bool = True):
        super().__init__()
        self.lib = lib
        self.checkable = checkable
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSpacing(4)
        self.setUniformItemSizes(True)
        self.setItemDelegate(_RefDelegate(self, tile, meta))
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)
        self.setStyleSheet("QListWidget{background:transparent;border:none;}")
        self.itemClicked.connect(self._toggle_on_click)
        self._last_checked: set[str] = set()

    def load(self, rows: list[dict], checked: set[str] | None = None):
        checked = checked if checked is not None else self.checked_ids_set()
        self.clear()
        for r in rows:
            it = QListWidgetItem()
            it.setData(Qt.UserRole, r["id"])
            it.setData(Qt.UserRole + 1, r)
            it.setToolTip(f"@{r['name']} · {r['grp']}\n{r['description']}")
            if self.checkable:
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if r["id"] in checked else Qt.Unchecked)
            self.addItem(it)

    def _toggle_on_click(self, it):
        if self.checkable:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def checked_ids(self) -> list[str]:
        return [self.item(i).data(Qt.UserRole) for i in range(self.count())
                if self.item(i).checkState() == Qt.Checked]

    def checked_ids_set(self) -> set[str]:
        return set(self.checked_ids()) if self.count() else set()

    def set_all(self, on: bool):
        for i in range(self.count()):
            self.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        fs = [u.toLocalFile() for u in e.mimeData().urls() if Path(u.toLocalFile()).suffix.lower() in IMG_EXT]
        if fs:
            self.files_dropped.emit(fs)


class _GroupChips(QWidget):
    changed = Signal(object)

    def __init__(self, lib):
        super().__init__()
        self.lib = lib
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(0, 0, 0, 0)
        self.h.setSpacing(6)
        self.group = QButtonGroup(self)
        self.current = None
        self.reload()

    def reload(self):
        for b in self.group.buttons():
            self.group.removeButton(b)
            b.deleteLater()
        total = len(self.lib.all())
        items = [(None, f"{tr('Tất cả')} {total}")] + [(g, f"{tr(g)} {n}") for g, n in self.lib.groups() if n]
        for g, text in items:
            b = QPushButton(text)
            b.setProperty("kind", "chip")
            b.setCheckable(True)
            b.setChecked(g == self.current)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, g=g: self._pick(g))
            self.group.addButton(b)
            self.h.addWidget(b)

    def _pick(self, g):
        self.current = g
        self.changed.emit(g)


class ImportRefsDialog(QDialog):
    """Khi nhập ảnh vào kho: hiện từng ảnh để người dùng đặt tên (@Tên), chọn nhóm, ghi mô tả trước khi lưu."""

    def __init__(self, parent, lib, files: list[str], grp: str = "Nhân vật"):
        super().__init__(parent)
        from PySide6.QtWidgets import QGridLayout, QScrollArea
        from ..services.refs import suggest_name
        self.lib = lib
        self.files = files
        self.setWindowTitle(tr("Đặt tên ảnh tham chiếu"))
        self.resize(760, min(720, 170 + 96 * len(files)))
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.addWidget(label("Đặt tên cho ảnh trước khi thêm vào kho", "h1"))
        v.addWidget(label("Tên dùng để gọi trong prompt: gõ @Tên. Mô tả (nếu có) sẽ tự chèn vào prompt.", "muted"))
        allg = QHBoxLayout()
        allg.addWidget(label("Nhóm cho tất cả:", "muted"))
        self.g_all = QComboBox()
        self.g_all.setEditable(True)
        self.g_all.addItems([tr(g) for g in GROUPS])
        self.g_all.setCurrentText(tr(grp))
        allg.addWidget(self.g_all)
        allg.addStretch()
        v.addLayout(allg)
        box = QWidget()
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.rows = []
        for i, f in enumerate(files):
            th = QLabel()
            th.setFixedSize(84, 84)
            pm = QPixmap(f)
            if not pm.isNull():
                th.setPixmap(pm.scaled(84, 84, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation).copy(0, 0, 84, 84))
            th.setStyleSheet(f"border:1px solid {C['border']};border-radius:4px;")
            name = QLineEdit(suggest_name(f))
            name.setPlaceholderText(tr("Tên (vd: Minh)"))
            desc = QLineEdit()
            desc.setPlaceholderText(tr("Mô tả (tùy chọn): tuổi, tóc, trang phục…"))
            fn = label(Path(f).name, "faint")
            col = QVBoxLayout()
            col.addWidget(name)
            col.addWidget(desc)
            col.addWidget(fn)
            w = QWidget()
            w.setLayout(col)
            grid.addWidget(th, i, 0)
            grid.addWidget(w, i, 1)
            self.rows.append((f, name, desc))
        grid.setColumnStretch(1, 1)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(box)
        v.addWidget(sc, 1)
        bot = QHBoxLayout()
        bot.addStretch()
        b_c = button("Hủy")
        b_c.clicked.connect(self.reject)
        b_ok = button("Thêm vào kho", "primary", "check2")
        b_ok.clicked.connect(self.accept)
        bot.addWidget(b_c)
        bot.addWidget(b_ok)
        v.addLayout(bot)
        if self.rows:
            self.rows[0][1].setFocus()
            self.rows[0][1].selectAll()

    def save(self) -> list[str]:
        g = self.g_all.currentText().strip() or "Khác"
        return [self.lib.add(f, n.text().strip() or None, g, d.text().strip()) for f, n, d in self.rows]


def import_with_names(parent, lib, files: list[str], grp: str = "Nhân vật") -> list[str]:
    """Hiện hộp đặt tên rồi thêm ảnh vào kho. Trả về id các ảnh đã thêm (rỗng nếu hủy)."""
    files = [f for f in files if Path(f).suffix.lower() in IMG_EXT]
    if not files:
        return []
    d = ImportRefsDialog(parent, lib, files, grp)
    return d.save() if d.exec() else []


def add_images_dialog(parent, lib, grp: str = "Nhân vật") -> int:
    fs, _ = QFileDialog.getOpenFileNames(parent, tr("Thêm ảnh vào kho"), "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
    return len(import_with_names(parent, lib, fs, grp)) if fs else 0


class RefPickerDialog(QDialog):
    """Hộp chọn ảnh từ kho. max_count=1 cho khung đầu/cuối."""

    def __init__(self, parent, lib, selected: list[str] | None = None, max_count: int = 10, title: str | None = None):
        super().__init__(parent)
        self.lib = lib
        self.max = max_count
        self.setWindowTitle(title or tr("Chọn ảnh tham chiếu"))
        self.resize(900, 640)
        v = QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label(title or "Chọn ảnh tham chiếu", "h1"))
        self.count_lbl = label("", "muted")
        top.addWidget(self.count_lbl)
        top.addStretch()
        v.addLayout(top)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Tìm theo tên, mô tả…"))
        self.search.textChanged.connect(self._reload)
        self.chips = _GroupChips(lib)
        self.chips.changed.connect(lambda _: self._reload())
        bar.addWidget(self.search, 1)
        bar.addWidget(self.chips)
        v.addLayout(bar)
        self.grid = RefGrid(lib, tile=130, checkable=True, meta=False)
        self.grid.itemChanged.connect(self._limit)
        self.grid.itemDoubleClicked.connect(lambda _: self.max == 1 and self.accept())
        self.grid.files_dropped.connect(self._drop)
        self._checked = set(selected or [])
        v.addWidget(self.grid, 1)
        self.empty = label("Kho đang trống. Bấm 'Thêm ảnh mới vào kho' hoặc kéo-thả ảnh vào đây.", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        bot = QHBoxLayout()
        b_add = button("Thêm ảnh mới vào kho", None, "upload", "#67e8f9")
        b_add.clicked.connect(self._add)
        bot.addWidget(b_add)
        tip = label("Mẹo: gõ @Tên trong prompt để dùng ảnh cho riêng dòng đó.", "faint")
        bot.addWidget(tip)
        bot.addStretch()
        b_cancel = button("Hủy")
        b_cancel.clicked.connect(self.reject)
        self.b_ok = button("Dùng ảnh đã chọn", "primary", "check2")
        self.b_ok.clicked.connect(self.accept)
        bot.addWidget(b_cancel)
        bot.addWidget(self.b_ok)
        v.addLayout(bot)
        self._reload()

    def _reload(self):
        self._checked |= set(self.grid.checked_ids())
        visible = {self.grid.item(i).data(Qt.UserRole) for i in range(self.grid.count())}
        self._checked -= (visible - set(self.grid.checked_ids()))
        rows = self.lib.all(self.chips.current, self.search.text())
        self.grid.blockSignals(True)
        self.grid.load(rows, self._checked)
        self.grid.blockSignals(False)
        self.empty.setVisible(not self.lib.all())
        self._update()

    def _limit(self, it):
        ids = self.grid.checked_ids()
        if it.checkState() == Qt.Checked and len(self._all_checked()) > self.max:
            if self.max == 1:   # chọn một: bỏ ô cũ
                self.grid.blockSignals(True)
                for i in range(self.grid.count()):
                    o = self.grid.item(i)
                    if o is not it:
                        o.setCheckState(Qt.Unchecked)
                self._checked = set()
                self.grid.blockSignals(False)
            else:
                self.grid.blockSignals(True)
                it.setCheckState(Qt.Unchecked)
                self.grid.blockSignals(False)
        self._update()

    def _all_checked(self) -> set[str]:
        visible = {self.grid.item(i).data(Qt.UserRole) for i in range(self.grid.count())}
        return (self._checked - visible) | set(self.grid.checked_ids())

    def _update(self):
        n = len(self._all_checked())
        self.count_lbl.setText(f"· {tr('đã chọn')} {n}" + (f" ({tr('tối đa')} {self.max})" if self.max > 1 else ""))
        self.b_ok.setEnabled(n > 0)
        self.b_ok.setText(tr("Dùng") + f" {n} " + tr("ảnh đã chọn") if n else tr("Dùng ảnh đã chọn"))
        self.grid.viewport().update()

    def _add(self):
        if add_images_dialog(self, self.lib):
            self.chips.reload()
            self._reload()

    def _drop(self, files):
        if import_with_names(self, self.lib, files):
            self.chips.reload()
            self._reload()

    def selected_ids(self) -> list[str]:
        ids = self._all_checked()
        order = [r["id"] for r in self.lib.all()]
        return sorted(ids, key=lambda i: order.index(i) if i in order else 0)


class RefStrip(QWidget):
    """Hàng ảnh tham chiếu đã chọn (có nút bỏ) + ô '+' + nút 'Chọn từ kho'."""
    changed = Signal()

    def __init__(self, lib, max_count: int = 10, single: bool = False, placeholder: str = ""):
        super().__init__()
        self.lib = lib
        self.max = 1 if single else max_count
        self.single = single
        self.placeholder = placeholder
        self.ids: list[str] = []
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(0, 0, 0, 0)
        self.h.setSpacing(8)
        self._render()

    def set_ids(self, ids: list[str]):
        self.ids = [i for i in ids if self.lib.get(i)][: self.max]
        self._render()

    def _render(self):
        while self.h.count():
            w = self.h.takeAt(0).widget()
            if w:
                w.deleteLater()
        size = (120, 68) if self.single else (56, 56)
        for rid in self.ids:
            r = self.lib.get(rid)
            if not r:
                continue
            box = QLabel()
            box.setFixedSize(*size)
            pm = thumb(r["path"], max(size)).scaled(size[0], size[1], Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            box.setPixmap(pm)
            box.setToolTip(f"@{r['name']}\n{tr('Bấm để bỏ')}")
            box.setStyleSheet(f"border:2px solid {C['accent']};border-radius:4px;")
            box.setCursor(Qt.PointingHandCursor)
            box.mousePressEvent = lambda e, i=rid: self._remove(i)
            self.h.addWidget(box)
            if self.single:
                box.setToolTip(f"@{r['name']} · {tr(self.placeholder)}\n{tr('Bấm để bỏ')}")
        if len(self.ids) < self.max:
            add = QPushButton("+" if not self.single else "+ " + tr(self.placeholder or "Chọn ảnh"))
            add.setFixedSize(*(size if not self.single else (150, 68)))
            add.setCursor(Qt.PointingHandCursor)
            add.setStyleSheet(f"QPushButton{{border:1.5px dashed #4a5fb0;border-radius:4px;color:{C['accent']};"
                              f"background:transparent;font-size:{18 if not self.single else 12}px;}}"
                              f"QPushButton:hover{{border-color:{C['accent']};}}")
            add.clicked.connect(self.pick)
            self.h.addWidget(add)
        self.h.addStretch()

    def _remove(self, rid):
        self.ids = [i for i in self.ids if i != rid]
        self._render()
        self.changed.emit()

    def pick(self):
        d = RefPickerDialog(self.window(), self.lib, self.ids, self.max,
                            tr("Chọn ảnh") + (f" – {tr(self.placeholder)}" if self.placeholder else ""))
        if d.exec():
            self.ids = d.selected_ids()[: self.max]
            self._render()
            self.changed.emit()

    def paths(self) -> list[str]:
        return self.lib.paths(self.ids)


class RefsPage(QWidget):
    """Trang Kho ảnh tham chiếu."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.lib = ctx.characters
        self.cur: dict | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 14)
        root.setSpacing(10)
        top = QHBoxLayout()
        top.addWidget(label("Kho ảnh tham chiếu", "h1"))
        self.info = label("", "muted")
        top.addWidget(self.info)
        top.addStretch()
        b_add = button("Thêm ảnh", "primary", "upload")
        b_add.clicked.connect(self._add)
        b_dir = button("Nhập cả thư mục", None, "folder", "#67e8f9")
        b_dir.clicked.connect(self._add_dir)
        self.b_all = button("Chọn tất cả", None, "check2", "#67e8f9")
        self.b_all.clicked.connect(self._toggle_all)
        b_del = button("Xóa đã chọn", "stop", "trash", C["danger"])
        b_del.clicked.connect(self._delete)
        for b in (b_add, b_dir, self.b_all, b_del):
            top.addWidget(b)
        root.addLayout(top)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Tìm theo tên, mô tả…"))
        self.search.setFixedWidth(320)
        self.search.textChanged.connect(self.reload)
        self.chips = _GroupChips(self.lib)
        self.chips.changed.connect(lambda _: self.reload())
        bar.addWidget(self.search)
        bar.addWidget(self.chips)
        bar.addStretch()
        root.addLayout(bar)
        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)
        gl = QVBoxLayout()
        self.grid = RefGrid(self.lib, tile=170, checkable=True, meta=True)
        self.grid.currentItemChanged.connect(lambda it, _: it and self._show(it.data(Qt.UserRole + 1)))
        self.grid.files_dropped.connect(self._drop)
        self.empty = label("Kho đang trống.\nBấm 'Thêm ảnh' hoặc kéo-thả ảnh vào đây.\n\n"
                           "Đặt tên cho ảnh (vd: Minh), rồi gõ @Minh trong prompt để dùng ảnh đó làm tham chiếu.", "muted")
        self.empty.setAlignment(Qt.AlignCenter)
        gl.addWidget(self.grid, 1)
        gl.addWidget(self.empty, 1)
        body.addLayout(gl, 1)

        det = Card("Chi tiết ảnh", "image", icon_color="#f9a8d4")
        det.setFixedWidth(340)
        self.preview = QLabel()
        self.preview.setFixedHeight(230)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(f"background:{C['input-bg']};border-radius:5px;")
        det.add(self.preview)
        self.name = QLineEdit()
        self.name.setPlaceholderText(tr("vd: Minh, CoGaiAoDai"))
        self.grp = QComboBox()
        self.grp.setEditable(True)
        self.grp.addItems([tr(g) for g in GROUPS])
        self.desc = QPlainTextEdit()
        self.desc.setFixedHeight(90)
        self.desc.setPlaceholderText(tr("Mô tả cố định (tự chèn vào prompt khi dùng @Tên): tuổi, tóc, trang phục…"))
        det.add(field("Tên gọi (gõ @Tên trong prompt)", self.name))
        det.add(field("Nhóm", self.grp))
        det.add(field("Mô tả", self.desc))
        r = QHBoxLayout()
        b_save = button("Lưu", "primary", "save")
        b_save.clicked.connect(self._save)
        b_rep = button("Thay ảnh", None, "image", "#67e8f9")
        b_rep.clicked.connect(self._replace)
        r.addWidget(b_save)
        r.addWidget(b_rep)
        det.add(r)
        det.body_layout.addStretch()
        self.det = det
        body.addWidget(det)
        self.reload()

    def reload(self):
        rows = self.lib.all(self.chips.current, self.search.text())
        self.grid.load(rows)
        total = len(self.lib.all())
        self.info.setText(f"· {total} " + tr("ảnh · dùng khi tạo ảnh (Tham chiếu) và video (Ảnh → Video / Tham chiếu)"))
        self.grid.setVisible(total > 0)
        self.empty.setVisible(total == 0)
        self.det.setEnabled(self.cur is not None)
        if rows and (self.cur is None or not any(x["id"] == self.cur["id"] for x in rows)):
            self.grid.setCurrentRow(0)

    def _show(self, r):
        self.cur = r
        self.det.setEnabled(True)
        pm = QPixmap(r["path"])
        if not pm.isNull():
            self.preview.setPixmap(pm.scaled(310, 226, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.name.setText(r["name"])
        self.grp.setCurrentText(tr(r["grp"]))
        self.desc.setPlainText(r["description"])

    def _refresh_all(self):
        self.chips.reload()
        self.reload()

    def _add(self):
        if add_images_dialog(self, self.lib, self.chips.current or "Nhân vật"):
            self._refresh_all()

    def _add_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Chọn thư mục ảnh"))
        if d:
            files = [str(f) for f in sorted(Path(d).iterdir()) if f.suffix.lower() in IMG_EXT]
            n = len(import_with_names(self, self.lib, files, self.chips.current or "Nhân vật"))
            if n:
                self.ctx.toast("ok", tr("Đã thêm") + f" {n} " + tr("ảnh"))
            self._refresh_all()

    def _drop(self, files):
        if import_with_names(self, self.lib, files, self.chips.current or "Nhân vật"):
            self._refresh_all()

    def _save(self):
        if not self.cur:
            return
        nm = self.lib.update(self.cur["id"], self.name.text().strip() or self.cur["name"],
                             self.grp.currentText().strip() or "Khác", self.desc.toPlainText().strip())
        if nm != self.name.text().strip():
            self.ctx.toast("warn", tr("Tên đã có, đổi thành") + f" @{nm}")
        else:
            self.ctx.toast("ok", tr("Đã lưu") + f" @{nm}")
        self.cur = self.lib.get(self.cur["id"])
        self._refresh_all()

    def _replace(self):
        if not self.cur:
            return
        f, _ = QFileDialog.getOpenFileName(self, tr("Chọn ảnh mới"), "", "Ảnh (*.png *.jpg *.jpeg *.webp)")
        if f:
            self.lib.replace_image(self.cur["id"], f)
            self.cur = self.lib.get(self.cur["id"])
            _PIX.clear()
            self._show(self.cur)
            self.reload()

    def _toggle_all(self):
        on = len(self.grid.checked_ids()) < self.grid.count()
        self.grid.set_all(on)

    def _delete(self):
        ids = self.grid.checked_ids()
        if not ids:
            self.ctx.toast("info", tr("Tick chọn ảnh cần xóa trước."))
            return
        if QMessageBox.question(self, tr("Xóa"), tr("Xóa") + f" {len(ids)} " + tr("ảnh khỏi kho?")) == QMessageBox.Yes:
            self.lib.delete(ids)
            if self.cur and self.cur["id"] in ids:
                self.cur = None
            self._refresh_all()

    def showEvent(self, e):
        super().showEvent(e)
        self._refresh_all()
