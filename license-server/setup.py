"""Cài máy chủ bản quyền lên Cloudflare (miễn phí) — chạy bằng setup.bat.

Làm lần lượt:
 1. Tạo cặp khóa ký giấy phép (khóa công khai ghi vào phần mềm).
 2. Đăng nhập Cloudflare (mở trình duyệt, bạn tự đăng nhập/đăng ký).
 3. Tạo cơ sở dữ liệu D1 + bảng.
 4. Đặt mật khẩu quản trị, khóa ký (bí mật trên Cloudflare).
 5. (Tuỳ chọn) bật thanh toán tự động VietQR + SePay.
 6. Đưa máy chủ lên mạng, ghi địa chỉ vào videoai/license_config.json.
Chạy lại lúc nào cũng được: bước nào đã làm sẽ bỏ qua.
"""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
TOML = HERE / "wrangler.toml"
CFG = ROOT / "videoai" / "license_config.json"
STATE = HERE / ".setup_state.json"
DB_NAME = "mrhuynh-license"


def say(t=""):
    print(t, flush=True)


def run(cmd, capture=True, input_text=None, check=True):
    say(f"  > {cmd}")
    p = subprocess.run(cmd, cwd=HERE, shell=True, text=True, encoding="utf-8", errors="replace",
                       input=input_text, capture_output=capture)
    out = (p.stdout or "") + (p.stderr or "")
    if check and p.returncode != 0:
        say(out[-3000:])
        raise SystemExit(f"\nLỖI khi chạy: {cmd}\nXem thông báo phía trên, sửa rồi chạy lại setup.bat.")
    return out


def state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(d):
    STATE.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def set_toml_value(text: str, key: str, value: str) -> str:
    pat = re.compile(rf'^({re.escape(key)}\s*=\s*)"[^"]*"', re.M)
    if not pat.search(text):
        raise SystemExit(f"Không thấy {key} trong wrangler.toml")
    return pat.sub(lambda m: f'{m.group(1)}"{value}"', text, count=1)


def parse_db_id(out: str) -> str | None:
    m = re.search(r'database_id\s*=\s*"([0-9a-f-]{36})"', out) or re.search(r'"database_id"\s*:\s*"([0-9a-f-]{36})"', out)
    if m:
        return m.group(1)
    m = re.search(r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b", out)
    return m.group(1) if m else None


def parse_worker_url(out: str) -> str | None:
    m = re.search(r"https://[a-z0-9.-]+\.workers\.dev", out)
    return m.group(0) if m else None


def main():
    st = state()
    say("=" * 64)
    say(" MÁY CHỦ BẢN QUYỀN · Video AI - Mr. Huỳnh  (Cloudflare, miễn phí)")
    say("=" * 64)

    say("\n[1/6] Khóa ký giấy phép")
    run(f'"{sys.executable}" "{ROOT / "tools" / "make_license_keys.py"}"', capture=False)
    jwk = (HERE / ".signing_key.jwk").read_text().strip()

    say("\n[2/6] Đăng nhập Cloudflare")
    who = run("npx wrangler whoami", check=False)
    if "not authenticated" in who.lower() or "You are not" in who:
        say("  Trình duyệt sẽ mở: đăng nhập (hoặc đăng ký miễn phí) Cloudflare rồi bấm Allow.")
        run("npx wrangler login", capture=False)
    else:
        say("  Đã đăng nhập.")

    say("\n[3/6] Cơ sở dữ liệu D1")
    toml = TOML.read_text(encoding="utf-8")
    if "DIEN_ID_SAU_KHI_TAO" in toml:
        out = run(f"npx wrangler d1 create {DB_NAME}", check=False)
        dbid = parse_db_id(out)
        if not dbid:
            out = run("npx wrangler d1 list --json", check=False)
            try:
                dbid = next(d["uuid"] for d in json.loads(out[out.index("["):]) if d.get("name") == DB_NAME)
            except Exception:
                say(out[-2000:])
                raise SystemExit("Không tạo/không tìm được cơ sở dữ liệu D1.")
        toml = toml.replace("DIEN_ID_SAU_KHI_TAO", dbid)
        TOML.write_text(toml, encoding="utf-8")
        say(f"  database_id = {dbid}")
    run(f"npx wrangler d1 execute {DB_NAME} --remote --yes --file schema.sql")

    say("\n[4/6] Bí mật: khóa ký + mật khẩu quản trị")
    if not st.get("admin_token"):
        st["admin_token"] = secrets.token_urlsafe(15)
        save_state(st)
    run("npx wrangler secret put SIGNING_KEY", input_text=jwk + "\n")
    run("npx wrangler secret put ADMIN_TOKEN", input_text=st["admin_token"] + "\n")

    say("\n[5/6] Thanh toán tự động (VietQR + SePay) — có thể bỏ qua, bật sau")
    if "--payment" in sys.argv:          # chạy từ bat-thanh-toan-tu-dong.bat: hỏi lại để bật / đổi tài khoản nhận tiền
        st.pop("payment_asked", None)
    if not st.get("payment_asked"):
        ans = "c" if "--payment" in sys.argv else input("  Bật thanh toán tự động ngay bây giờ? (c/K): ").strip().lower()
        if ans in ("c", "co", "có", "y", "yes"):
            bank = input("  Mã ngân hàng (MB, VCB, TCB, ACB, VPB, BIDV, ...): ").strip().upper()
            acc = input("  Số tài khoản nhận tiền: ").strip()
            name = input("  Tên chủ tài khoản (KHÔNG dấu, vd HUYNH XUYEN SON): ").strip().upper()
            st["sepay_key"] = st.get("sepay_key") or secrets.token_urlsafe(18)
            toml = TOML.read_text(encoding="utf-8")
            toml = set_toml_value(toml, "BANK_ID", bank)
            toml = set_toml_value(toml, "BANK_ACCOUNT", acc)
            toml = set_toml_value(toml, "BANK_NAME", name)
            TOML.write_text(toml, encoding="utf-8")
            run("npx wrangler secret put SEPAY_API_KEY", input_text=st["sepay_key"] + "\n")
        st["payment_asked"] = True
        save_state(st)

    say("\n[6/6] Đưa máy chủ lên mạng")
    out = run("npx wrangler deploy")
    url = parse_worker_url(out) or st.get("url")
    if not url:
        say(out[-2000:])
        url = input("  Không đọc được địa chỉ máy chủ, hãy dán địa chỉ https://....workers.dev: ").strip()
    st["url"] = url.rstrip("/")
    save_state(st)
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    cfg["server_url"] = st["url"]
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    say("\n" + "=" * 64)
    say(" XONG! Ghi lại các thông tin sau (cũng lưu trong license-server\\.setup_state.json):")
    say(f"   Trang quản trị : {st['url']}/admin")
    say(f"   Mật khẩu       : {st['admin_token']}")
    if st.get("sepay_key"):
        say("")
        say("   ---- KHAI BÁO TRONG SEPAY (my.sepay.vn › Tích hợp WebHooks › Thêm webhook) ----")
        say(f"   Gọi đến URL    : {st['url']}/v1/sepay")
        say("   Sự kiện        : Có tiền vào")
        say("   Chứng thực     : API Key")
        say(f"   API Key        : {st['sepay_key']}")
        say("   Kiểu nội dung  : application/json")
        say("   (Nếu SePay hỏi cấu trúc mã thanh toán: tiền tố VAI, độ dài 9 ký tự)")
    say("   Địa chỉ máy chủ đã ghi vào videoai\\license_config.json")
    say("\n Bước tiếp theo: chạy 'build Windows.bat' để build phần mềm có bản quyền.")
    say(" GIỮ BÍ MẬT file license-server\\.signing_key.jwk và .setup_state.json – không gửi cho ai.")
    say("=" * 64)


if __name__ == "__main__":
    main()
