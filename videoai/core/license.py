"""Bản quyền: gói Miễn phí vĩnh viễn (mỗi lần 1 tác vụ) + gói Chuyên nghiệp kích hoạt key online.

Cách hoạt động
- Máy chủ (license-server/, Cloudflare Worker) cấp "giấy phép" = dữ liệu + chữ ký Ed25519.
- Phần mềm chỉ có KHÓA CÔNG KHAI (videoai/license_config.json) nên kiểm tra được chữ ký nhưng
  không tự tạo/sửa được giấy phép → khách không sửa được ngày hết hạn.
- Giấy phép gắn với mã máy (MachineGuid + số serial ổ đĩa, đã băm).
- Kiểm tra lại với máy chủ mỗi 24 giờ; mất mạng vẫn dùng tiếp tối đa 3 ngày.
- Lùi đồng hồ máy để kéo dài thời hạn: bị phát hiện, buộc kiểm tra online.
- Không có key / key hết hạn / bị khóa → tự về gói Miễn phí (không chặn mở phần mềm).

Nếu license_config.json chưa có server_url/public_key (lúc phát triển) thì bản quyền TẮT.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from . import log
from .paths import APP_VERSION, data_dir, package_dir

L = log.get("license")

FREE_PLAN = {"code": "free", "name": "Miễn phí", "days": 0, "price": 0, "badge": "Vĩnh viễn"}
DEFAULT_PLANS = [   # gói Chuyên nghiệp; dùng khi chưa kết nối được máy chủ (giá thật lấy từ máy chủ)
    {"code": "m1", "name": "1 tháng", "days": 30, "price": 80000, "badge": None},
    {"code": "m3", "name": "3 tháng", "days": 90, "price": 220000, "badge": "Phổ biến"},
    {"code": "m6", "name": "6 tháng", "days": 180, "price": 450000, "badge": "Tiết kiệm 30.000đ"},
    {"code": "y1", "name": "1 năm", "days": 365, "price": 900000, "badge": "Tiết kiệm 60.000đ"},
]
FREE_LIMIT_TEXT = "Gói Miễn phí: dùng đủ chức năng, nhiều tài khoản, nhưng mỗi lần chỉ tạo 1 tác vụ."

MESSAGES = {
    "no_network": "Không kết nối được máy chủ bản quyền. Kiểm tra mạng rồi thử lại.",
    "bad_signature": "Giấy phép không hợp lệ.",
    "wrong_machine": "Giấy phép này thuộc máy khác.",
    "expired": "Bản quyền đã hết hạn. Nhập key mới để gia hạn.",
    "trial_expired": "Đã hết thời gian dùng thử. Vui lòng mua key để tiếp tục.",
    "need_online": "Đã quá 3 ngày chưa kiểm tra bản quyền. Hãy kết nối mạng để tiếp tục.",
    "clock": "Đồng hồ máy tính bị lùi. Hãy chỉnh lại ngày giờ và kết nối mạng.",
    "none": "Đang dùng gói Miễn phí (mỗi lần 1 tác vụ).",
}


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _cfg() -> dict:
    try:
        return json.loads((package_dir() / "license_config.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def machine_id(product: str = "videoai") -> str:
    """Mã máy ổn định: không đổi khi cài lại phần mềm, đổi khi sang máy khác."""
    forced = os.environ.get("VIDEOAI_MACHINE_ID")
    if forced:
        return hashlib.sha256(forced.encode()).hexdigest()[:40]
    parts = []
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0,
                                winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                parts.append(winreg.QueryValueEx(k, "MachineGuid")[0])
        except Exception:
            pass
        try:
            import ctypes
            serial = ctypes.c_uint32()
            drive = os.environ.get("SystemDrive", "C:") + "\\"
            if ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(drive), None, 0, ctypes.byref(serial),
                                                            None, None, None, 0):
                parts.append(f"{serial.value:08X}")
        except Exception:
            pass
    else:
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                parts.append(Path(p).read_text().strip())
                break
            except Exception:
                pass
    if not parts:
        parts.append(platform.node())
    raw = f"mrhuynh|{product}|" + "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


@dataclass
class Status:
    ok: bool
    kind: str = ""            # trial | key | dev
    plan: str = ""
    plan_name: str = ""
    exp: int = 0              # 0 = vĩnh viễn
    key: str = ""             # key đã che bớt
    reason: str = ""          # mã lý do khi ok=False
    message: str = ""
    offline: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def tier(self) -> str:
        """pro = Chuyên nghiệp (đủ tính năng); free = Miễn phí vĩnh viễn (mỗi lần 1 tác vụ)."""
        return "pro" if self.ok and self.kind in ("key", "dev") else "free"

    @property
    def lifetime(self) -> bool:
        return self.ok and self.kind == "key" and self.exp == 0

    @property
    def days_left(self) -> int:
        if not self.exp:
            return 10 ** 6
        return max(0, int((self.exp - time.time() + 86399) // 86400))

    def label(self) -> str:
        if self.kind == "dev":
            return "Bản phát triển (đủ tính năng)"
        if self.tier == "free":
            return "Gói Miễn phí"
        if self.lifetime:
            return "Chuyên nghiệp · vĩnh viễn"
        return f"Chuyên nghiệp {self.plan_name} · còn {self.days_left} ngày"


class LicenseError(Exception):
    def __init__(self, code: str, message: str = "", extra: dict | None = None):
        super().__init__(message or MESSAGES.get(code, code))
        self.code = code
        self.message = message or MESSAGES.get(code, code)
        self.extra = extra or {}


class License:
    def __init__(self, store: Path | None = None, cfg: dict | None = None):
        c = cfg if cfg is not None else _cfg()
        self.product = c.get("product") or "videoai"
        self.server = (os.environ.get("VIDEOAI_LICENSE_URL") or c.get("server_url") or "").rstrip("/")
        self.public_key = c.get("public_key") or ""
        self.contact_zalo = c.get("contact_zalo") or "https://zalo.me/0979007367"
        self.contact_phone = c.get("contact_phone") or ""
        self.store = store or (data_dir() / "license.dat")
        self.machine = machine_id(self.product)
        self._plans_cache = self.store.with_name("plans.json")
        self.status = Status(False, reason="none", message=MESSAGES["none"])

    # ------------------------------------------------------------ trạng thái
    @property
    def enabled(self) -> bool:
        return bool(self.server and self.public_key)

    def _read(self) -> dict:
        try:
            raw = base64.b64decode(self.store.read_bytes())
            data = bytes(b ^ 0x5A for b in raw)
            return json.loads(data.decode())
        except Exception:
            return {}

    def _write(self, d: dict):
        self.store.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(d).encode()
        self.store.write_bytes(base64.b64encode(bytes(b ^ 0x5A for b in data)))

    def _verify(self, token: str) -> dict:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        try:
            body, sig = token.split(".", 1)
            Ed25519PublicKey.from_public_bytes(_b64d(self.public_key)).verify(_b64d(sig), body.encode())
            payload = json.loads(_b64d(body))
        except (ValueError, InvalidSignature, json.JSONDecodeError) as e:
            raise LicenseError("bad_signature") from e
        if payload.get("p") != self.product:
            raise LicenseError("bad_signature")
        if payload.get("m") != self.machine:
            raise LicenseError("wrong_machine")
        return payload

    def _status_from(self, payload: dict, offline=False) -> Status:
        exp = int(payload.get("exp") or 0)
        kind = payload.get("kind", "")
        if exp and exp <= time.time():
            code = "trial_expired" if kind == "trial" else "expired"
            return Status(False, kind=kind, plan=payload.get("plan", ""), plan_name=payload.get("plan_name", ""),
                          exp=exp, key=payload.get("key", ""), reason=code, message=MESSAGES[code])
        return Status(True, kind=kind, plan=payload.get("plan", ""), plan_name=payload.get("plan_name", ""),
                      exp=exp, key=payload.get("key", ""), offline=offline)

    def local(self) -> Status:
        """Kiểm tra giấy phép đã lưu, không cần mạng."""
        if not self.enabled:
            self.status = Status(True, kind="dev", plan_name="Bản phát triển")
            return self.status
        d = self._read()
        tok = d.get("token")
        if not tok:
            self.status = Status(False, reason="none", message=MESSAGES["none"])
            return self.status
        try:
            payload = self._verify(tok)
        except LicenseError as e:
            self.status = Status(False, reason=e.code, message=e.message)
            return self.status
        t = time.time()
        st = self._status_from(payload)
        if st.ok:
            if t + 3600 < float(d.get("seen") or 0):
                st = Status(False, kind=st.kind, reason="clock", message=MESSAGES["clock"])
            elif t > int(payload.get("chk", 0)) + int(payload.get("grace", 3 * 86400)):
                st = Status(False, kind=st.kind, exp=st.exp, reason="need_online", message=MESSAGES["need_online"])
            else:
                d["seen"] = max(t, float(d.get("seen") or 0))
                self._write(d)
        self.status = st
        return st

    def due_check(self) -> bool:
        d = self._read()
        try:
            payload = self._verify(d["token"])
            return time.time() >= int(payload.get("chk", 0))
        except Exception:
            return True

    # ------------------------------------------------------------ máy chủ
    def _post(self, path: str, body: dict, timeout: float = 15) -> dict:
        data = json.dumps({"product": self.product, "machine": self.machine, "app_version": APP_VERSION, **body}).encode()
        req = urllib.request.Request(self.server + path, data=data, method="POST",
                                     headers={"content-type": "application/json",
                                              "user-agent": f"VideoAI/{APP_VERSION}"})
        return self._send(req, timeout)

    def _get(self, path: str, timeout: float = 15) -> dict:
        req = urllib.request.Request(self.server + path, headers={"user-agent": f"VideoAI/{APP_VERSION}"})
        return self._send(req, timeout)

    @staticmethod
    def _send(req, timeout) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                j = json.loads(e.read().decode())
            except Exception:
                raise LicenseError("no_network", f"Máy chủ bản quyền lỗi ({e.code}).") from e
            raise LicenseError(j.get("code", "error"), j.get("message", ""), j) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise LicenseError("no_network") from e

    def _accept(self, res: dict) -> Status:
        payload = self._verify(res["token"])          # luôn tự kiểm tra chữ ký của máy chủ
        d = self._read()
        d["token"] = res["token"]
        if res.get("full_key"):
            d["key"] = res["full_key"]
        elif payload.get("kind") == "trial":
            d.pop("key", None)
        d["seen"] = max(time.time(), float(d.get("seen") or 0))
        self._write(d)
        self.status = self._status_from(payload)
        return self.status

    def activate(self, key: str) -> tuple[Status, dict]:
        key = "".join(key.split()).upper()
        res = self._post("/v1/activate", {"key": key})
        return self._accept(res), res

    def refresh(self, timeout: float = 15) -> Status:
        """Kiểm tra lại với máy chủ. Mất mạng: giữ trạng thái theo giấy phép đã lưu (còn trong 3 ngày cho phép)."""
        if not self.enabled:
            return self.local()
        d = self._read()
        if not d.get("token") or not d.get("key"):     # gói Miễn phí: không cần hỏi máy chủ
            return self.local()
        try:
            res = self._post("/v1/check", {"key": d.get("key") or ""}, timeout=timeout)
            return self._accept(res)
        except LicenseError as e:
            if e.code == "no_network":
                st = self.local()
                st.offline = True
                return st
            if e.code in ("revoked", "moved", "expired", "bad_key", "trial_expired"):
                d.pop("token", None)
                self._write(d)
                self.status = Status(False, reason=e.code, message=e.message)
                return self.status
            raise

    def startup(self) -> Status:
        """Gọi khi mở phần mềm: dùng giấy phép đã lưu, quá hạn kiểm tra thì hỏi máy chủ."""
        st = self.local()
        if not self.enabled:
            return st
        if st.ok and not self.due_check():
            return st
        if st.reason in ("none",):
            return st
        try:
            return self.refresh(timeout=8)
        except LicenseError as e:
            self.status = Status(False, reason=e.code, message=e.message)
            return self.status

    # ------------------------------------------------------------ bảng giá & mua
    def plans(self, online: bool = True) -> dict:
        if online and self.enabled:
            try:
                j = self._get(f"/v1/plans?product={self.product}", timeout=8)
                self._plans_cache.parent.mkdir(parents=True, exist_ok=True)
                self._plans_cache.write_text(json.dumps(j, ensure_ascii=False), encoding="utf-8")
                return j
            except LicenseError:
                pass
        try:
            return json.loads(self._plans_cache.read_text(encoding="utf-8"))
        except Exception:
            return {"plans": DEFAULT_PLANS, "payment": False,
                    "contact": {"zalo": self.contact_zalo, "phone": self.contact_phone}}

    def order(self, plan: str) -> dict:
        return self._post("/v1/order", {"plan": plan})

    def order_status(self, code: str) -> dict:
        return self._get(f"/v1/order?code={code}&machine={self.machine}", timeout=10)


def fmt_vnd(n: int) -> str:
    return f"{int(n):,}".replace(",", ".") + "đ"
