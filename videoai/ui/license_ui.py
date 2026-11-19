"""Cửa sổ Bản quyền: bảng giá, mua key (VietQR tự động hoặc qua Zalo), nhập key, dùng thử."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QPixmap
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from .theme import C
from ..core.i18n import tr
from ..core.license import FREE_PLAN, License, LicenseError, Status, fmt_vnd
from ..core.paths import APP_NAME, assets_dir

_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="license")


def run_bg(owner: QWidget, fn, done, fail=None):
    """Chạy fn ở luồng nền, xong gọi done(kết quả) / fail(lỗi) trên luồng giao diện."""
    fut = _pool.submit(fn)
    t = QTimer(owner)
    t.setInterval(80)

    def poll():
        if not fut.done():
            return
        t.stop()
        t.deleteLater()
        e = fut.exception()
        if e is None:
            done(fut.result())
        elif fail:
            fail(e)
    t.timeout.connect(poll)
    t.start()


def _btn(text, kind="primary", h=38):
    b = QPushButton(tr(text))
    b.setProperty("kind", kind)
    b.setCursor(Qt.PointingHandCursor)
    b.setMinimumHeight(h)
    return b


class PlanCard(QFrame):
    def __init__(self, plan: dict, on_buy, best: bool, current: bool = False):
        super().__init__()
        self.setObjectName("plan")
        free = plan.get("code") == "free"
        hot = best or (plan.get("badge") or "").lower().startswith("phổ biến")
        self.setStyleSheet(
            f"QFrame#plan{{background:qlineargradient(x1:0,y1:0,x2:1,y2:1,stop:0 {'#1a2470' if hot else C['surface-2']},"
            f"stop:1 {'#2a1660' if hot else C['surface']});border:{'2px solid #22d3ee' if hot else '1px solid ' + C['border']};"
            f"border-radius:7px;}}QFrame#plan:hover{{border:2px solid #67e8f9;}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 14)
        v.setSpacing(4)
        badge = QLabel(tr(plan.get("badge") or " "))
        badge.setAlignment(Qt.AlignCenter)
        if plan.get("badge"):
            badge.setStyleSheet("background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #f97316,stop:1 #ec4899);"
                                "color:white;border-radius:4px;padding:2px 8px;font-size:11px;font-weight:700;")
        else:
            badge.setStyleSheet("background:transparent;font-size:11px;")
        bh = QHBoxLayout()
        bh.addStretch()
        bh.addWidget(badge)
        bh.addStretch()
        v.addLayout(bh)
        tier = QLabel(tr("MIỄN PHÍ" if free else "CHUYÊN NGHIỆP"))
        tier.setAlignment(Qt.AlignCenter)
        tier.setStyleSheet(f"font-size:10.5px;font-weight:800;letter-spacing:1px;background:transparent;border:none;"
                           f"color:{'#94a3b8' if free else '#facc15'};")
        v.addWidget(tier)
        name = QLabel(tr(plan["name"]) if not free else tr("Cơ bản"))
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet(f"font-size:15px;font-weight:700;color:{C['text']};background:transparent;border:none;")
        price = QLabel(fmt_vnd(plan["price"]))
        price.setAlignment(Qt.AlignCenter)
        price.setStyleSheet("font-size:22px;font-weight:800;color:#67e8f9;background:transparent;border:none;")
        days = int(plan.get("days") or 0)
        if free:
            sub_t = tr("Đủ chức năng · mỗi lần 1 tác vụ")
        elif days == 0:
            sub_t = "Dùng mãi mãi, không gia hạn"
        elif days >= 60:
            sub_t = f"≈ {fmt_vnd(round(plan['price'] / (days / 30) / 1000) * 1000)}/tháng"
        else:
            sub_t = f"{days} ngày sử dụng"
        sub = QLabel(sub_t if sub_t.startswith("≈") else tr(sub_t))
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color:{C['text-muted']};font-size:11.5px;background:transparent;border:none;")
        v.addWidget(name)
        v.addWidget(price)
        v.addWidget(sub)
        v.addSpacing(6)
        if free:
            b = _btn("Đang dùng" if current else "Gói cơ bản", "seg", 34)
            b.setEnabled(False)
        else:
            b = _btn("Mua gói này", "primary" if hot else "seg", 34)
            b.clicked.connect(lambda: on_buy(plan))
        v.addWidget(b)


class PayDialog(QDialog):
    """Chuyển khoản VietQR. Máy chủ nhận tiền (SePay) → tự tạo key → phần mềm tự kích hoạt."""

    def __init__(self, parent, lic: License, plan: dict):
        super().__init__(parent)
        self.lic, self.plan, self.key = lic, plan, None
        self.setWindowTitle(f"Thanh toán · {plan['name']}")
        self.setMinimumWidth(440)
        v = QVBoxLayout(self)
        v.setSpacing(8)
        self.title = QLabel(f"Gói {plan['name']} · {fmt_vnd(plan['price'])}")
        self.title.setStyleSheet("font-size:16px;font-weight:700;")
        self.qr = QLabel("Đang tạo mã QR…")
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setFixedSize(320, 320)
        self.qr.setStyleSheet("background:white;border-radius:6px;color:#333;")
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.state = QLabel("Quét mã bằng ứng dụng ngân hàng. Giữ nguyên số tiền và nội dung chuyển khoản.")
        self.state.setWordWrap(True)
        self.state.setObjectName("muted")
        v.addWidget(self.title)
        v.addWidget(self.qr, 0, Qt.AlignHCenter)
        v.addSpacing(6)
        v.addWidget(self.info)
        v.addWidget(self.state)
        h = QHBoxLayout()
        h.addStretch()
        b = _btn("Đóng", "seg", 34)
        b.clicked.connect(self.reject)
        h.addWidget(b)
        v.addLayout(h)
        self.order = None
        self.timer = QTimer(self)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(self._poll)
        run_bg(self, lambda: lic.order(plan["code"]), self._got_order, self._fail)

    def _fail(self, e):
        self.state.setText(f"<span style='color:{C['danger']}'>{getattr(e, 'message', e)}</span>")

    def _got_order(self, o):
        self.order = o
        b = o.get("bank", {})
        self.info.setText(f"<b>{tr('Ngân hàng')}:</b> {b.get('id', '')} · <b>STK:</b> {b.get('account', '')} · {b.get('name', '')}<br>"
                          f"<b>Số tiền:</b> {fmt_vnd(o['amount'])}<br><b>Nội dung:</b> "
                          f"<span style='color:#67e8f9;font-size:15px;font-weight:700'>{o['code']}</span>")

        def load():
            if o.get("qr_payload"):            # tự vẽ mã VietQR từ dữ liệu chuẩn EMVCo của máy chủ (không phụ thuộc web ngoài)
                try:
                    import io
                    import segno
                    buf = io.BytesIO()
                    segno.make(o["qr_payload"], error="m").save(buf, kind="png", scale=8, border=2)
                    return buf.getvalue()
                except Exception:
                    pass
            import urllib.request
            with urllib.request.urlopen(o["qr_url"], timeout=15) as r:
                return r.read()

        def show(data):
            pm = QPixmap()
            pm.loadFromData(data)
            self.qr.setPixmap(pm.scaled(310, 310, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        run_bg(self, load, show, lambda e: self.qr.setText("Không tải được ảnh QR.\nHãy chuyển khoản theo thông tin bên dưới."))
        self.timer.start()

    def _poll(self):
        if not self.order:
            return
        run_bg(self, lambda: self.lic.order_status(self.order["code"]), self._status, lambda e: None)

    def _status(self, s):
        if s.get("status") == "paid" and s.get("key"):
            self.timer.stop()
            self.key = s["key"]
            self.state.setText(f"<span style='color:{C['success']};font-weight:700'>Đã nhận tiền! Đang kích hoạt…</span>")
            QTimer.singleShot(600, self.accept)
        elif s.get("status") == "expired":
            self.timer.stop()
            self.state.setText("Đơn hàng đã hết hạn. Đóng cửa sổ và chọn gói lại.")


class LicenseDialog(QDialog):
    def __init__(self, parent, lic: License, blocking: bool = False):
        super().__init__(parent)
        self.lic, self.blocking = lic, blocking
        self.setWindowTitle(f"Bản quyền · {APP_NAME}")
        self.setMinimumWidth(940)
        self.setStyleSheet(f"QDialog{{background:{C['bg']};}}")
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)

        head = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(QPixmap(str(assets_dir() / "logo.png")).scaled(58, 58, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        head.addWidget(logo)
        tv = QVBoxLayout()
        t = QLabel(f"Bản quyền {APP_NAME}")
        t.setStyleSheet("font-size:20px;font-weight:800;")
        self.status_lbl = QLabel()
        self.status_lbl.setWordWrap(True)
        tv.addWidget(t)
        tv.addWidget(self.status_lbl)
        head.addLayout(tv, 1)
        v.addLayout(head)

        self.grid_box = QWidget()
        self.grid = QGridLayout(self.grid_box)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(12)
        v.addWidget(self.grid_box)
        note = QLabel("<b>Miễn phí</b>: dùng đủ chức năng, đăng nhập nhiều tài khoản, nhưng mỗi lần chỉ tạo <b>1 tác vụ</b> "
                      "(xong tác vụ này mới nhập được prompt tiếp). <b>Chuyên nghiệp</b>: chạy hàng loạt, song song nhiều tài khoản. "
                      "Mua thêm khi còn hạn được <b>cộng dồn</b> thời gian. Mỗi key dùng cho 1 máy.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        v.addWidget(note)

        box = QFrame()
        box.setStyleSheet(f"QFrame{{background:{C['surface']};border:1px solid {C['border']};border-radius:6px;}}"
                          "QLabel{border:none;background:transparent;}")
        bv = QVBoxLayout(box)
        bv.setContentsMargins(16, 12, 16, 14)
        lab = QLabel("Đã có key? Nhập key để kích hoạt / gia hạn")
        lab.setStyleSheet("font-weight:700;")
        bv.addWidget(lab)
        kh = QHBoxLayout()
        self.key_in = QLineEdit()
        self.key_in.setPlaceholderText("VAI-XXXX-XXXX-XXXX-XXXX")
        self.key_in.setMinimumHeight(38)
        self.key_in.setStyleSheet("font-family:Consolas,monospace;font-size:14px;letter-spacing:1px;")
        self.key_in.returnPressed.connect(self._activate)
        self.b_act = _btn("Kích hoạt")
        self.b_act.setMinimumWidth(130)
        self.b_act.clicked.connect(self._activate)
        kh.addWidget(self.key_in, 1)
        kh.addWidget(self.b_act)
        bv.addLayout(kh)
        self.msg = QLabel()
        self.msg.setWordWrap(True)
        bv.addWidget(self.msg)
        v.addWidget(box)

        foot = QHBoxLayout()
        mid = QLabel(f"Mã máy: <span style='font-family:Consolas'>{lic.machine[:8].upper()}…{lic.machine[-6:].upper()}</span>")
        mid.setObjectName("muted")
        b_copy = _btn("Chép mã máy", "seg", 32)
        b_copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(lic.machine),
                                        self._say("Đã chép mã máy.", "info")))
        b_zalo = _btn("Liên hệ Zalo", "seg", 32)
        b_zalo.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self.contact.get("zalo") or lic.contact_zalo)))
        self.b_close = _btn("Thoát phần mềm" if blocking else "Đóng", "seg", 32)
        self.b_close.clicked.connect(self.reject)
        foot.addWidget(mid)
        foot.addWidget(b_copy)
        foot.addStretch()
        foot.addWidget(b_zalo)
        foot.addWidget(self.b_close)
        v.addLayout(foot)

        self.contact = {}
        self.payment = False
        self._show_plans(lic.plans(online=False))
        run_bg(self, lambda: lic.plans(online=True), self._show_plans)
        self._refresh_status()

    # ---------------------------------------------------------------
    def _say(self, text, kind="info"):
        col = {"ok": C["success"], "error": C["danger"], "info": C["info"], "warn": C["warning"]}[kind]
        self.msg.setText(f"<span style='color:{col}'>{text}</span>")

    def _refresh_status(self):
        st: Status = self.lic.status
        if st.tier == "free" and st.reason in ("none", ""):
            self.status_lbl.setText(f"<span style='color:{C['info']};font-weight:600'>● Đang dùng gói Miễn phí "
                                    "(mỗi lần 1 tác vụ). Nâng cấp Chuyên nghiệp để chạy hàng loạt.</span>")
            self.b_close.setText("Đóng")
            if hasattr(self, "_plans_data"):
                self._show_plans(self._plans_data)
            return
        if st.ok:
            col = C["success"]
            txt = st.label() + (f" · key {st.key}" if st.key else "")
            if st.offline:
                txt += " · đang dùng không mạng"
        else:
            col = C["danger"]
            txt = (st.message or "Bản quyền không còn hiệu lực.") + " Đã chuyển về gói Miễn phí."
        self.status_lbl.setText(f"<span style='color:{col};font-weight:600'>● {txt}</span>")
        self.b_close.setText("Đóng")
        if hasattr(self, "_plans_data"):
            self._show_plans(self._plans_data)

    def _show_plans(self, data):
        self._plans_data = data
        self.contact = data.get("contact") or {}
        self.payment = bool(data.get("payment"))
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        plans = [FREE_PLAN] + [p for p in (data.get("plans") or []) if p.get("code") != "free"]
        free_now = self.lic.status.tier == "free"
        for i, p in enumerate(plans):
            self.grid.addWidget(PlanCard(p, self._buy, False, current=(p["code"] == "free" and free_now)), 0, i)

    def _buy(self, plan):
        if self.payment:
            d = PayDialog(self, self.lic, plan)
            if d.exec() and d.key:
                self.key_in.setText(d.key)
                self._activate()
            return
        msg = (f"Chào {self.contact.get('name') or 'anh Huỳnh'}, em muốn mua {APP_NAME} gói {plan['name']} "
               f"({fmt_vnd(plan['price'])}). Mã máy: {self.lic.machine}")
        QGuiApplication.clipboard().setText(msg)
        QDesktopServices.openUrl(QUrl(self.contact.get("zalo") or self.lic.contact_zalo))
        self._say(f"Đã mở Zalo và chép sẵn tin nhắn mua gói <b>{plan['name']}</b> – dán (Ctrl+V) và gửi. "
                  "Nhận key xong, nhập vào ô trên rồi bấm Kích hoạt.", "info")

    def _busy(self, on: bool, text="Đang kiểm tra…"):
        self.b_act.setEnabled(not on)
        if on:
            self._say(text, "info")

    def _activate(self):
        key = self.key_in.text().strip()
        if len(key.replace("-", "").replace(" ", "")) < 12:
            self._say("Hãy nhập đủ key (dạng VAI-XXXX-XXXX-XXXX-XXXX).", "warn")
            return
        self._busy(True, "Đang kích hoạt…")

        def ok(r):
            st, res = r
            self._busy(False)
            if res.get("renewed"):
                self._say(f"Gia hạn thành công: cộng thêm {res.get('added_days') or 'vĩnh viễn'} ngày. {st.label()}.", "ok")
            else:
                self._say(f"Kích hoạt thành công! {st.label()}.", "ok")
            self.key_in.clear()
            self._refresh_status()
        run_bg(self, lambda: self.lic.activate(key), ok, self._err)

    def _err(self, e):
        self._busy(False)
        self._say(getattr(e, "message", None) or str(e), "error")
        self._refresh_status()


__all__ = ["LicenseDialog", "run_bg", "LicenseError"]
