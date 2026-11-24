"""Cầu nối cục bộ (127.0.0.1) giữa Tools và Tiện ích Chrome "Video AI · Mr. Huỳnh".

Tiện ích KHÔNG tự tạo video và KHÔNG lách kiểm tra của Google — nó chỉ theo dõi trạng thái Tools
(kết nối, đăng nhập Flow, số tác vụ, reCAPTCHA) và gửi lệnh Tạm dừng / Tiếp tục.

Mọi endpoint chỉ nghe trên 127.0.0.1 và yêu cầu token (trừ /ext/ping và /ext/onboard).

  GET  /ext/ping                      {ok, app, version}
  GET  /ext/status?token=             trạng thái đầy đủ (kết nối, counts, flow, recaptcha, logs, paused)
  POST /ext/command   {action}        action: pause | resume | reconnect
  POST /ext/flow      {logged_in,recaptcha,url}   content.js trên flow.google.com báo về
  POST /ext/onboarded {ok}            người dùng bấm "Đã đăng nhập xong" trong trang hướng dẫn
  GET  /ext/onboard                   trang hướng dẫn cài tiện ích + đăng nhập (HTML, cùng thương hiệu)
"""
from __future__ import annotations

import collections
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..core import log
from ..core.db import Database
from ..core.paths import APP_VERSION

L = log.get("ext")

PORT_RANGE = range(47817, 47838)


class ExtBridge:
    def __init__(self, db: Database, engine):
        self.db = db
        self.engine = engine
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.port = 0
        self._logs: collections.deque = collections.deque(maxlen=120)
        self._flow_recaptcha_until = 0.0        # content.js báo reCAPTCHA (còn hiệu lực vài giây)
        self._flow_logged_in_hint: bool | None = None
        self.on_onboarded = None                # callback app đặt: người dùng đã đăng nhập xong
        log.add_listener(self._on_log)

    # ---------------------------------------------------------------- token
    @property
    def token(self) -> str:
        t = self.db.get_setting("ext_token")
        if not t:
            t = secrets.token_urlsafe(18)
            self.db.set_setting("ext_token", t)
        return t

    def regenerate_token(self) -> str:
        self.db.set_setting("ext_token", secrets.token_urlsafe(18))
        return self.token

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}" if self.port else ""

    # ---------------------------------------------------------------- logs
    def _on_log(self, msg: str, levelno: int):
        lvl = "err" if levelno >= 40 else ("warn" if levelno >= 30 else ("ok" if " xong" in msg or "✓" in msg else ""))
        # "12:00:00  INFO    videoai.flow: ..." -> giờ + phần nội dung
        t, _, rest = msg.partition("  ")
        body = rest.split(": ", 1)[-1] if ": " in rest else rest
        self._logs.append({"t": t.strip()[:8], "level": lvl, "msg": body.strip()[:160]})

    # ---------------------------------------------------------------- status
    def _counts(self) -> dict:
        rows = self.db.query("SELECT status, COUNT(*) n FROM jobs GROUP BY status")
        by = {r["status"]: r["n"] for r in rows}
        return {
            "queued": by.get("queued", 0) + by.get("needs_user", 0),
            "running": by.get("running", 0),
            "done": by.get("done", 0),
            "failed": by.get("failed", 0) + by.get("blocked", 0),
        }

    def _flow_logged_in(self) -> int:
        try:
            return self.db.one("SELECT COUNT(*) n FROM accounts WHERE platform IN ('flow','gvids','gpics') "
                               "AND enabled=1 AND status='ok'")["n"]
        except Exception:
            return 0

    def status(self) -> dict:
        recaptcha = bool(getattr(self.engine, "needs_user", False)) or time.time() < self._flow_recaptcha_until
        return {
            "app": "VideoAI-MrHuynh",
            "version": APP_VERSION,
            "paused": bool(getattr(self.engine, "paused", False)),
            "recaptcha": recaptcha,
            "flow_logged_in": self._flow_logged_in(),
            "counts": self._counts(),
            "logs": list(self._logs),
        }

    # ---------------------------------------------------------------- commands
    def command(self, action: str) -> dict:
        if action == "pause":
            self.engine.paused = True
        elif action == "resume":
            self.engine.paused = False
        elif action == "reconnect":
            pass                      # kết nối do tiện ích tự thử lại; ở đây chỉ xác nhận còn sống
        else:
            return {"ok": False, "error": "unknown action"}
        L.info("Trợ lý Chrome: %s", {"pause": "Tạm dừng hàng đợi", "resume": "Tiếp tục hàng đợi",
                                     "reconnect": "Kết nối lại"}.get(action, action))
        return {"ok": True, "paused": self.engine.paused}

    def mark_flow(self, logged_in: bool, recaptcha: bool):
        self._flow_logged_in_hint = logged_in
        if recaptcha:
            self._flow_recaptcha_until = time.time() + 12

    # ---------------------------------------------------------------- server
    def start(self) -> int:
        if self.httpd:
            return self.port
        bridge = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")

            def _send(self, code, obj, ctype="application/json; charset=utf-8"):
                b = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self._cors()
                self.end_headers()
                try:
                    self.wfile.write(b)
                except Exception:
                    pass

            def _auth(self) -> bool:
                from urllib.parse import urlparse, parse_qs
                q = parse_qs(urlparse(self.path).query)
                tok = (q.get("token", [""])[0]) or self.headers.get("X-Ext-Token", "")
                return secrets.compare_digest(tok, bridge.token)

            def _body(self) -> dict:
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                    return json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    return {}

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path == "/ext/ping":
                    return self._send(200, {"ok": True, "app": "VideoAI-MrHuynh", "version": APP_VERSION})
                if path == "/ext/onboard":
                    return self._send(200, bridge._onboard_html().encode(), "text/html; charset=utf-8")
                if path == "/ext/status":
                    if not self._auth():
                        return self._send(401, {"ok": False, "error": "token sai"})
                    return self._send(200, bridge.status())
                return self._send(404, {"ok": False, "error": "not found"})

            def do_POST(self):
                path = self.path.split("?", 1)[0]
                if not self._auth():
                    return self._send(401, {"ok": False, "error": "token sai"})
                data = self._body()
                if path == "/ext/command":
                    return self._send(200, bridge.command(str(data.get("action", ""))))
                if path == "/ext/flow":
                    bridge.mark_flow(bool(data.get("logged_in")), bool(data.get("recaptcha")))
                    return self._send(200, {"ok": True})
                if path == "/ext/onboarded":
                    if callable(bridge.on_onboarded):
                        try:
                            bridge.on_onboarded()
                        except Exception as e:
                            L.warning("onboarded callback lỗi: %s", e)
                    return self._send(200, {"ok": True})
                return self._send(404, {"ok": False, "error": "not found"})

        last = None
        for port in PORT_RANGE:
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
                self.port = port
                break
            except OSError as e:
                last = e
                self.httpd = None
        if not self.httpd:
            raise RuntimeError(f"Không mở được cổng cho Trợ lý Chrome: {last}")
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="ext-bridge", daemon=True)
        self.thread.start()
        L.info("Trợ lý Chrome: đang lắng nghe %s", self.base_url)
        return self.port

    def stop(self):
        if self.httpd:
            try:
                self.httpd.shutdown()
            except Exception:
                pass
            self.httpd = None

    # ---------------------------------------------------------------- trang hướng dẫn
    def _onboard_html(self) -> str:
        from .ext_onboard import ONBOARD_HTML
        return ONBOARD_HTML.replace("__TOKEN__", self.token).replace("__BASE__", self.base_url).replace("__VER__", APP_VERSION)
