"""Bản quyền: kiểm thử phía phần mềm + máy chủ thật (Cloudflare Worker chạy cục bộ bằng `wrangler dev`).
Phần chạy với máy chủ chỉ chạy khi có biến VIDEOAI_LICENSE_TEST_URL (vd http://localhost:8799)."""
import base64
import json
import os
import time
import urllib.request
import uuid

import pytest

URL = os.environ.get("VIDEOAI_LICENSE_TEST_URL", "")
ADMIN = os.environ.get("VIDEOAI_LICENSE_TEST_ADMIN", "admin-test-123456")
# Máy chủ PHP trên hosting: trang quản trị ở /admin/api.php?a=…, webhook SePay dùng khóa của Voice AI
ADMIN_URL = os.environ.get("VIDEOAI_LICENSE_TEST_ADMIN_URL", "")
SEPAY_KEY = os.environ.get("VIDEOAI_LICENSE_TEST_SEPAY", "sepaytest")
need_server = pytest.mark.skipif(not URL, reason="cần máy chủ bản quyền cục bộ")


def _cfg():
    from videoai.core.license import _cfg
    from pathlib import Path
    c = dict(_cfg())
    c["server_url"] = URL
    jwk = Path(__file__).resolve().parent.parent / "license-server" / ".signing_key.jwk"
    if jwk.exists():   # khóa công khai khớp với máy chủ cục bộ đang chạy
        c["public_key"] = json.loads(jwk.read_text())["x"]
    return c


def _lic(tmp_path, machine):
    os.environ["VIDEOAI_MACHINE_ID"] = machine
    from videoai.core.license import License
    return License(store=tmp_path / f"{machine}.dat", cfg=_cfg())


def _admin(path, body=None):
    target = f"{ADMIN_URL}{path}" if ADMIN_URL else f"{URL}/admin/api/{path}"
    req = urllib.request.Request(target, method="POST" if body is not None else "GET",
                                 data=json.dumps(body or {}).encode() if body is not None else None,
                                 headers={"x-admin-token": ADMIN, "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def test_dev_mode_when_not_configured(tmp_path):
    from videoai.core.license import License
    lic = License(store=tmp_path / "x.dat", cfg={"product": "videoai"})
    assert not lic.enabled and lic.local().ok and lic.status.kind == "dev"


def test_tampered_token_rejected(tmp_path):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from videoai.core.license import License
    from cryptography.hazmat.primitives import serialization
    k = Ed25519PrivateKey.generate()
    pub = base64.urlsafe_b64encode(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).rstrip(b"=").decode()
    os.environ["VIDEOAI_MACHINE_ID"] = "may-test-1"
    lic = License(store=tmp_path / "t.dat", cfg={"product": "videoai", "server_url": "http://127.0.0.1:9", "public_key": pub})
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    payload = {"p": "videoai", "m": lic.machine, "kind": "key", "plan": "m1", "exp": int(time.time()) + 86400,
               "iat": int(time.time()), "chk": int(time.time()) + 86400, "grace": 3 * 86400}
    body = b64(json.dumps(payload).encode())
    tok = body + "." + b64(k.sign(body.encode()))
    lic._write({"token": tok})
    assert lic.local().ok
    # khách sửa ngày hết hạn → chữ ký sai
    payload["exp"] += 10 * 365 * 86400
    body2 = b64(json.dumps(payload).encode())
    lic._write({"token": body2 + "." + tok.split(".")[1]})
    st = lic.local()
    assert not st.ok and st.reason == "bad_signature"
    # chép giấy phép sang máy khác
    lic._write({"token": tok})
    os.environ["VIDEOAI_MACHINE_ID"] = "may-khac"
    lic2 = License(store=tmp_path / "t.dat", cfg={"product": "videoai", "server_url": "http://127.0.0.1:9", "public_key": pub})
    assert lic2.local().reason == "wrong_machine"
    # quá hạn kiểm tra + 3 ngày không mạng
    os.environ["VIDEOAI_MACHINE_ID"] = "may-test-1"
    payload = {**payload, "exp": 0, "chk": int(time.time()) - 4 * 86400}
    body3 = b64(json.dumps(payload).encode())
    lic._write({"token": body3 + "." + b64(k.sign(body3.encode()))})
    assert lic.local().reason == "need_online"
    # mất mạng khi kiểm tra: không làm mất giấy phép đang còn hạn
    payload = {**payload, "chk": int(time.time()) - 3600}
    body4 = b64(json.dumps(payload).encode())
    lic._write({"token": body4 + "." + b64(k.sign(body4.encode())), "key": "VAI-X"})
    st = lic.refresh(timeout=2)
    assert st.ok and st.offline and st.lifetime and st.tier == "pro"


@need_server
def test_free_then_buy_renew_transfer_revoke(tmp_path):
    from videoai.core.license import LicenseError
    m1, m2 = "pc-" + uuid.uuid4().hex, "pc-" + uuid.uuid4().hex
    lic = _lic(tmp_path, m1)
    st = lic.local()
    assert st.tier == "free" and st.label() == "Gói Miễn phí"           # không có key = gói Miễn phí vĩnh viễn
    assert lic.refresh().tier == "free"                                  # không hỏi máy chủ khi chưa có key
    plans = lic.plans()
    assert [(p["code"], p["price"]) for p in plans["plans"]] == [("m1", 80000), ("m3", 220000), ("m6", 450000), ("y1", 900000)]

    k1 = _admin("create", {"plan": "m1", "customer": "test"})["keys"][0]
    with pytest.raises(LicenseError) as e:
        lic.activate("VAI-SAI0-SAI0-SAI0-SAI0")
    assert e.value.code == "bad_key"
    st, _ = lic.activate(k1.lower().replace("-", " - "))     # gõ chữ thường, có khoảng trắng vẫn nhận
    assert st.tier == "pro" and 29 <= st.days_left <= 30 and st.plan_name == "1 tháng"
    # gia hạn cộng dồn: thêm key 3 tháng → 30 + 90
    k2 = _admin("create", {"plan": "m3"})["keys"][0]
    st, res = lic.activate(k2)
    assert res.get("renewed") and 119 <= st.days_left <= 120
    assert lic.refresh().days_left == st.days_left
    with pytest.raises(LicenseError) as e:
        _lic(tmp_path, m2).activate(k2)
    assert e.value.code == "used"

    lic_b = _lic(tmp_path, m2)
    st_b, _ = lic_b.activate(k1)
    assert st_b.tier == "pro" and 119 <= st_b.days_left <= 120
    os.environ["VIDEOAI_MACHINE_ID"] = m1
    st_old = lic.refresh()
    assert st_old.tier == "free" and st_old.reason == "moved"           # máy cũ về gói Miễn phí
    with pytest.raises(LicenseError) as e:
        lic.activate(k1)
    assert e.value.code == "transfer_cooldown"
    _admin("reset_machine", {"key": k1})
    assert lic.activate(k1)[0].tier == "pro"
    _admin("revoke", {"key": k1})
    st = lic.refresh()
    assert st.tier == "free" and st.reason == "revoked"


@need_server
def test_payment_webhook(tmp_path):
    m = "pc-" + uuid.uuid4().hex
    lic = _lic(tmp_path, m)
    o = lic.order("y1")
    assert o["amount"] == 900000 and o["code"].startswith("VAI") and "img.vietqr.io" in o["qr_url"]
    assert lic.order_status(o["code"])["status"] == "pending"
    hook = lambda body, key=SEPAY_KEY: urllib.request.urlopen(urllib.request.Request(
        f"{URL}/v1/sepay", method="POST", data=json.dumps(body).encode(),
        headers={"authorization": f"Apikey {key}", "content-type": "application/json"}), timeout=10)
    with pytest.raises(urllib.error.HTTPError):
        hook({"content": o["code"], "transferAmount": 900000}, key="sai")
    hook({"id": 1001, "transferType": "in", "content": f"MBVCB.123 {o['code']} chuyen tien", "transferAmount": 500000})
    assert lic.order_status(o["code"])["status"] in ("pending", "review")   # chuyển thiếu tiền: chưa cấp key
    bid = int(time.time() * 1000)
    hook({"id": bid, "transferType": "in", "content": f"{o['code'].lower()} thanh toan", "transferAmount": 900000})
    hook({"id": bid, "transferType": "in", "content": f"{o['code']}", "transferAmount": 900000})   # SePay gửi lại
    s = lic.order_status(o["code"])
    assert s["status"] == "paid" and s["key"]
    st, _ = lic.activate(s["key"])
    assert st.tier == "pro" and 364 <= st.days_left <= 365


import urllib.error  # noqa: E402


def test_license_dialog_offline(qapp, tmp_path):
    from videoai.core.license import License
    from videoai.ui.license_ui import LicenseDialog, PlanCard
    os.environ["VIDEOAI_MACHINE_ID"] = "ui-test"
    lic = License(store=tmp_path / "u.dat", cfg={"product": "videoai", "server_url": "http://127.0.0.1:9", "public_key": "x"})
    lic.local()
    d = LicenseDialog(None, lic, blocking=True)
    cards = d.findChildren(PlanCard)
    assert len(cards) == 5                                    # Miễn phí + 4 gói Chuyên nghiệp
    assert d.b_close.text() == "Đóng"
    d.close()


@need_server
def test_guides_from_admin(tmp_path):
    _admin("guides", {"guides": {"flow_image": "https://www.youtube.com/watch?v=img1", "flow_video": "https://youtu.be/vid2"}})
    lic = _lic(tmp_path, "pc-" + uuid.uuid4().hex)
    g = lic.guides()
    assert g["flow_image"].endswith("img1") and g["flow_video"].endswith("vid2")
    lic.server = "http://127.0.0.1:9"                      # mất mạng → dùng bản đã lưu
    assert lic.guides()["flow_video"].endswith("vid2")
