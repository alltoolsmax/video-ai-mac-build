"""Điền lại videoai/license_config.json trước khi build (khi bị chép đè bằng bản trống từ mã nguồn mới).

Lấy khóa công khai từ license-server/.signing_key.jwk và tên miền từ hosting/.hosting_state.json
(hai file này chỉ có trên máy bạn, tạo bởi chuan-bi-hosting.bat). Không đụng tới khóa bí mật.
Thoát mã 0 = đã có đủ thông tin bản quyền; 1 = chưa có (bản build sẽ là "Bản phát triển").
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "videoai" / "license_config.json"
JWK = ROOT / "license-server" / ".signing_key.jwk"
STATE = ROOT / "hosting" / ".hosting_state.json"


def main() -> int:
    cfg = json.loads(CFG.read_text(encoding="utf-8")) if CFG.exists() else {"product": "videoai"}
    changed = False
    if not cfg.get("public_key") and JWK.exists():
        cfg["public_key"] = json.loads(JWK.read_text())["x"]
        changed = True
    if not cfg.get("server_url") and STATE.exists():
        dom = (json.loads(STATE.read_text(encoding="utf-8")).get("domain") or "").strip().strip("/")
        if dom:
            cfg["server_url"] = f"https://{dom}/video"
            changed = True
    if changed:
        CFG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        print("   Da dien lai thong tin ban quyen: " + str(cfg.get("server_url")))   # chữ không dấu: console Windows
    return 0 if cfg.get("server_url") and cfg.get("public_key") else 1


if __name__ == "__main__":
    sys.exit(main())
