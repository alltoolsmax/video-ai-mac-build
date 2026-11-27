"""Điểm vào của SYNC API trong Video AI: kho key, cửa sổ + khay hệ thống, API HTTP, và gắn key cho tài khoản."""
from __future__ import annotations

import time

from PySide6.QtCore import QObject, Qt

from ..core import log
from ..core.cookies import session_expiry
from ..core.platforms import platform_url
from .store import SyncKeyError, SyncStore

L = log.get("syncapi")
DEFAULT_PORT = 8788               # 8787 là cổng mặc định của Webhook API


class SyncApi(QObject):
    def __init__(self, db, engine, win=None):
        super().__init__(win)
        self.db, self.engine, self.win = db, engine, win
        self.store = SyncStore(db)
        self.http = None
        self._tray = None
        self._applied: dict[str, tuple] = {}      # account_id -> ((key, hash cookie), thời điểm nạp gần nhất)

    # ---------- cấu hình ----------
    def url_for_platform(self, platform: str) -> str:
        return platform_url(self.db, platform)

    @property
    def port(self) -> int:
        try:
            return int(self.db.get_setting("sync_api_port", DEFAULT_PORT))
        except (TypeError, ValueError):
            return DEFAULT_PORT

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.http.port}/v1" if self.http and self.http.running() else ""

    # ---------- API HTTP ----------
    def start_http(self) -> bool:
        if self.http and self.http.running():
            return True
        from .server import SyncHttpServer
        self.http = SyncHttpServer(self.db, self.engine, self.store)
        try:
            self.http.start(self.port)
            return True
        except OSError as e:
            L.warning("SYNC API: không mở được cổng %s (%s) – API cho ứng dụng khác tạm tắt, phần còn lại vẫn dùng được",
                      self.port, e)
            return False

    def shutdown(self):
        if self.http:
            self.http.stop()
        if self._tray:
            self._tray.hide()

    # ---------- cửa sổ + khay hệ thống ----------
    def tray(self):
        if self._tray is None:
            from .window import SyncApiTray
            self._tray = SyncApiTray(self)
            self._tray.open_requested.connect(self._open_from_tray)
        return self._tray

    def account_labels(self, key: str) -> list[str]:
        out = []
        for aid in self.store.accounts_of(key):
            row = self.db.one("SELECT label FROM accounts WHERE id=?", (aid,))
            if row:
                out.append(row["label"])
        return out

    def open_window(self, platform: str | None = None, key: str | None = None, lock: bool = False, parent=None):
        """Mở cửa sổ SYNC API (không chặn). Trả về cửa sổ để nối tín hiệu key_copied."""
        from .window import SyncApiWindow, modal_parent
        parent = parent or modal_parent(self.win)
        w = SyncApiWindow(self.store, platform, key, lock, parent, self.base_url, self.account_labels)
        w.setWindowModality(Qt.WindowModal if parent is not None else Qt.NonModal)
        w.saved.connect(self._on_saved)
        w.key_copied.connect(lambda _k: self.tray().show(announce=True))
        self.tray().show()
        w.show()
        w.raise_()
        w.activateWindow()
        return w

    def _open_from_tray(self):
        from .window import modal_parent
        parent = modal_parent(self.win)
        w = self.open_window(parent=parent)
        got = getattr(parent, "sync_key_copied", None)     # khung nhập API Key đang mở → điền key vào đó
        if callable(got):
            w.key_copied.connect(got)

    # ---------- gắn key cho tài khoản ----------
    def apply_key(self, account: dict, key: str) -> list[str]:
        """Gắn API key cho tài khoản: nạp cookie của key vào hồ sơ trình duyệt của tài khoản rồi tự kiểm tra
        (cùng đường với «Dán cookie»). Trả về cảnh báo. Key lạ / khác nền tảng → SyncKeyError."""
        e = self.store.get(key)
        if not e:
            raise SyncKeyError("API key này không có trong SYNC API. Bấm «Lấy API Key» để tạo.")
        if e["platform"] != account["platform"]:
            raise SyncKeyError("API key này thuộc nền tảng khác với tài khoản.")
        cookies, warns, text = self.store.cookies(key)
        self.store.link(account["id"], key)
        # Bấm Lưu trong SYNC API rồi OK ở khung API Key gọi vào đây hai lần liền nhau: lần nạp thứ hai mở lại trình duyệt
        # của tài khoản khi lần kiểm tra thứ nhất còn đang chạy → lỗi "page has been closed" trong log. Cùng key + cùng
        # cookie trong 20 giây thì không nạp lại.
        mark = (key, hash(text))
        last = self._applied.get(account["id"])
        if last and last[0] == mark and time.monotonic() - last[1] < 20:
            return warns
        self._applied[account["id"]] = (mark, time.monotonic())
        self.db.set_account_cookie(account["id"], text, session_expiry(cookies, account["platform"]))
        self.db.update_account(account["id"], status="unknown")
        self.engine.paste_cookies(account, cookies, self.url_for_platform(account["platform"]))
        return warns

    def _on_saved(self, key: str):
        """Cookie của một key vừa đổi → nạp lại cho các tài khoản đang gắn key đó."""
        for aid in self.store.accounts_of(key):
            acc = self.db.one("SELECT * FROM accounts WHERE id=?", (aid,))
            if not acc:
                self.store.unlink(aid)
                continue
            try:
                self.apply_key(acc, key)
            except SyncKeyError as e:
                L.warning("SYNC API: không nạp lại được cookie cho %s: %s", acc["label"], e)


def get(ctx) -> SyncApi:
    """SyncApi dùng chung của cửa sổ chính (tạo khi cần)."""
    s = getattr(ctx, "sync_api", None)
    if s is None:
        s = SyncApi(ctx.db, ctx.engine, ctx.win)
        ctx.sync_api = s
    return s
