"""API HTTP cục bộ của SYNC API (chỉ nghe 127.0.0.1), kiểu OpenAI, cho ứng dụng khác dùng API key của tài khoản.

Header: Authorization: Bearer <API key>     (API key xác định luôn nền tảng + tài khoản Video AI đã gắn key đó)
  GET  /v1/models
  POST /v1/images/generations   {"prompt", "n", "size" | "ratio", "model", "quality", "images": [base64…], "response_format"}
  POST /v1/videos/generations   {"prompt", "ratio", "model", "quality", "images": [base64…]}            (Flow, Grok, Muse)
  POST /v1/chat/completions     {"messages": [...]}                                                      (Chat GPT)
  GET  /files/<mã>              tệp kết quả (địa chỉ trả trong "url")
Mỗi yêu cầu tạo là một tác vụ trong hàng đợi của chính engine Video AI, ghim vào tài khoản của key (không chuyển tài
khoản khác), nên chạy đúng như khi bấm Chạy trong ứng dụng: cùng trình duyệt ẩn, cùng giới hạn, cùng cách báo lỗi.
"""
from __future__ import annotations

import base64
import json
import re
import secrets
import shutil
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import gcd
from pathlib import Path

from ..core import log
from ..core.errors import JobError, friendly
from ..core.paths import default_output_dir
from ..core.platforms import PAGE_BY_KEY
from ..services.llm import CHAT_PLATFORMS
from .store import SyncStore

L = log.get("syncapi")

IMAGE_PAGE = {"flow": "flow_image", "gpt": "gpt_image", "grok": "grok_image", "muse": "muse_image"}
VIDEO_PAGE = {"flow": "flow_video", "grok": "grok_video", "muse": "meta_muse"}
TERMINAL = ("done", "failed", "blocked", "cancelled")
MAX_BODY = 96 * 1024 * 1024            # ảnh tham chiếu gửi dạng base64 trong JSON
MAX_IMAGE = 25 * 1024 * 1024
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
        ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
EXT_OF = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


class ApiError(Exception):
    def __init__(self, status: int, message: str, code: str | None = None):
        super().__init__(message)
        self.status, self.message, self.code = status, message, code

    def body(self) -> dict:
        return {"error": {"message": self.message, "code": self.code,
                          "type": "server_error" if self.status >= 500 else "invalid_request_error"}}


def aspect(size) -> str:
    """"1536x1024" → "3:2" ('' nếu không đúng dạng)."""
    m = re.fullmatch(r"(\d{2,5})x(\d{2,5})", str(size or ""))
    if not m:
        return ""
    w, h = int(m.group(1)), int(m.group(2))
    if not w or not h:
        return ""
    d = gcd(w, h)
    return f"{w // d}:{h // d}"


def decode_image(v, n: int) -> tuple[bytes, str]:
    """Ảnh gửi qua API: data URL, chuỗi base64, hoặc {"base64", "contentType"} → (dữ liệu, đuôi tệp)."""
    mime = ""
    if isinstance(v, dict):
        mime, v = str(v.get("contentType") or ""), v.get("base64")
    if not isinstance(v, str) or not v:
        raise ApiError(400, f"Ảnh #{n}: phải là data URL, chuỗi base64 hoặc {{base64, contentType}}", "bad_image")
    m = re.match(r"^data:([^;,]*)(;base64)?,", v)
    if m:
        if not m.group(2):
            raise ApiError(400, f"Ảnh #{n}: data URL phải là base64", "bad_image")
        mime, v = m.group(1), v[m.end():]
    try:
        data = base64.b64decode(v, validate=False)
    except Exception as e:
        raise ApiError(400, f"Ảnh #{n}: base64 không hợp lệ", "bad_image") from e
    if not data or len(data) > MAX_IMAGE:
        raise ApiError(400, f"Ảnh #{n}: rỗng hoặc lớn hơn 25 MB", "bad_image")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        ext = ".png"
    elif data[:3] == b"\xff\xd8\xff":
        ext = ".jpg"
    elif data[8:12] == b"WEBP":
        ext = ".webp"
    else:
        ext = EXT_OF.get(mime.lower())
        if not ext:
            raise ApiError(400, f"Ảnh #{n}: chỉ nhận PNG, JPEG, WEBP", "bad_image")
    return data, ext


class SyncHttpServer:
    def __init__(self, db, engine, store: SyncStore):
        self.db, self.engine, self.store = db, engine, store
        self.httpd: ThreadingHTTPServer | None = None
        self.port = 0
        self._files: dict[str, Path] = {}
        self._lock = threading.Lock()

    def running(self) -> bool:
        return self.httpd is not None

    # ------------------------------------------------------------------ nghiệp vụ
    def account_for(self, entry: dict) -> dict:
        for aid in self.store.accounts_of(entry["key"]):
            a = self.db.one("SELECT * FROM accounts WHERE id=?", (aid,))
            if a and a["enabled"] and a["platform"] == entry["platform"]:
                return a
        raise ApiError(409, "API key này chưa gắn với tài khoản nào đang bật trong Video AI "
                            "(Cài Đặt › Tài khoản › Thêm tài khoản → dán key này).", "key_not_linked")

    def models(self, entry: dict) -> dict:
        out = []
        for kind, table in (("image", IMAGE_PAGE), ("video", VIDEO_PAGE)):
            p = PAGE_BY_KEY.get(table.get(entry["platform"], ""))
            if p and p.ready:
                out.append({"id": p.key, "object": "model", "owned_by": "sync-api", "kind": kind, "label": p.label,
                            "models": p.models, "ratios": [r.split(" ")[0] for r in p.ratios], "max_n": p.max_count})
        if entry["platform"] in CHAT_PLATFORMS:
            out.append({"id": "chat", "object": "model", "owned_by": "sync-api", "kind": "chat"})
        return {"object": "list", "data": out}

    def _file_url(self, path: Path) -> str:
        token = secrets.token_hex(16) + path.suffix.lower()        # không đoán được: /files/ không cần API key
        with self._lock:
            self._files[token] = path
        return f"http://127.0.0.1:{self.port}/files/{token}"

    def _save_refs(self, images, tmp: Path) -> list[str]:
        if images is None:
            return []
        if not isinstance(images, list):
            raise ApiError(400, '"images" phải là mảng', "bad_image")
        if len(images) > 10:
            raise ApiError(400, "Tối đa 10 ảnh tham chiếu", "bad_image")
        refs = []
        for n, v in enumerate(images, 1):
            data, ext = decode_image(v, n)
            f = tmp / f"ref_{n}{ext}"
            f.write_bytes(data)
            refs.append(str(f))
        return refs

    def generate(self, entry: dict, kind: str, body: dict) -> dict:
        plat = entry["platform"]
        pdef = PAGE_BY_KEY.get((VIDEO_PAGE if kind == "video" else IMAGE_PAGE).get(plat, ""))
        if not pdef or not pdef.ready:
            raise ApiError(400, f"API key này (nền tảng {plat}) không tạo được {'video' if kind == 'video' else 'ảnh'}"
                                + (" – tài khoản Gemini chỉ dùng cho AI Agent (/chat/completions)." if plat == "gemini" else "."),
                           "unsupported")
        acc = self.account_for(entry)
        prompt = body.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ApiError(400, 'Thiếu "prompt"', "bad_input")
        try:
            n = max(1, min(pdef.max_count, int(body.get("n", 1))))
        except (TypeError, ValueError):
            raise ApiError(400, '"n" phải là số', "bad_input") from None
        params = {k: v for k, v in body["params"].items() if isinstance(k, str) and not k.startswith("_")
                  and k != "pin_account"} if isinstance(body.get("params"), dict) else {}
        want = str(body.get("ratio") or "").strip() or aspect(body.get("size"))
        if want:
            full = next((r for r in pdef.ratios if r.split(" ")[0] == want), None)
            if not full:
                raise ApiError(400, f"Tỷ lệ {want} không có ở {pdef.label}. Chọn: "
                                    + ", ".join(r.split(" ")[0] for r in pdef.ratios), "bad_ratio")
            params["ratio"] = full
        if body.get("model") in pdef.models:
            params["model"] = body["model"]
        if body.get("quality") in (pdef.extra.get("quality") or []):
            params["quality"] = body["quality"]
        params["pin_account"] = acc["id"]

        images = body.get("images")
        if images is None and body.get("image") is not None:
            images = [body["image"]]
        tmp = Path(tempfile.mkdtemp(prefix="syncapi-"))
        keep_tmp = False
        try:
            refs = self._save_refs(images, tmp)
            modes = [m.key for m in pdef.modes]
            mode = ("i2v" if refs and "i2v" in modes else "t2v" if "t2v" in modes else modes[0]) if kind == "video" else modes[0]
            try:
                timeout = float(body.get("timeoutSec") or (900 if kind == "video" else 420))
            except (TypeError, ValueError):
                raise ApiError(400, '"timeoutSec" phải là số', "bad_input") from None
            timeout = max(30.0, min(3600.0, timeout))
            save_dir = default_output_dir() / "sync_api" / pdef.key
            bid = self.db.create_batch(plat, pdef.key, params, str(save_dir), "flat",
                                       [{"mode": mode, "prompt": prompt.strip()[:4000], "refs": refs, "count": n}],
                                       source="webhook")
            self.engine.ensure_page(pdef.key, acc["id"])
            L.info("SYNC API: %s · %s · tài khoản %s · batch %s", pdef.label, mode, acc["label"], bid)
            end = time.monotonic() + timeout
            job = None
            while time.monotonic() < end:
                job = self.db.one("SELECT * FROM jobs WHERE batch_id=?", (bid,))
                if job and job["status"] in TERMINAL:
                    break
                time.sleep(0.5)
            else:
                self.db.execute("UPDATE jobs SET status='cancelled' WHERE batch_id=? AND status IN ('queued','needs_user')", (bid,))
                keep_tmp = True                # tác vụ đang chạy dở vẫn cần ảnh tham chiếu
                st = job["status"] if job else "?"
                hint = " Tài khoản đang chờ bạn xác minh trong trình duyệt." if st == "needs_user" else ""
                raise ApiError(504, f"Quá {int(timeout)} giây chưa có kết quả (trạng thái: {st}).{hint}", "timeout")
            if job["status"] != "done":
                code = job["error_code"] or job["status"]
                raise ApiError(502, (job["error_text"] or friendly(job["error_code"]))[:500], code)
            outs = [Path(o["path"]) for o in self.db.outputs(job["id"]) if Path(o["path"]).exists()]
            if not outs:
                raise ApiError(502, "Tác vụ xong nhưng không thấy tệp kết quả", "no_media")
            b64 = body.get("response_format") == "b64_json"
            data = []
            for p in outs:
                item = {"b64_json": base64.b64encode(p.read_bytes()).decode()} if b64 else {"url": self._file_url(p)}
                item["path"] = str(p)
                data.append(item)
            return {"created": int(time.time()), "data": data}
        finally:
            if not keep_tmp:
                shutil.rmtree(tmp, ignore_errors=True)

    def chat(self, entry: dict, body: dict) -> str:
        if entry["platform"] not in CHAT_PLATFORMS:
            raise ApiError(400, "Chỉ API key của tài khoản Chat GPT hoặc Gemini dùng được /chat/completions.", "unsupported")
        acc = self.account_for(entry)
        msgs = body.get("messages")
        if not isinstance(msgs, list) or not msgs:
            raise ApiError(400, 'Thiếu "messages"', "bad_input")
        system, turns, images = [], [], []
        for m in msgs:
            if not isinstance(m, dict):
                continue
            c = m.get("content")
            parts = [{"type": "text", "text": c}] if isinstance(c, str) else c if isinstance(c, list) else []
            text = "\n".join(p["text"] for p in parts if isinstance(p, dict) and p.get("type") == "text"
                             and isinstance(p.get("text"), str)).strip()
            for p in parts:
                u = p.get("image_url", {}).get("url") if isinstance(p, dict) and p.get("type") == "image_url" \
                    and isinstance(p.get("image_url"), dict) else None
                if u:
                    images.append(u)
            if not text:
                continue
            if m.get("role") == "system":
                system.append(text)
            else:
                turns.append(f"[Câu trả lời trước của bạn]\n{text}" if m.get("role") == "assistant" else text)
        if not turns:
            raise ApiError(400, "Không có nội dung người dùng trong messages", "bad_input")
        try:
            timeout = int(max(30, min(1800, float(body.get("timeoutSec") or 240))))
        except (TypeError, ValueError):
            raise ApiError(400, '"timeoutSec" phải là số', "bad_input") from None
        want_json = isinstance(body.get("response_format"), dict) and body["response_format"].get("type") == "json_object"
        tmp = Path(tempfile.mkdtemp(prefix="syncapi-"))
        try:
            files = self._save_refs(images, tmp)
            sys_text = "\n\n".join(system) or "Bạn là trợ lý."
            if want_json:
                fut = self.engine.ask_ai(acc, sys_text, "\n\n".join(turns), timeout_s=timeout, files=files or None, want_json=True)
            else:
                fut = self.engine.ask_ai(acc, sys_text, "\n\n".join(turns), timeout_s=timeout, files=files or None)
            try:
                out = fut.result(timeout=2 * timeout + 180)
            except JobError as e:
                raise ApiError(502, (e.detail or e.friendly)[:500], e.code) from e
            except TimeoutError as e:
                fut.cancel()
                raise ApiError(504, "Chat GPT không trả lời kịp", "timeout") from e
            except Exception as e:
                raise ApiError(502, str(e)[:500] or type(e).__name__, "unknown") from e
            if not (out or "").strip():
                raise ApiError(502, "Chat GPT không trả lời", "no_reply")
            return out
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    # ------------------------------------------------------------------ HTTP
    def start(self, port: int) -> None:
        if self.httpd:
            return
        srv = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *a):
                L.info("%s %s", self.address_string(), fmt % a)

            def _send(self, code: int, obj=None, raw: bytes | None = None, ctype: str = "application/json; charset=utf-8"):
                b = raw if raw is not None else json.dumps(obj, ensure_ascii=False).encode()
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(b)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(b)

            def _host_ok(self) -> bool:
                # chặn trang web khác gọi vào qua DNS rebinding: chỉ nhận Host là chính địa chỉ cục bộ này
                if self.headers.get("Host", "") in (f"127.0.0.1:{srv.port}", f"localhost:{srv.port}"):
                    return True
                self._send(403, ApiError(403, "Host không hợp lệ", "forbidden").body())
                return False

            def _entry(self) -> dict:
                tok = re.sub(r"(?i)^Bearer\s+", "", self.headers.get("Authorization", "")).strip()
                e = srv.store.find(tok) if tok else None
                if not e:
                    raise ApiError(401, "Sai hoặc thiếu API key (Authorization: Bearer <key>)", "invalid_api_key")
                return e

            def do_GET(self):
                if not self._host_ok():
                    return
                try:
                    if self.path.startswith("/files/"):
                        with srv._lock:
                            p = srv._files.get(self.path[7:])
                        if not p or not p.exists():
                            raise ApiError(404, "Không tìm thấy tệp", "not_found")
                        return self._send(200, raw=p.read_bytes(), ctype=MIME.get(p.suffix.lower(), "application/octet-stream"))
                    if self.path == "/v1/models":
                        return self._send(200, srv.models(self._entry()))
                    raise ApiError(404, "Không tìm thấy endpoint này", "not_found")
                except ApiError as e:
                    self._send(e.status, e.body())

            def do_POST(self):
                if not self._host_ok():
                    return
                try:
                    entry = self._entry()
                    try:
                        n = int(self.headers.get("Content-Length") or 0)
                    except ValueError:
                        n = -1
                    if n < 0 or n > MAX_BODY:
                        self.close_connection = True
                        raise ApiError(413, "Body quá lớn", "too_large")
                    if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
                        self.rfile.read(n)
                        raise ApiError(415, "Cần Content-Type: application/json (ảnh gửi dạng base64 trong JSON)", "bad_input")
                    try:
                        body = json.loads(self.rfile.read(n) or b"{}")
                    except Exception:
                        raise ApiError(400, "Body không phải JSON hợp lệ", "bad_input") from None
                    if not isinstance(body, dict):
                        raise ApiError(400, "Body phải là một object JSON", "bad_input")
                    if self.path in ("/v1/images/generations", "/v1/images/edits"):
                        return self._send(200, srv.generate(entry, "image", body))
                    if self.path == "/v1/videos/generations":
                        return self._send(200, srv.generate(entry, "video", body))
                    if self.path == "/v1/chat/completions":
                        text = srv.chat(entry, body)
                        cid, created = "chatcmpl-" + secrets.token_hex(12), int(time.time())
                        model = body.get("model") if isinstance(body.get("model"), str) else "chat"
                        if body.get("stream") is True:
                            chunks = [{"role": "assistant", "content": text}, {}]
                            raw = "".join("data: " + json.dumps({"id": cid, "object": "chat.completion.chunk", "created": created,
                                                                 "model": model, "choices": [{"index": 0, "delta": d,
                                                                 "finish_reason": None if d else "stop"}]}, ensure_ascii=False) + "\n\n"
                                          for d in chunks) + "data: [DONE]\n\n"
                            return self._send(200, raw=raw.encode(), ctype="text/event-stream; charset=utf-8")
                        return self._send(200, {"id": cid, "object": "chat.completion", "created": created, "model": model,
                                                "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                                             "finish_reason": "stop"}],
                                                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
                    raise ApiError(404, "Không tìm thấy endpoint này", "not_found")
                except ApiError as e:
                    self._send(e.status, e.body())
                except Exception as e:
                    L.exception("SYNC API %s", self.path)
                    self._send(500, ApiError(500, f"{type(e).__name__}: {str(e)[:300]}", "internal").body())

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, name="syncapi-http", daemon=True).start()
        L.info("SYNC API đang lắng nghe http://127.0.0.1:%s/v1", self.port)

    def stop(self) -> None:
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            L.info("Đã tắt SYNC API")
