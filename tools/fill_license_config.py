"""Điền videoai/license_config.json trước khi build — kể cả khi bạn xóa thư mục cũ và giải nén mã mới ra thư mục mới.

Thứ tự:
1. Chép lại các file riêng đã sao lưu ở %APPDATA%\\VideoAI-MrHuynh-build (tools/build_secrets.py).
2. Địa chỉ máy chủ: file cấu hình → .hosting_state.json → mặc định https://active.mrhuynh.net/video
3. Khóa công khai: HỎI THẲNG MÁY CHỦ (<server_url>/v1/pubkey) — luôn khớp với seed trên hosting;
   không kết nối được thì dùng khóa trong file / .signing_key.jwk.
4. Đủ thông tin → sao lưu lại ra %APPDATA%.
Thoát mã 0 = đủ thông tin bản quyền; 1 = thiếu (bản build sẽ là "Bản phát triển").
Chỉ in chữ không dấu (console Windows).
"""
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_secrets  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "videoai" / "license_config.json"
JWK = ROOT / "license-server" / ".signing_key.jwk"
STATE = ROOT / "hosting" / ".hosting_state.json"
DEFAULT_SERVER = "https://active.mrhuynh.net/video"


def server_pubkey(server: str) -> str | None:
    try:
        req = urllib.request.Request(server.rstrip("/") + "/v1/pubkey", headers={"User-Agent": "VideoAI-build"})
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.loads(r.read().decode("utf-8"))
        k = (d.get("public_key") or "").strip()
        return k if len(k) >= 40 else None
    except Exception as e:
        print("   (Khong hoi duoc khoa cong khai tu may chu: %s)" % str(e)[:120])
        return None


def main() -> int:
    got = build_secrets.restore()
    if got:
        print("   Da lay lai tu ban sao luu: " + ", ".join(got))
    cfg = json.loads(CFG.read_text(encoding="utf-8")) if CFG.exists() else {"product": "videoai"}
    if not cfg.get("server_url"):
        dom = ""
        if STATE.exists():
            dom = (json.loads(STATE.read_text(encoding="utf-8")).get("domain") or "").strip().strip("/")
        cfg["server_url"] = f"https://{dom}/video" if dom else DEFAULT_SERVER
    key = server_pubkey(cfg["server_url"])
    if key:
        if cfg.get("public_key") and cfg["public_key"] != key:
            print("   CHU Y: khoa cong khai cu KHAC khoa tren may chu -> dung khoa cua may chu.")
        cfg["public_key"] = key
    elif not cfg.get("public_key") and JWK.exists():
        cfg["public_key"] = json.loads(JWK.read_text())["x"]
    CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = bool(cfg.get("server_url") and cfg.get("public_key"))
    if ok:
        build_secrets.backup()
        print("   Da dien thong tin ban quyen: " + cfg["server_url"] + ("  (khoa lay tu may chu)" if key else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
