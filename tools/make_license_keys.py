"""Tạo cặp khóa ký giấy phép (Ed25519).

- Khóa BÍ MẬT  → license-server/.signing_key.jwk  (chỉ đưa lên Cloudflare, KHÔNG gửi ai, KHÔNG đưa vào phần mềm)
- Khóa CÔNG KHAI → videoai/license_config.json   (gắn vào phần mềm để kiểm tra chữ ký)

Chạy 1 lần duy nhất. Nếu tạo lại, mọi giấy phép đã cấp sẽ không còn hợp lệ cho tới khi
phần mềm của khách kiểm tra lại với máy chủ (khách cần bản phần mềm mới có khóa công khai mới).
"""
import base64
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parent.parent
SECRET = ROOT / "license-server" / ".signing_key.jwk"
SEED_HEX = ROOT / "hosting" / "video_seed.hex"      # dán vào active_private/video/config.php (seed_hex) trên hosting
CFG = ROOT / "videoai" / "license_config.json"


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _server_installed(url: str) -> bool:
    """Hosting đã cài máy chủ Video AI (trả lời bảng giá) → đã có khóa ký trên đó."""
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/v1/plans", headers={"User-Agent": "VideoAI-build"}), timeout=15) as r:
            return bool(json.loads(r.read().decode("utf-8")).get("plans"))
    except Exception:
        return False


def main():
    force = "--force" in sys.argv
    sys.path.insert(0, str(ROOT / "tools"))
    import build_secrets
    build_secrets.restore()                     # thư mục mới: lấy lại khóa đã sao lưu ở %APPDATA%
    url = sys.argv[1].rstrip("/") if len(sys.argv) > 1 and sys.argv[1].startswith("http") else ""
    if not SECRET.exists() and not force and url:
        from fill_license_config import server_pubkey
        if server_pubkey(url) or _server_installed(url):
            print("LOI: hosting DA CO khoa ky nhung tren may nay khong con file license-server\\.signing_key.jwk.")
            print("     KHONG tao khoa moi (se lam hong moi key da ban). Hay chep lai file .signing_key.jwk cu,")
            print("     hoac chi cap nhat hosting bang VideoAI-hosting-update.zip (khong can khoa).")
            sys.exit(2)
    if SECRET.exists() and not force:
        print(f"Đã có khóa: {SECRET} (dùng --force để tạo lại)")
        priv = json.loads(SECRET.read_text())
        pub = priv["x"]
    else:
        k = Ed25519PrivateKey.generate()
        d = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        x = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        pub = b64u(x)
        SECRET.write_text(json.dumps({"kty": "OKP", "crv": "Ed25519", "d": b64u(d), "x": pub}))
        print(f"Đã tạo khóa bí mật: {SECRET}")
    d_raw = base64.urlsafe_b64decode(json.loads(SECRET.read_text())["d"] + "==")
    SEED_HEX.parent.mkdir(parents=True, exist_ok=True)
    SEED_HEX.write_text(d_raw.hex())
    print(f"Đã ghi seed cho hosting PHP: {SEED_HEX}  (64 ký tự hex – giữ bí mật)")
    cfg = json.loads(CFG.read_text(encoding="utf-8")) if CFG.exists() else {}
    cfg["public_key"] = pub
    if len(sys.argv) > 1 and sys.argv[1].startswith("http"):
        cfg["server_url"] = sys.argv[1].rstrip("/")
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Đã ghi khóa công khai vào {CFG}")
    build_secrets.backup()


if __name__ == "__main__":
    main()
