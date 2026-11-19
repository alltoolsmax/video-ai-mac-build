"""Chuẩn bị gói tải lên hosting (cPanel) cho máy chủ bản quyền Video AI + trang quản trị chung với Voice AI.

Chạy bằng hosting\\chuan-bi-hosting.bat. Làm:
 1. Tạo (hoặc dùng lại) khóa ký giấy phép Video AI → ghi khóa công khai + địa chỉ máy chủ vào phần mềm.
 2. Tạo thư mục hosting\\upload\\ gồm đúng 2 thư mục để tải lên + file config.php đã điền sẵn
    (seed ký, mật khẩu quản trị ngẫu nhiên) + file zip để tải lên cho nhanh.
Chạy lại lúc nào cũng được: khóa ký và mật khẩu cũ được giữ nguyên.
"""
from __future__ import annotations

import json
import secrets
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOST = ROOT / "hosting"
OUT = HOST / "upload"
STATE = HOST / ".hosting_state.json"


def main():
    st = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    dom = (sys.argv[1] if len(sys.argv) > 1 else st.get("domain") or "").strip()
    if not dom:
        dom = input("Tên miền máy chủ bản quyền (Enter = active.mrhuynh.net): ").strip() or "active.mrhuynh.net"
    dom = dom.replace("https://", "").replace("http://", "").strip("/")
    st["domain"] = dom
    st.setdefault("admin_password", secrets.token_urlsafe(18))
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    url = f"https://{dom}/video"
    subprocess.run([sys.executable, str(ROOT / "tools" / "make_license_keys.py"), url], check=True)
    seed = (HOST / "video_seed.hex").read_text().strip()

    if OUT.exists():
        shutil.rmtree(OUT)
    pub = OUT / dom
    priv = OUT / "active_private" / "video"
    shutil.copytree(HOST / "active.mrhuynh.net", pub)
    priv.mkdir(parents=True)
    shutil.copy(HOST / "active_private" / "video" / "lib.php", priv / "lib.php")
    shutil.copy(HOST / "active_private" / "video" / "config.example.php", priv / "config.example.php")
    cfg = (HOST / "active_private" / "video" / "config.example.php").read_text(encoding="utf-8")
    cfg = cfg.replace("DAN_NOI_DUNG_video_seed.hex_VAO_DAY", seed).replace("DAT_MAT_KHAU_QUAN_TRI_DAI", st["admin_password"])
    (priv / "config.php").write_text(cfg, encoding="utf-8")
    for d in ("data", "logs"):
        (priv / d).mkdir()
        (priv / d / ".htaccess").write_text("Require all denied\n")
    shutil.copy(HOST / "HUONG-DAN-HOSTING.txt", OUT / "HUONG-DAN-HOSTING.txt")
    z = OUT / "VideoAI-hosting-upload.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in OUT.rglob("*"):
            if f.is_file() and f != z:
                zf.write(f, f.relative_to(OUT))
    # Gói CẬP NHẬT: chỉ mã nguồn, KHÔNG có config.php / data / logs → giải nén đè lên hosting đang chạy không mất gì
    zu = OUT / "VideoAI-hosting-update.zip"
    skip = {"config.php", "HUONG-DAN-HOSTING.txt"}
    with zipfile.ZipFile(zu, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in OUT.rglob("*"):
            rel = f.relative_to(OUT)
            if not f.is_file() or f.suffix == ".zip" or f.name in skip or rel.parts[-2:-1] in (("data",), ("logs",)):
                continue
            zf.write(f, rel)

    print("\n" + "=" * 66)
    print(" XONG. Gói tải lên hosting nằm ở:  hosting\\upload\\")
    print(f"   {dom}\\                 → tải vào thư mục gốc của subdomain {dom}")
    print("   active_private\\video\\   → tải vào thư mục active_private (đã có của Voice AI)")
    print(f"   (hoặc dùng file zip: hosting\\upload\\{z.name})")
    print(f"   Hosting ĐÃ CÀI rồi, chỉ cập nhật mã: tải hosting\\upload\\{zu.name} lên thư mục chính rồi Extract")
    print("")
    print(f" Trang quản trị chung : https://{dom}/admin/")
    print(f" Mật khẩu quản trị    : {st['admin_password']}")
    print(f" Máy chủ Video AI     : {url}   (đã ghi vào phần mềm)")
    print(f" Webhook SePay chung  : https://{dom}/webhook.php")
    print("")
    print(" Bước tiếp: làm theo hosting\\upload\\HUONG-DAN-HOSTING.txt, rồi chạy 'build Windows.bat'.")
    print(" GIỮ BÍ MẬT: hosting\\video_seed.hex, hosting\\.hosting_state.json, license-server\\.signing_key.jwk")
    print("=" * 66)


if __name__ == "__main__":
    main()
