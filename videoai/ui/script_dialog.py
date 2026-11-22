"""Popup "Quy trình tự động": chủ đề · ảnh tham chiếu (Nhân vật + giọng nói / Sản phẩm / Bối cảnh) · ý tưởng · thời lượng
→ AI Agent viết kịch bản đúng số cảnh → người dùng sửa → Lưu: mỗi cảnh thành 1 tác vụ của trang tạo video."""
from __future__ import annotations

import hashlib
import threading
import urllib.request
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QIntValidator, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QPlainTextEdit, QPushButton, QScrollArea, QLineEdit, QSlider, QVBoxLayout, QWidget)

from .theme import icon, icon_pixmap
from .widgets import ShineButton, button, combo, field, icon_button, label
from .workers import run_bg
from ..core.i18n import tr
from ..services import script as S

TAG_COLOR = {"NV": ["#22d3ee", "#c4a5ff", "#f9a8d4", "#86efac", "#fdba74"], "SP": ["#fbbf24"], "BC": ["#4ade80"]}
MAX_PER_KIND = {"NV": 5, "SP": 5, "BC": 4}
IMG_FILTER = "Ảnh (*.png *.jpg *.jpeg *.webp *.bmp)"
CLIP_SECS = {"flow": 8, "grok": 6, "muse": 10}


def tag_color(tag: str) -> str:
    cols = TAG_COLOR.get(tag[:2], ["#9aa6d6"])
    try:
        return cols[(int(tag[2:]) - 1) % len(cols)]
    except ValueError:
        return cols[0]


def rounded(path: str, w: int, h: int) -> QPixmap:
    src = QPixmap(path)
    out = QPixmap(w, h)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    pp = QPainterPath()
    pp.addRoundedRect(0, 0, w, h, 8, 8)
    p.setClipPath(pp)
    if not src.isNull():
        sc = src.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        p.drawPixmap((w - sc.width()) // 2, (h - sc.height()) // 2, sc)
    else:
        p.fillRect(0, 0, w, h, QColor("#101a52"))
    p.end()
    return out


# ====================================================================== nút chọn trực quan
# Tỷ lệ video theo đúng nền tảng (Flow chỉ có 16:9 / 9:16; Grok Imagine có thêm 1:1, 2:3, 3:2)
VIDEO_RATIOS = {"flow": ["9:16", "16:9"], "grok": ["9:16", "16:9", "1:1", "2:3", "3:2"], "muse": ["9:16", "16:9"]}
RATIO_FULL = {"16:9": "16:9 Ngang", "9:16": "9:16 Dọc", "1:1": "1:1 Vuông", "4:3": "4:3 Ngang", "3:4": "3:4 Dọc",
              "2:3": "2:3 Dọc", "3:2": "3:2 Ngang"}
STYLE_SHORT = ["Chân thực", "Điện ảnh", "Hoạt hình 3D", "Anime"]          # cùng thứ tự với S.STYLES
LANG_SHORT = ["Tiếng Việt", "Tiếng Anh", "Không thoại"]                   # cùng thứ tự với S.LANGS


def ratio_pixmap(r: str, color: str, size: int = 18) -> QPixmap:
    """Hình chữ nhật đúng tỷ lệ (9:16 dọc, 16:9 ngang, 1:1 vuông…) để nhìn là biết khung."""
    a, b = (float(x) for x in r.split(":"))
    k = (size - 3) / max(a, b)
    w, h = a * k, b * k
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(color), 1.6))
    p.drawRoundedRect((size - w) / 2, (size - h) / 2, w, h, 2, 2)
    p.end()
    return pm


def _seg():
    from .pages.flow_page import Seg
    return Seg


class NumBox(QLineEdit):
    """Ô nhập số (gõ trực tiếp hoặc bấm − / +), giới hạn lo..hi."""
    valueChanged = Signal(int)

    def __init__(self, lo: int, hi: int, v: int):
        super().__init__()
        self.lo, self.hi = lo, hi
        self.setValidator(QIntValidator(lo, hi, self))
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet("QLineEdit{font-size:16px;font-weight:800;color:#22d3ee;padding:0;}")
        self._v = max(lo, min(hi, v))
        self.setText(str(self._v))
        self.textEdited.connect(self._edited)
        self.editingFinished.connect(lambda: self.setText(str(self._v)))

    def _edited(self, t):
        if t.isdigit():
            self.setValue(int(t), keep_text=True)

    def value(self) -> int:
        return self._v

    def maximum(self) -> int:
        return self.hi

    def setValue(self, v: int, keep_text: bool = False):
        v = max(self.lo, min(self.hi, int(v)))
        if not keep_text:
            self.setText(str(v))
        if v != self._v:
            self._v = v
            self.valueChanged.emit(v)


class RatioSeg(QWidget):
    """Hàng nút tỷ lệ có hình khung (dùng như combo cũ: currentText())."""

    def __init__(self, items: list[str], current: str):
        super().__init__()
        self.seg = _seg()(items, current)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(self.seg)
        self.btns = self.seg.btns
        for r, b in self.btns.items():             # khóa có thể là "16:9 Ngang" (trang ảnh) hoặc "16:9" (video)
            r0 = r.split(" ")[0]
            ic = QIcon()
            ic.addPixmap(ratio_pixmap(r0, "#7f8bc4"), QIcon.Normal, QIcon.Off)
            ic.addPixmap(ratio_pixmap(r0, "#ffffff"), QIcon.Normal, QIcon.On)
            b.setIcon(ic)
            b.setIconSize(QSize(18, 18))
            b.setText(" " + r0)
            b.setMinimumHeight(34)

    def currentText(self) -> str:
        return self.seg.value()

    def value(self) -> str:
        return self.seg.value()

    def set_value(self, v: str):
        self.seg.set_value(v)


# ====================================================================== ô ảnh

class RefTile(QFrame):
    removed = Signal(object)
    voice_clicked = Signal(object)

    def __init__(self, ref: S.RefImage, show_voice: bool):
        super().__init__()
        self.ref = ref
        c = tag_color(ref.tag)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        box = QFrame()
        box.setFixedSize(60, 74)
        box.setObjectName("rt")
        box.setStyleSheet(f"QFrame#rt{{background:#0b1030;border:1px solid {c};border-radius:9px;}}")
        im = QLabel(box)
        im.setPixmap(rounded(ref.path, 54, 68))
        im.move(4, 4)
        t = QLabel(ref.tag, box)
        t.setStyleSheet(f"background:{c};color:#0b1030;font-weight:800;font-size:10px;border-radius:6px;padding:1px 6px;")
        t.move(6, 6)
        t.adjustSize()
        x = QPushButton(box)
        x.setFixedSize(18, 18)
        x.setIcon(icon("x", "#ffffff", 11))
        x.setCursor(Qt.PointingHandCursor)
        x.setToolTip(tr("Bỏ ảnh này"))
        x.setStyleSheet("QPushButton{background:rgba(0,0,0,160);border-radius:9px;border:none;}")
        x.move(39, 4)
        x.clicked.connect(lambda: self.removed.emit(self.ref))
        box.setToolTip(Path(ref.path).name)
        v.addWidget(box)
        self.voice_btn = None
        if show_voice:
            b = QPushButton(" " + (ref.voice or tr("Giọng")) + " ▾")
            b.setFixedSize(60, 20)
            b.setIcon(icon("mic", c, 12))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tr("Chọn giọng nói của nhân vật này – giọng được giữ giống nhau ở mọi cảnh"))
            b.setStyleSheet(f"QPushButton{{background:#101a52;border:1px solid {c};border-radius:6px;color:#eaf0ff;"
                            f"font-size:10px;padding:0 2px;}}")
            b.clicked.connect(lambda: self.voice_clicked.emit(self.ref))
            v.addWidget(b)
            self.voice_btn = b


class RefSection(QFrame):
    """Mục ảnh tham chiếu theo loại: Nhân vật (NV) / Sản phẩm (SP) / Bối cảnh (BC)."""
    changed = Signal()

    def __init__(self, dlg, kind: str, title: str, sub: str, ic: str, color: str):
        super().__init__()
        self.dlg, self.kind = dlg, kind
        self.refs: list[S.RefImage] = []
        self.setObjectName("sec")
        self.setStyleSheet("QFrame#sec{background:#0d1442;border:1px solid #22357a;border-radius:12px;}")
        self.setAcceptDrops(True)
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 5, 10, 7)
        v.setSpacing(4)
        h = QHBoxLayout()
        h.setSpacing(8)
        i = QLabel()
        i.setPixmap(icon_pixmap(ic, color, 16))
        h.addWidget(i)
        h.addWidget(QLabel(f"<b style='color:{color}'>{tr(title)}</b>  <span style='color:#7f8bc4;font-size:11px'>{tr(sub)}</span>"), 1)
        v.addLayout(h)
        self.row = QHBoxLayout()
        self.row.setSpacing(8)
        v.addLayout(self.row)
        self.add_text = {"NV": "Thêm", "SP": "Thêm", "BC": "Thêm"}[kind]
        self.render()

    # -- kéo thả ảnh vào khung
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.add_paths([u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])

    def add_paths(self, paths: list[str]):
        for p in paths:
            if len(self.refs) >= MAX_PER_KIND[self.kind]:
                break
            if Path(p).suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp") and Path(p).exists():
                self.refs.append(S.RefImage(f"{self.kind}{len(self.refs) + 1}", str(p)))
        self.render()
        self.changed.emit()

    def remove(self, ref):
        self.refs = [r for r in self.refs if r is not ref]
        for i, r in enumerate(self.refs, 1):          # đánh lại nhãn liên tục NV1, NV2…
            r.tag = f"{self.kind}{i}"
        self.render()
        self.changed.emit()

    def render(self):
        while self.row.count():
            it = self.row.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        show_voice = self.kind == "NV" and self.dlg.voices_on()
        for r in self.refs:
            t = RefTile(r, show_voice)
            t.removed.connect(self.remove)
            t.voice_clicked.connect(self.dlg.pick_voice)
            self.row.addWidget(t, 0, Qt.AlignTop)
        if len(self.refs) < MAX_PER_KIND[self.kind]:
            b = QPushButton()
            b.setFixedSize(60, 74)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tr("Thêm ảnh từ máy hoặc từ Kho ảnh tham chiếu (có thể kéo thả ảnh vào khung này)"))
            b.setStyleSheet("QPushButton{background:#0b1030;border:1.5px dashed #4a5fb0;border-radius:9px;}"
                            "QPushButton:hover{border-color:#22d3ee;}")
            bv = QVBoxLayout(b)
            bv.setContentsMargins(0, 6, 0, 4)
            i = QLabel()
            i.setPixmap(icon_pixmap("plus", "#7f8bc4", 18))
            i.setAlignment(Qt.AlignCenter)
            i.setStyleSheet("background:transparent;")
            t = QLabel(tr(self.add_text))
            t.setAlignment(Qt.AlignCenter)
            t.setWordWrap(True)
            t.setStyleSheet("background:transparent;color:#9aa6d6;font-size:10px;")
            bv.addWidget(i)
            bv.addWidget(t)
            b.clicked.connect(lambda: self._add_menu(b))
            self.row.addWidget(b, 0, Qt.AlignTop)
        self.row.addStretch(1)

    def _add_menu(self, anchor):
        m = QMenu(self)
        m.addAction(icon("folder", "#67e8f9"), tr("Chọn ảnh trên máy…"), self._from_disk)
        m.addAction(icon("library", "#f9a8d4"), tr("Chọn từ Kho ảnh tham chiếu…"), self._from_lib)
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def _from_disk(self):
        fs, _ = QFileDialog.getOpenFileNames(self, tr(self.add_text), "", IMG_FILTER)
        self.add_paths(fs)

    def _from_lib(self):
        from .refs_ui import RefPickerDialog
        lib = self.dlg.page.lib
        d = RefPickerDialog(self.window(), lib, [], MAX_PER_KIND[self.kind] - len(self.refs), tr(self.add_text))
        if d.exec():
            self.add_paths(lib.paths(d.selected_ids()))


# ====================================================================== cảnh
class SceneCard(QFrame):
    rewrite = Signal(int)
    delete = Signal(int)

    def __init__(self, idx: int, sc: dict, image: bool = False):
        super().__init__()
        self.idx = idx
        self.sc = sc
        self.setObjectName("sc")
        self.setStyleSheet("QFrame#sc{background:#0b1030;border:1px solid #22357a;border-radius:10px;}")
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 8, 10, 8)
        v.setSpacing(5)
        h = QHBoxLayout()
        h.setSpacing(6)
        n = QLabel(str(idx + 1))
        n.setFixedSize(22, 22)
        n.setAlignment(Qt.AlignCenter)
        n.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #6366f1,stop:1 #d946ef);color:white;"
                        "border-radius:11px;font-weight:800;")
        h.addWidget(n)
        meta = " · ".join(x for x in (sc.get("time", ""), sc.get("title", "")) if x)
        h.addWidget(QLabel(f"<b style='color:#eaf0ff'>{tr('Ảnh' if image else 'Cảnh')} {idx + 1}</b> "
                           f"<span style='color:#7f8bc4'>· {meta}</span>"), 1)
        for t in sc.get("refs", []):
            c = tag_color(t)
            lb = QLabel(t)
            lb.setStyleSheet(f"color:{c};border:1px solid {c};border-radius:7px;padding:0 6px;font-size:10px;font-weight:700;")
            h.addWidget(lb)
        self.b_re = icon_button("retry", "Viết lại ảnh này" if image else "Viết lại cảnh này")
        self.b_re.clicked.connect(lambda: self.rewrite.emit(self.idx))
        b_del = icon_button("trash", "Xóa ảnh" if image else "Xóa cảnh", "#fb7185")
        b_del.clicked.connect(lambda: self.delete.emit(self.idx))
        h.addWidget(self.b_re)
        h.addWidget(b_del)
        v.addLayout(h)
        self.edit = QPlainTextEdit(sc["prompt"])
        self.edit.setFixedHeight(78)
        self.edit.setStyleSheet("QPlainTextEdit{border:none;background:transparent;color:#cdd6ff;font-size:12px;}")
        self.edit.setToolTip(tr("Sửa trực tiếp prompt của cảnh"))
        v.addWidget(self.edit)

    def value(self) -> dict:
        return dict(self.sc, prompt=" ".join(self.edit.toPlainText().split()))


# ====================================================================== hộp chọn giọng
class VoicePicker(QDialog):
    """29 giọng của Google Flow: lọc Nữ / Nam, bấm ▶ để nghe thử (mẫu của Flow, hoặc câu thoại riêng đọc qua Flow)."""
    _got = Signal(str, str, str)      # voice, path, error

    def __init__(self, parent, ctx, tag: str, current: str = "", sample: str = ""):
        super().__init__(parent)
        self.ctx = ctx
        self.chosen = current or ""
        self.setWindowTitle(tr("Chọn giọng nói") + f" – {tag}")
        self.resize(780, 620)
        self.setStyleSheet("QDialog{background:#070b24;} QLabel{background:transparent;}")
        self.player = None
        self._got.connect(self._on_audio)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(10)
        v.addWidget(QLabel(f"<span style='font-size:16px;font-weight:800;color:#fff'>{tr('Chọn giọng nói cho')} {tag}</span>"))
        v.addWidget(QLabel("<span style='color:#9aa6d6'>" + tr(
            "29 giọng của Google Flow. Bấm ▶ để nghe thử. Để trống câu thoại: nghe đoạn mẫu của Flow (nhanh). "
            "Gõ câu thoại: Flow đọc đúng câu của bạn bằng tài khoản Flow (mất vài giây).") +
            "<br>" + tr("Giọng đã chọn được gắn vào mọi cảnh có nhân vật này để giọng nói giống nhau xuyên suốt video.") +
            "</span>"))
        fr = QHBoxLayout()
        self.filt = QButtonGroup(self)
        for i, t in enumerate(("Tất cả", "Nữ", "Nam")):
            b = QPushButton(tr(t))
            b.setProperty("kind", "seg")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(30)
            self.filt.addButton(b, i)
            fr.addWidget(b)
        self.filt.idClicked.connect(lambda _: self._fill())
        fr.addStretch(1)
        v.addLayout(fr)
        v.addWidget(label("Câu thoại mẫu để nghe thử (tối đa 120 ký tự, để trống = mẫu của Flow)", "fieldLabel"))
        self.sample = QPlainTextEdit(sample)
        self.sample.setFixedHeight(46)
        self.sample.textChanged.connect(self._clip)
        v.addWidget(self.sample)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setStyleSheet("QScrollArea{border:none;}")
        inner = QWidget()
        inner.setObjectName("vin")
        inner.setStyleSheet("QWidget#vin{background:#070b24;}")
        self.grid = QGridLayout(inner)
        self.grid.setSpacing(8)
        self.grid.setContentsMargins(0, 0, 6, 0)
        sa.setWidget(inner)
        v.addWidget(sa, 1)
        fb = QHBoxLayout()
        self.status = QLabel()
        self.status.setStyleSheet("color:#7f8bc4;")
        fb.addWidget(self.status, 1)
        bc = button("Hủy")
        bc.clicked.connect(self.reject)
        fb.addWidget(bc)
        self.b_ok = ShineButton(tr("Dùng giọng này"), "check", ("#22d3ee", "#6366f1", "#d946ef"))
        self.b_ok.setFixedHeight(38)
        self.b_ok.clicked.connect(self._ok)
        fb.addWidget(self.b_ok)
        v.addLayout(fb)
        self.cards: dict[str, tuple[QFrame, QPushButton]] = {}
        self._fill()
        self._show_status()

    def _clip(self):
        t = self.sample.toPlainText()
        if len(t) > 120:
            self.sample.setPlainText(t[:120])

    def _fill(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        self.cards.clear()
        want = {0: None, 1: "Nữ", 2: "Nam"}[self.filt.checkedId()]
        vs = [n for n, _ in S.VOICES if want is None or S.voice_gender(n) == want]
        for i, n in enumerate(vs):
            f = QFrame()
            f.setObjectName("vc")
            f.setCursor(Qt.PointingHandCursor)
            h = QHBoxLayout(f)
            h.setContentsMargins(10, 8, 10, 8)
            pb = QPushButton()
            pb.setFixedSize(34, 34)
            pb.setIcon(icon("play", "#ffffff", 16))
            pb.setIconSize(QSize(16, 16))
            pb.setCursor(Qt.PointingHandCursor)
            pb.setToolTip(tr("Nghe thử"))
            pb.setStyleSheet("QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #6366f1,stop:1 #d946ef);"
                             "border-radius:17px;border:none;}")
            pb.clicked.connect(lambda _=False, nm=n: self.play(nm))
            h.addWidget(pb)
            tx = QVBoxLayout()
            tx.setSpacing(0)
            tx.addWidget(QLabel(f"<b style='color:#eaf0ff'>{n}</b>"))
            tx.addWidget(QLabel(f"<span style='color:#9aa6d6;font-size:11px'>{S.voice_gender(n)}, {S.voice_desc(n).split(', ', 1)[-1]}</span>"))
            h.addLayout(tx, 1)
            f.mousePressEvent = lambda _e, nm=n: self._choose(nm)
            self.grid.addWidget(f, i // 2, i % 2)
            self.cards[n] = (f, pb)
        self._paint()

    def _paint(self):
        for n, (f, _) in self.cards.items():
            sel = n == self.chosen
            f.setStyleSheet(f"QFrame#vc{{background:{'#0f2340' if sel else '#0d1442'};"
                            f"border:{'2px solid #22d3ee' if sel else '1px solid #22357a'};border-radius:10px;}}")

    def _choose(self, n):
        self.chosen = n
        self._paint()
        self._show_status()

    def _show_status(self, extra: str = ""):
        cur = (f"{tr('Đã chọn')}: <b style='color:#22d3ee'>{self.chosen}</b> – {S.voice_gender(self.chosen)}, "
               f"{S.voice_desc(self.chosen).split(', ', 1)[-1]}") if self.chosen else tr("Chưa chọn giọng")
        self.status.setText(cur + (f"  ·  {extra}" if extra else ""))

    # -- nghe thử
    def play(self, n: str):
        self._choose(n)
        text = " ".join(self.sample.toPlainText().split())
        if not text:
            dst = S.voice_cache_dir() / f"{n}.wav"
            if dst.exists() and dst.stat().st_size > 1000:
                return self._play_file(str(dst))
            self._show_status(tr("đang tải mẫu…"))

            def get():
                try:
                    req = urllib.request.Request(S.VOICE_SAMPLE_URL.format(name=n), headers={"User-Agent": "Mozilla/5.0"})
                    data = urllib.request.urlopen(req, timeout=20).read()
                    dst.write_bytes(data)
                    self._got.emit(n, str(dst), "")
                except Exception as e:
                    self._got.emit(n, "", f"không tải được mẫu ({e})")
            threading.Thread(target=get, daemon=True).start()
            return
        key = hashlib.sha1(f"{n}|{text}".encode()).hexdigest()[:16]
        hit = list(S.voice_cache_dir().glob(f"{n}_{key}.*"))
        if hit:
            return self._play_file(str(hit[0]))
        acc = next((a for a in self.ctx.db.accounts("flow") if a["enabled"] and a["status"] in ("ok", "unknown")), None)
        if acc is None:
            return self._show_status(tr("cần 1 tài khoản Google Flow đã đăng nhập để đọc câu thoại riêng"))
        self._show_status(tr("Flow đang đọc thử…"))
        fut = self.ctx.engine.flow_voice_preview(acc, n, text)

        def wait():
            try:
                data = fut.result(timeout=150)
                ext = ".wav" if data[:4] == b"RIFF" else ".ogg" if data[:4] == b"OggS" else ".mp3"
                dst = S.voice_cache_dir() / f"{n}_{key}{ext}"
                dst.write_bytes(data)
                self._got.emit(n, str(dst), "")
            except Exception as e:
                msg = getattr(e, "detail", "") or str(e)
                self._got.emit(n, "", f"Flow chưa đọc được ({msg[:120]})")
        threading.Thread(target=wait, daemon=True).start()

    def _on_audio(self, n, path, err):
        if err:
            return self._show_status(err)
        self._show_status()
        self._play_file(path)

    def _play_file(self, path: str):
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        except Exception:
            return self._show_status(tr("máy chưa có thư viện phát âm thanh"))
        if self.player is None:
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.player.setAudioOutput(self.audio)
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def _ok(self):
        if not self.chosen:
            return self._show_status(tr("hãy chọn 1 giọng"))
        if self.player:
            self.player.stop()
        self.accept()

    def sample_text(self) -> str:
        return self.sample.toPlainText()


# ====================================================================== popup chính
class ScriptDialog(QDialog):
    def __init__(self, page):
        super().__init__(page.window())
        self.page = page
        self.ctx = page.ctx
        self.db = page.db
        self.flow = page.pdef.platform == "flow"
        self.image = not page.video                 # Quy trình tự động ở trang TẠO ẢNH
        self.skey = "image_script_dialog" if self.image else "script_dialog"
        self.free = page._is_free()
        self.clip = page.clip_secs()
        self.script: dict | None = None
        self.cards: list[SceneCard] = []
        self.busy = False
        self.result_tasks: list[dict] = []
        st = self.db.get_setting(self.skey, {}) or {}
        self.setWindowTitle(tr("Quy trình tự động – Ảnh") if self.image else tr("Quy trình tự động"))
        scr = page.screen().availableGeometry() if page.screen() else None
        self.resize(min(1340, scr.width() - 40) if scr else 1340, min(800, scr.height() - 50) if scr else 800)
        self.setStyleSheet("QDialog{background:#070b24;} QLabel{background:transparent;}")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        bar = QFrame()
        bar.setFixedHeight(4)
        bar.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #f59e0b,stop:0.5 #d946ef,stop:1 #22d3ee);")
        root.addWidget(bar)
        hd = QHBoxLayout()
        hd.setContentsMargins(22, 14, 22, 8)
        hd.setSpacing(12)
        ic = QLabel()
        ic.setFixedSize(40, 40)
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(icon_pixmap("image" if self.image else "clapper", "#ffffff", 22))
        ic.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 #f59e0b,stop:1 #db2777);border-radius:10px;")
        hd.addWidget(ic)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        ttl = tr("Quy trình tự động – Ảnh") if self.image else tr("Quy trình tự động")
        tv.addWidget(QLabel(f"<span style='font-size:18px;font-weight:800;color:#fff'>{ttl}</span>"))
        tv.addWidget(QLabel("<span style='color:#9aa6d6'>" + (tr(
            "AI Agent xem ảnh tham chiếu, chọn bố cục theo mục đích và viết đủ số prompt ảnh") if self.image else tr(
            "AI Agent xem ảnh tham chiếu, viết kịch bản theo chủ đề và chia thành từng prompt đúng thời lượng")) + "</span>"))
        hd.addLayout(tv, 1)
        root.addLayout(hd)

        body = QHBoxLayout()
        body.setContentsMargins(22, 4, 22, 16)
        body.setSpacing(16)
        # ---------------- trái (gọn: mọi nút hiện đủ, không cần lăn chuột)
        lw = QWidget()
        lw.setFixedWidth(676)
        LO = QVBoxLayout(lw)
        LO.setContentsMargins(0, 0, 0, 0)
        LO.setSpacing(8)
        lsa = QScrollArea()                          # màn hình thấp: phần tùy chọn cuộn được, nút AI luôn hiện
        lsa.setWidgetResizable(True)
        lsa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lsa.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        lin = QWidget()
        lin.setObjectName("lin")
        lin.setStyleSheet("QWidget#lin{background:#070b24;}")
        L = QVBoxLayout(lin)
        L.setContentsMargins(0, 0, 4, 0)
        L.setSpacing(7)
        lsa.setWidget(lin)
        LO.addWidget(lsa, 1)
        L.addWidget(label("1. Mục đích" if self.image else "1. Chủ đề", "fieldLabel"))
        self.T = S.IMG_TOPICS if self.image else S.TOPICS
        order = S.IMG_TOPIC_ORDER if self.image else S.TOPIC_ORDER
        tg = QGridLayout()
        tg.setSpacing(6)
        self.topics = QButtonGroup(self)
        cur_t = st.get("topic") if st.get("topic") in self.T else order[0]
        for i, k in enumerate(order):
            b = QPushButton(tr(self.T[k][0]))
            b.setProperty("kind", "seg")
            b.setCheckable(True)
            b.setChecked(k == cur_t)
            b.setMinimumHeight(32)
            b.setStyleSheet("QPushButton{padding:0 4px;font-size:12px;}")
            b.setCursor(Qt.PointingHandCursor)
            b.setProperty("topic", k)
            self.topics.addButton(b, i)
            tg.addWidget(b, i // 4, i % 4)
        L.addLayout(tg)
        self.muse = page.pdef.platform == "muse" and not self.image
        nv_sub = ("NV1, NV2… – mỗi khung 1 nhân vật" if self.image
                  else "NV1, NV2… – mỗi khung 1 nhân vật · bấm 🎤 để chọn giọng nói")
        self.lang = None
        self.sec = {
            "NV": RefSection(self, "NV", "Nhân vật", nv_sub, "users", "#22d3ee"),
            "SP": RefSection(self, "SP", "Sản phẩm / Vật liệu", "SP1, SP2…", "image", "#fbbf24"),
            "BC": RefSection(self, "BC", "Bối cảnh", "BC1, BC2…", "camera", "#4ade80"),
        }
        L.addWidget(label("2. Ảnh tham chiếu  (AI nhận biết đúng từng nhân vật / sản phẩm / bối cảnh)", "fieldLabel"))
        L.addWidget(self.sec["NV"])
        sb = QHBoxLayout()
        sb.setSpacing(8)
        sb.addWidget(self.sec["SP"], 1)
        sb.addWidget(self.sec["BC"], 1)
        L.addLayout(sb)
        L.addWidget(label("3. Ý tưởng / thông tin sản phẩm", "fieldLabel"))
        self.idea = QPlainTextEdit(st.get("idea", ""))
        self.idea.setPlaceholderText(tr("Ví dụ: Bộ ảnh quảng cáo serum dưỡng ẩm cho da khô, tông xanh mát, sang trọng, "
                                        "NV1 cầm SP1, giá 299k.") if self.image else tr(
            "Ví dụ: Review serum dưỡng ẩm cho da khô, NV1 là người review, giọng vui vẻ, nhấn mạnh thấm nhanh, giá 299k."))
        self.idea.setFixedHeight(54)
        L.addWidget(self.idea)
        # 4. tùy chọn: mỗi mục 1 hàng nút chọn trực quan (nhãn bên trái)
        L.addWidget(label("4. Tùy chọn", "fieldLabel"))
        og = QGridLayout()
        og.setHorizontalSpacing(10)
        og.setVerticalSpacing(7)
        og.setColumnStretch(1, 1)
        rown = [0]

        def row(title, w):
            lb = QLabel(tr(title))
            lb.setStyleSheet("color:#cdd6ff;font-weight:600;")
            lb.setFixedWidth(84)
            og.addWidget(lb, rown[0], 0, Qt.AlignVCenter)
            og.addWidget(w, rown[0], 1)
            rown[0] += 1

        from .pages.flow_page import Seg
        top = 30
        if self.image:                       # Tổng số ảnh: ô nhập số (mỗi ảnh = 1 prompt) + Chữ trên ảnh
            self.dur = NumBox(1, 1 if self.free else top, 1 if self.free else int(st.get("scenes", 4)))
            self.dur.setFixedSize(64, 32)
            self.dur.valueChanged.connect(self._dur_text)
            pm_ = []
            for sym, d_ in (("−", -1), ("+", 1)):
                bb = QPushButton(sym)
                bb.setFixedSize(32, 32)
                bb.setMinimumWidth(32)
                bb.setCursor(Qt.PointingHandCursor)
                bb.setAutoRepeat(True)
                bb.setStyleSheet("QPushButton{background:#101a52;border:1px solid #2a3d8f;color:#eaf0ff;font-size:16px;"
                                 "font-weight:800;border-radius:6px;padding:0;} QPushButton:hover{border-color:#22d3ee;}")
                bb.clicked.connect(lambda _=False, d_=d_: self.dur.setValue(self.dur.value() + d_))
                pm_.append(bb)
            self.dur.valueChanged.connect(self._dur_text)
            self.dur_lbl = QLabel()
            self.text = Seg(["Không chữ", "Có tiêu đề"], "Có tiêu đề" if st.get("text_on") else "Không chữ")
            for bt in self.text.btns.values():
                bt.setMinimumHeight(32)
            tw = QWidget()
            th = QHBoxLayout(tw)
            th.setContentsMargins(0, 0, 0, 0)
            th.setSpacing(10)
            th.setSpacing(4)
            th.addWidget(pm_[0])
            th.addWidget(self.dur)
            th.addWidget(pm_[1])
            th.addSpacing(6)
            th.addWidget(self.dur_lbl)
            th.addSpacing(10)
            th.addStretch(1)
            tl = QLabel(tr("Chữ trên ảnh"))
            tl.setStyleSheet("color:#cdd6ff;font-weight:600;")
            th.addWidget(tl)
            self.text.setFixedWidth(250)
            th.addWidget(self.text)
            row("Tổng số ảnh", tw)
            ratios = list(page.pdef.ratios)          # giữ nhãn đầy đủ (adapter đọc "16:9 Ngang"…)
            cur_r = page.ratio.currentText()
        else:
            self.text = None
            self.dur = QSlider(Qt.Horizontal)
            self.dur.setRange(1, 1 if self.free else top)
            self.dur.setValue(1 if self.free else max(1, min(top, int(st.get("scenes", 5)))))
            self.dur.valueChanged.connect(self._dur_text)
            self.dur_lbl = QLabel()
            self.dur_lbl.setFixedWidth(200)
            dw = QWidget()
            dh = QHBoxLayout(dw)
            dh.setContentsMargins(0, 0, 0, 0)
            dh.setSpacing(12)
            dh.addWidget(self.dur, 1)
            dh.addWidget(self.dur_lbl)
            row("Thời lượng", dw)
            ratios = VIDEO_RATIOS.get(page.pdef.platform, ["9:16", "16:9"])
            cur_r = page.ratio_value()
        self.ratio = RatioSeg(ratios, cur_r if cur_r in ratios else ratios[0])
        row("Tỷ lệ", self.ratio)
        if not self.image:                   # Lời thoại: Tiếng Việt / Tiếng Anh / Không thoại (Muse: mặc định có thoại)
            cur_l = st.get("lang") if st.get("lang") in S.LANGS else S.LANGS[0]
            self.lang = Seg(LANG_SHORT, LANG_SHORT[S.LANGS.index(cur_l)], on_change=self._lang_changed)
            for bt in self.lang.btns.values():
                bt.setMinimumHeight(32)
            row("Lời thoại", self.lang)
        cur_s = st.get("style") if st.get("style") in S.STYLES else S.STYLES[0]
        self.style = Seg(STYLE_SHORT, STYLE_SHORT[S.STYLES.index(cur_s)])
        for bt in self.style.btns.values():
            bt.setMinimumHeight(32)
        row("Phong cách", self.style)
        # Nhất quán (video): 1 hàng
        self.cons_box = QWidget()
        ch = QHBoxLayout(self.cons_box)
        ch.setContentsMargins(0, 0, 0, 0)
        ch.setSpacing(8)
        self.cons = Seg(["Nhất quán cao", "Nhanh"], "Nhanh" if st.get("keyframe") is False else "Nhất quán cao")
        for bt in self.cons.btns.values():
            bt.setMinimumHeight(32)
        ch.addWidget(self.cons, 3)
        self.chain = QPushButton("  " + tr("Nối cảnh liền mạch"))
        self.chain.setCheckable(True)
        self.chain.setChecked(False)
        self.chain.hide()                             # v2.0.1: bỏ khỏi giao diện
        self.chain.setCursor(Qt.PointingHandCursor)
        self.chain.toggled.connect(self._chain_icon)
        self._chain_icon(self.chain.isChecked())
        ch.addWidget(self.chain, 0)
        if not self.image:
            row("Nhất quán", self.cons_box)
        else:
            self.cons_box.hide()
        L.addLayout(og)
        for k, s_ in self.sec.items():
            for r in st.get("refs", {}).get(k, []):
                if Path(r.get("path", "")).exists():
                    s_.refs.append(S.RefImage(f"{k}{len(s_.refs) + 1}", r["path"], r.get("voice", "")))
            s_.render()
        L.addStretch(1)
        self.gen_text = "Phân tích và tạo nội dung" if self.image else "Phân tích và tạo kịch bản"
        from .widgets import AIButton
        self.b_gen = AIButton(tr(self.gen_text), "sparkle", height=44)
        self.b_gen.clicked.connect(self.generate)
        LO.addWidget(self.b_gen)
        self.gen_status = QLabel()                    # tiến trình / lỗi của AI Agent: hiện đủ chữ dưới nút
        self.gen_status.setWordWrap(True)
        self.gen_status.setStyleSheet("color:#9aa6d6;font-size:12px;")
        self.gen_status.hide()
        LO.addWidget(self.gen_status)
        body.addWidget(lw)
        sep = QFrame()                                # vạch dọc phân cách 2 khối (sáng ở giữa, mờ 2 đầu)
        sep.setFixedWidth(2)
        sep.setStyleSheet("QFrame{border:none;background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
                          "stop:0 rgba(99,102,241,0),stop:0.2 #6366f1,stop:0.5 #22d3ee,stop:0.8 #d946ef,"
                          "stop:1 rgba(217,70,239,0));}")
        body.addWidget(sep)
        # ---------------- phải
        R = QVBoxLayout()
        R.setSpacing(8)
        rh = QHBoxLayout()
        self.head = QLabel()
        rh.addWidget(self.head, 1)
        self.b_all = button("Viết lại tất cả", None, "retry", "#aab4e8")
        self.b_all.clicked.connect(self.generate)
        rh.addWidget(self.b_all)
        R.addLayout(rh)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        inner = QWidget()
        inner.setObjectName("inn")
        inner.setStyleSheet("QWidget#inn{background:#070b24;}")
        self.list = QVBoxLayout(inner)
        self.list.setSpacing(8)
        self.list.setContentsMargins(0, 0, 6, 0)
        self.list.addStretch(1)
        self.empty = QLabel(tr("Chọn chủ đề, thêm ảnh, nhập ý tưởng rồi bấm") + "\n“" + tr(
            "Phân tích và tạo nội dung" if self.image else "Phân tích và tạo kịch bản") + "”\n\n" + tr(
            "AI Agent sẽ viết mỗi ảnh 1 prompt tại đây" if self.image else "AI Agent sẽ viết từng cảnh tại đây"))
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setStyleSheet("color:#5f6aa8;font-size:13px;")
        self.list.insertWidget(0, self.empty, 1)
        sa.setWidget(inner)
        from PySide6.QtWidgets import QStackedWidget
        from .widgets import AIWorking
        self.stack = QStackedWidget()                 # 0 = danh sách prompt · 1 = hiệu ứng AI Agent đang làm việc
        self.stack.addWidget(sa)
        self.working = AIWorking()
        self.stack.addWidget(self.working)
        R.addWidget(self.stack, 1)
        ft = QHBoxLayout()
        ft.addStretch(1)
        bc = button("Hủy")
        bc.setFixedHeight(42)
        bc.clicked.connect(self.reject)
        ft.addWidget(bc)
        self.b_save = ShineButton(tr("Bắt đầu chạy"), "play", ("#22d3ee", "#6366f1", "#d946ef"))
        self.b_save.setFixedHeight(42)
        self.b_save.setMinimumWidth(240)
        self.b_save.clicked.connect(self.save)
        ft.addWidget(self.b_save)
        R.addLayout(ft)
        rw = QWidget()
        rw.setLayout(R)
        body.addWidget(rw, 1)
        root.addLayout(body, 1)
        self._dur_text()
        self._render_scenes()

    # ------------------------------------------------ trạng thái
    def voices_on(self) -> bool:
        return not self.image and self.lang is not None and not self.lang_value().startswith("Không")

    def lang_value(self) -> str:
        if self.lang is None:
            return S.LANGS[-1]
        return S.LANGS[LANG_SHORT.index(self.lang.value())]

    def style_value(self) -> str:
        return S.STYLES[STYLE_SHORT.index(self.style.value())]

    def _lang_changed(self, *_):
        self.sec["NV"].render()

    def _chain_icon(self, on):
        self.chain.setIcon(icon("check", "#22d3ee" if on else "#3b4a8f", 16))
        self.chain.setStyleSheet("QPushButton{text-align:left;border:none;background:transparent;color:%s;}" %
                                 ("#eaf0ff" if on else "#9aa6d6"))

    def _dur_text(self):
        n = self.dur.value()
        if self.image:
            self.dur_lbl.setText("")
            return
        self.dur_lbl.setText(f"<b style='color:#22d3ee;font-size:15px'>{n * self.clip} {tr('giây')}</b>  "
                             f"<span style='color:#9aa6d6'>= {n} {tr('cảnh')} × {self.clip}s</span>")

    def topic(self) -> str:
        b = self.topics.checkedButton()
        return b.property("topic") if b else ("product" if self.image else "review")

    def refs(self) -> list[S.RefImage]:
        return [r for k in ("NV", "SP", "BC") for r in self.sec[k].refs]

    def brief(self) -> S.Brief:
        if self.image:
            return S.Brief(topic=self.topic(), idea=self.idea.toPlainText(), total_secs=0, clip_secs=0,
                           ratio=self.ratio.currentText(), style=self.style_value(), refs=self.refs(),
                           model=self.page.model_name(), platform=self.page.pdef.platform, kind="image",
                           count=self.dur.value(), text_on=self.text.value() == "Có tiêu đề", lang="Không thoại")
        return S.Brief(topic=self.topic(), idea=self.idea.toPlainText(), total_secs=self.dur.value() * self.clip,
                       clip_secs=self.clip, ratio=self.ratio.currentText(), lang=self.lang_value(),
                       style=self.style_value(), refs=self.refs(), model=self.page.model_name(),
                       keyframe=self.cons.value().startswith("Nhất quán"), platform=self.page.pdef.platform)

    def _save_state(self):
        if self.image:
            return self.db.set_setting(self.skey, {
                "topic": self.topic(), "idea": self.idea.toPlainText(), "scenes": self.dur.value(),
                "style": self.style_value(), "text_on": self.text.value() == "Có tiêu đề",
                "refs": {k: [{"path": r.path, "voice": ""} for r in s_.refs] for k, s_ in self.sec.items()}})
        self.db.set_setting("script_dialog", {
            "topic": self.topic(), "idea": self.idea.toPlainText(), "scenes": self.dur.value(),
            "lang": self.lang_value(), "style": self.style_value(),
            "keyframe": self.cons.value().startswith("Nhất quán"), "chain": self.chain.isChecked(),
            "refs": {k: [{"path": r.path, "voice": r.voice} for r in s_.refs] for k, s_ in self.sec.items()}})

    def pick_voice(self, ref: S.RefImage):
        if not self.flow:                         # Grok / Muse: chọn kiểu giọng (mô tả trong prompt)
            m = QMenu(self)
            for name, desc in S.VOICE_PRESETS.items():
                a = m.addAction(icon("mic", tag_color(ref.tag)), f"{name}  –  {desc}")
                a.setData(name)
            ch = m.exec(self.cursor().pos())
            if ch is not None:
                ref.voice = ch.data()
                self.sec["NV"].render()
                self._save_state()
            return
        st = self.db.get_setting("script_dialog", {}) or {}
        d = VoicePicker(self, self.ctx, ref.tag, ref.voice, st.get("voice_sample", ""))
        if d.exec():
            ref.voice = d.chosen
            self.sec["NV"].render()
        self._save_state()
        st = self.db.get_setting("script_dialog", {}) or {}
        st["voice_sample"] = d.sample_text()
        self.db.set_setting("script_dialog", st)

    # ------------------------------------------------ kết quả
    def _render_scenes(self):
        while self.list.count() > 2:
            it = self.list.takeAt(1)
            if it.widget():
                it.widget().hide()
                it.widget().deleteLater()
        self.cards = []
        sc = (self.script or {}).get("scenes", [])
        for i, s_ in enumerate(sc):
            c = SceneCard(i, s_, self.image)
            c.rewrite.connect(self.rewrite)
            c.delete.connect(self.delete_scene)
            self.list.insertWidget(i + 1, c)
            self.cards.append(c)
        n = len(sc)
        hd = f"<span style='font-size:14px;font-weight:800;color:#fff'>{tr('Danh sách Prompt kịch bản')}</span>  "
        if not n:
            self.head.setText(hd + f"<span style='color:#7f8bc4'>· {tr('chưa có prompt')}</span>")
        elif self.image:
            self.head.setText(hd + f"<span style='color:#4ade80'>● {n} prompt = {n} {tr('ảnh')} · "
                              f"{tr(self.T[self.topic()][0])}</span>")
        else:
            self.head.setText(hd + f"<span style='color:#4ade80'>● {n} {tr('cảnh')} · {n * self.clip} {tr('giây')} · "
                              f"{tr(S.TOPICS[self.topic()][0])}</span>")
        self.empty.setVisible(not n)
        self.b_all.setVisible(bool(n))
        self.b_save.setText(tr("Bắt đầu chạy") + (f" ({n})" if n else ""))
        self.b_save.setEnabled(bool(n))

    def _collect(self):
        if self.script:
            self.script["scenes"] = [c.value() for c in self.cards]

    def _set_busy(self, on: bool, msg: str = ""):
        self.busy = on
        self.stack.setCurrentIndex(1 if on else 0)
        self.b_gen.busy = on
        self.b_gen.setEnabled(not on)
        self.b_all.setEnabled(not on)
        self.b_save.setEnabled(not on and bool(self.cards))
        self.b_gen.setText(tr("AI Agent đang làm việc…") if on else tr(self.gen_text))
        self.b_gen.update()
        self._status(msg if on else "")

    def _status(self, msg: str, err: bool = False):
        self.gen_status.setText(("⚠ " if err else "● ") + tr(msg) if msg else "")
        self.gen_status.setStyleSheet(f"color:{'#fca5a5' if err else '#9aa6d6'};font-size:12px;")
        self.gen_status.setVisible(bool(msg))

    def generate(self):
        if self.busy:
            return
        from ..services import llm
        if llm.pick_account(self.db) is None:
            return self.ctx.toast("warn", tr("Chưa có tài khoản ChatGPT hoặc Google (Flow) nào đăng nhập cho AI Agent – "
                                             "thêm ở Cài đặt › Tài khoản."))
        b = self.brief()
        if not b.idea.strip() and not b.refs:
            return self.ctx.toast("warn", tr("Nhập ý tưởng hoặc thêm ít nhất 1 ảnh tham chiếu."))
        self._save_state()
        self._set_busy(True, "AI Agent đang phân tích và viết prompt…" if self.image else "AI Agent đang phân tích và viết kịch bản…")
        eng = self.ctx.engine
        gen = S.generate_images if self.image else S.generate

        def work(progress):
            return gen(self.db, eng, b, lambda m: progress(0, m))

        def done(res):
            self._set_busy(False)
            self.script = res
            self._render_scenes()
            self.ctx.toast("ok", tr("AI đã viết") + f" {len(res['scenes'])} " + tr("ảnh" if self.image else "cảnh"))

        def err(msg):
            self._set_busy(False)
            self._status(msg, err=True)
            self.ctx.toast("error", msg)
        run_bg(work, on_done=done, on_error=err, on_progress=lambda _p, m: m and self._status(m))

    def rewrite(self, k: int):
        if self.busy or not self.script:
            return
        self._collect()
        b = self.brief()
        b.total_secs = len(self.script["scenes"]) * self.clip
        b.count = len(self.script["scenes"])
        self._set_busy(True, (f"Đang viết lại ảnh {k + 1}…" if self.image else f"Đang viết lại cảnh {k + 1}…"))
        eng = self.ctx.engine
        script = self.script
        fn = S.rewrite_image if self.image else S.rewrite_scene

        def work(progress):
            return fn(self.db, eng, b, script, k, lambda m: progress(0, m))

        def done(sc):
            self._set_busy(False)
            self.script["scenes"][k] = sc
            self._render_scenes()

        def err(msg):
            self._set_busy(False)
            self.ctx.toast("error", msg)
        run_bg(work, on_done=done, on_error=err)

    def delete_scene(self, k: int):
        self._collect()
        if self.script and 0 <= k < len(self.script["scenes"]):
            del self.script["scenes"][k]
            if not self.image:
                S.fix_times(self.script["scenes"], self.clip)
            self._render_scenes()

    def save(self):
        if not self.script or not self.cards:
            return
        self._collect()
        self._save_state()
        b = self.brief()
        refs = S.keep_refs(self.refs())
        if self.image:
            self.result_tasks = S.image_tasks(b, self.script, refs)
        else:
            self.result_tasks = S.to_tasks(b, self.script, refs, self.chain.isChecked(), self.flow)
        self.accept()
