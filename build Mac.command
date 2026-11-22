#!/bin/bash
# BUILD VIDEO AI - MR. HUYNH cho macOS: bấm đúp file này trong Finder (hoặc chạy: bash "build Mac.command").
# Kết quả: dist/VideoAI-MrHuynh-<phiên bản>-mac.dmg  +  dist/downloads-mac-upload.zip (tải lên mrhuynh.net/downloads)
cd "$(dirname "$0")" || exit 1
APP="Video AI - Mr Huynh"
fail() { echo; echo "  [LOI] $1"; echo; [ -n "$CI" ] || read -r -p "Bam Enter de dong..." _; exit 1; }

echo "============================================================"
echo "  BUILD VIDEO AI - MR. HUYNH  (tao file .dmg cho macOS)"
echo "============================================================"
echo "  May: $(sw_vers -productName) $(sw_vers -productVersion) - chip $(uname -m)"
echo

# ---------- 1. Python 3.10 - 3.14 ----------
PY=""
for c in python3.12 python3.13 python3.14 python3.11 python3.10 \
         /Library/Frameworks/Python.framework/Versions/{3.12,3.13,3.14,3.11}/bin/python3 python3; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10)<=sys.version_info[:2]<=(3,14) else 1)' 2>/dev/null; then
    PY="$c"; break
  fi
done
[ -n "$PY" ] || fail "Chua co Python 3.10 - 3.14. Tai Python 3.12 (macOS 64-bit universal2 installer) tai
         https://www.python.org/downloads/macos/  -> cai xong bam lai file nay."
echo "[1/7] Dung Python: $PY ($("$PY" --version 2>&1))"
xcode-select -p >/dev/null 2>&1 || echo "      (Neu macOS hoi cai 'Command Line Tools' thi bam Cai dat roi chay lai)"

# ---------- 2. Môi trường ảo ----------
if [ ! -x ".venv-mac/bin/python" ]; then
  echo "[2/7] Tao moi truong ao .venv-mac ..."
  "$PY" -m venv .venv-mac || fail "Khong tao duoc moi truong ao"
else
  echo "[2/7] Da co moi truong ao .venv-mac"
fi
VPY="$PWD/.venv-mac/bin/python"

# ---------- 3. Thư viện ----------
echo "[3/7] Cai thu vien (lan dau mat vai phut) ..."
"$VPY" -m pip install --upgrade pip --disable-pip-version-check -q || fail "pip loi"
"$VPY" -m pip install --prefer-binary -r requirements.txt pyinstaller --disable-pip-version-check -q || fail "Cai thu vien loi"

export SSL_CERT_FILE="$("$VPY" -m certifi)"      # chứng chỉ HTTPS cho Python của python.org

# ---------- 4. Bản quyền ----------
if ! "$VPY" tools/fill_license_config.py; then
  echo
  echo "  ============================================================"
  echo "  [CANH BAO] CHUA CO THONG TIN BAN QUYEN - day la BAN PHAT TRIEN:"
  echo "             KHONG KHOA KEY. KHONG PHAT HANH CHO KHACH."
  echo "             Chep file videoai/license_config.json tu may Windows (da chay chuan-bi-hosting.bat) sang day."
  echo "  ============================================================"
  [ -n "$CI" ] && exit 1                     # GitHub Actions: không phát hành bản thiếu bản quyền
  read -r -p "  Bam Enter de van build ban phat trien, hoac dong cua so de huy..." _
fi

# ---------- 5. Đóng gói .app ----------
echo "[4/7] Tao bieu tuong ung dung ..."
mkdir -p build/out
ICONSET="build/out/icon.iconset"; rm -rf "$ICONSET"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z $s $s videoai/assets/logo.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null 2>&1
  d=$((s*2)); sips -z $d $d videoai/assets/logo.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null 2>&1
done
iconutil -c icns "$ICONSET" -o build/out/icon.icns 2>/dev/null || echo "      (bo qua bieu tuong)"

echo "[5/7] Dong goi bang PyInstaller ..."
rm -rf "dist/$APP.app" dist/VideoAI-MrHuynh
"$VPY" -m PyInstaller --noconfirm --clean --distpath dist --workpath build/out/mac build/VideoAI-mac.spec || fail "PyInstaller loi"
[ -d "dist/$APP.app" ] || fail "Khong thay dist/$APP.app"
rm -rf dist/VideoAI-MrHuynh

# ---------- 6. Công cụ đi kèm + ký ad-hoc ----------
echo "[6/7] Tai ffmpeg, Real-ESRGAN, yt-dlp ..."
bash build/fetch_tools_mac.sh "dist/$APP.app/Contents/MacOS/bin"
echo "      Ky ad-hoc (bat buoc de chay tren chip Apple M) ..."
find "dist/$APP.app/Contents/MacOS/bin" -type f -perm +111 -exec codesign --force --sign - {} \; >/dev/null 2>&1
codesign --force --deep --sign - "dist/$APP.app" >/dev/null 2>&1 || echo "      (codesign bao loi - ung dung van co the chay)"
codesign --verify --deep "dist/$APP.app" >/dev/null 2>&1 && echo "      Chu ky OK" || echo "      [CANH BAO] kiem tra chu ky chua dat"

# ---------- 7. Tạo .dmg ----------
VER="$("$VPY" -c 'from videoai.core.paths import APP_VERSION; print(APP_VERSION)')"
DMG="dist/VideoAI-MrHuynh-$VER-mac.dmg"
echo "[7/7] Tao $DMG ..."
STAGE="build/out/dmg"; rm -rf "$STAGE"; mkdir -p "$STAGE"
ditto "dist/$APP.app" "$STAGE/$APP.app"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
ok=""
for i in 1 2 3; do                                 # hdiutil đôi khi báo "Resource busy" → thử lại
  hdiutil create -volname "$APP" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null && { ok=1; break; }
  sleep 5
done
[ -n "$ok" ] || fail "hdiutil khong tao duoc .dmg"
rm -rf "$STAGE"
"$VPY" tools/make_downloads.py --mac "$DMG" || fail "Khong tao duoc goi tai len"

echo
echo "============================================================"
echo "  XONG!"
echo "    Bo cai macOS : $DMG"
echo "    Chip         : $(uname -m)  (arm64 = chi may Mac chip Apple M; x86_64 = Mac Intel, chay ca chip M qua Rosetta)"
echo
echo "  PHAT HANH (cung trang tai voi ban Windows):"
echo "    1. cPanel File Manager > public_html/downloads > Upload"
echo "       dist/downloads-mac-upload.zip  > Extract (ghi de)"
echo "       => https://mrhuynh.net/downloads/video_ai_mrhuynh_mac.dmg"
echo "    2. Trang quan tri > Cap nhat phan mem > chon \"File tren trang tai (macOS)\" > Phat hanh"
echo "============================================================"
[ -n "$CI" ] && exit 0
open dist >/dev/null 2>&1
read -r -p "Bam Enter de dong..." _
