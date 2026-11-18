"""Webhook API cục bộ (127.0.0.1) để n8n / Make / script khác gửi tác vụ vào hàng đợi.

POST /api/jobs                 {"page":"flow_video","prompts":[...],"mode":"t2v","count":1,"params":{...},"callback_url":"..."}
GET  /api/jobs/<batch_id>      trạng thái + file kết quả
POST /api/jobs/<batch_id>/cancel
GET  /api/pages                danh sách trang hợp lệ
Header bắt buộc: Authorization: Bearer <token>   (token xem trong trang Webhook API)
"""
from __future__ import annotations

import json
import secrets
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ..core import log
from ..core.db import Database
from ..core.paths import default_output_dir
from ..core.platforms import PAGE_BY_KEY

L = log.get("webhook")


class WebhookServer:
    def __init__(self, db: Database, engine):
        self.db = db
        self.engine = engine
        self.httpd: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self._watch: dict[str, str] = {}   # batch_id -> callback url

    @property
    def token(self) -> str:
        t = self.db.get_setting("webhook_token")
        if not t:
            t = secrets.token_urlsafe(24)
            self.db.set_setting("webhook_token", t)
        return t

    def regenerate_token(self) -> str:
        self.db.set_setting("webhook_token", secrets.token_urlsafe(24))
        return self.token

    def running(self) -> bool:
        return self.httpd is not None

    def start(self, port: int) -> None:
        if self.httpd:
            return
        srv = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, fmt, *a):
                L.info("%s %s", self.address_string(), fmt % a)

            def _send(self, code, obj):
                b = json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def _auth(self):
                if self.headers.get("Authorization", "") != f"Bearer {srv.token}":
                    self._send(401, {"error": "unauthorized"})
                    return False
                return True

            def do_GET(self):
                if not self._auth():
                    return
                if self.path == "/api/pages":
                    return self._send(200, [{"page": p.key, "label": p.label, "modes": [m.key for m in p.modes]}
                                            for p in PAGE_BY_KEY.values()])
                if self.path.startswith("/api/jobs/"):
                    return self._send(200, srv.batch_status(self.path.split("/")[3]))
                self._send(404, {"error": "not found"})

            def do_POST(self):
                if not self._auth():
                    return
                n = int(self.headers.get("Content-Length") or 0)
                if n > 2_000_000:
                    return self._send(413, {"error": "body quá lớn"})
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                except Exception:
                    return self._send(400, {"error": "invalid json"})
                if self.path == "/api/jobs":
                    try:
                        return self._send(201, srv.create(body))
                    except ValueError as e:
                        return self._send(400, {"error": str(e)})
                if self.path.startswith("/api/jobs/") and self.path.endswith("/cancel"):
                    bid = self.path.split("/")[3]
                    srv.db.execute("UPDATE jobs SET status='cancelled' WHERE batch_id=? AND status IN ('queued','needs_user')", (bid,))
                    return self._send(200, {"ok": True})
                self._send(404, {"error": "not found"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        threading.Thread(target=self._callback_loop, daemon=True).start()
        L.info("Webhook đang lắng nghe http://127.0.0.1:%s", port)

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            L.info("Đã tắt webhook")

    def create(self, body: dict) -> dict:
        page = body.get("page")
        pdef = PAGE_BY_KEY.get(page)
        if not pdef:
            raise ValueError("page không hợp lệ")
        prompts = [str(p) for p in body.get("prompts", []) if str(p).strip()]
        if not prompts:
            raise ValueError("prompts trống")
        mode = body.get("mode") or pdef.modes[0].key
        if mode not in {m.key for m in pdef.modes}:
            raise ValueError("mode không hợp lệ cho trang này")
        acc_id = body.get("account_id")
        if not acc_id:
            accs = [a for a in self.db.accounts(pdef.platform) if a["enabled"]]
            if not accs:
                raise ValueError("chưa có tài khoản cho nền tảng này")
            acc_id = accs[0]["id"]
        save_dir = body.get("save_dir") or str(default_output_dir() / pdef.key)
        if len(prompts) > 1000:
            raise ValueError("tối đa 1000 prompt mỗi lần")
        count = max(1, min(PAGE_BY_KEY[page].max_count, int(body.get("count", 1))))
        refs = [str(r) for r in body.get("refs", []) if isinstance(r, str)][:10]
        rows = [{"mode": mode, "prompt": p[:4000], "refs": refs, "count": count} for p in prompts]
        bid = self.db.create_batch(pdef.platform, pdef.key, body.get("params", {}), save_dir, "per_task", rows, source="webhook")
        conc = int(self.db.get_setting("webhook_concurrency", 1))
        self.engine.start_page(pdef.key, acc_id, conc, tuple(self.db.get_setting("default_delay", [5, 10])))
        if body.get("callback_url"):
            self._watch[bid] = body["callback_url"]
        return {"batch_id": bid, "jobs": len(rows)}

    def batch_status(self, bid: str) -> dict:
        jobs = self.db.query("SELECT id,row_no,prompt,status,progress,error_code FROM jobs WHERE batch_id=? ORDER BY row_no", (bid,))
        for j in jobs:
            j["files"] = [o["path"] for o in self.db.outputs(j["id"])]
        done = all(j["status"] in ("done", "failed", "blocked", "cancelled") for j in jobs) if jobs else False
        return {"batch_id": bid, "finished": done, "jobs": jobs}

    def _callback_loop(self):
        import time
        while self.httpd:
            for bid, url in list(self._watch.items()):
                st = self.batch_status(bid)
                if st["finished"]:
                    try:
                        req = urllib.request.Request(url, data=json.dumps(st, ensure_ascii=False).encode(),
                                                     headers={"Content-Type": "application/json"})
                        urllib.request.urlopen(req, timeout=20)
                    except Exception as e:
                        L.warning("callback %s lỗi: %s", url, e)
                    self._watch.pop(bid, None)
            time.sleep(3)
