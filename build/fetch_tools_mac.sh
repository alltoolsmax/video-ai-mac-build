#!/bin/bash
# Tải ffmpeg + ffprobe, Real-ESRGAN và yt-dlp cho macOS vào thư mục bin của ứng dụng.
# Dùng:  bash build/fetch_tools_mac.sh "dist/Video AI - Mr Huynh.app/Contents/MacOS/bin"
set -u
DEST="${1:-bin}"
mkdir -p "$DEST"
TMP="$(mktemp -d /tmp/videoai_tools.XXXXXX)"
ARCH="$(uname -m)"                     # arm64 (chip Apple M) hoặc x86_64 (Intel)
[ "$ARCH" = "x86_64" ] && RARCH="amd64" || RARCH="arm64"

get() {  # get <tệp ra> <url1> [url2...]
  local out="$1"; shift
  for u in "$@"; do
    echo "  - Tai $(basename "$out") tu $u"
    if curl -L --fail --retry 2 --connect-timeout 20 -# -o "$out" "$u"; then return 0; fi
    echo "    Nguon nay loi, thu nguon khac..."
  done
  return 1
}

# ffmpeg + ffprobe (bản tĩnh, không cần Homebrew)
mkdir -p "$DEST/ffmpeg"
for tool in ffmpeg ffprobe; do
  if [ -x "$DEST/ffmpeg/$tool" ]; then echo "  - $tool da co"; continue; fi
  if get "$TMP/$tool.zip" \
      "https://ffmpeg.martin-riedl.de/redirect/latest/macos/$RARCH/release/$tool.zip" \
      "https://evermeet.cx/ffmpeg/getrelease/$tool/zip" \
      "https://evermeet.cx/ffmpeg/getrelease/zip"; then
    rm -rf "$TMP/$tool.d"; mkdir -p "$TMP/$tool.d"
    unzip -o -q "$TMP/$tool.zip" -d "$TMP/$tool.d"
    f="$(find "$TMP/$tool.d" -type f -name "$tool" | head -n 1)"
    if [ -n "$f" ]; then cp "$f" "$DEST/ffmpeg/$tool"; chmod 755 "$DEST/ffmpeg/$tool"; echo "    OK: $tool"
    else echo "    [CANH BAO] khong thay $tool trong goi tai ve"; fi
  else
    echo "    [CANH BAO] Khong tai duoc $tool (Cong cu nhanh / Xoa logo se can ffmpeg)"
  fi
done
"$DEST/ffmpeg/ffmpeg" -version >/dev/null 2>&1 && echo "    ffmpeg chay duoc" || echo "    [CANH BAO] ffmpeg chua chay duoc tren may nay"

# Real-ESRGAN ncnn-vulkan (bản macOS chạy cả chip Apple M và Intel)
if [ ! -x "$DEST/realesrgan/realesrgan-ncnn-vulkan" ]; then
  if get "$TMP/realesrgan.zip" \
      "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.5.0/realesrgan-ncnn-vulkan-20220424-macos.zip"; then
    mkdir -p "$TMP/realesrgan.d" "$DEST/realesrgan"
    unzip -o -q "$TMP/realesrgan.zip" -d "$TMP/realesrgan.d"
    exe="$(find "$TMP/realesrgan.d" -type f -name realesrgan-ncnn-vulkan | head -n 1)"
    if [ -n "$exe" ]; then cp -R "$(dirname "$exe")/." "$DEST/realesrgan/"; chmod 755 "$DEST/realesrgan/realesrgan-ncnn-vulkan"; echo "    OK: Real-ESRGAN"; fi
  else
    echo "    [CANH BAO] Khong tai duoc Real-ESRGAN (Nang cap anh se dung che do Lanczos)"
  fi
else echo "  - Real-ESRGAN da co"; fi

# yt-dlp (bản chạy độc lập cho macOS; ứng dụng tự chép sang thư mục dữ liệu và tự cập nhật)
mkdir -p "$DEST/yt-dlp"
if [ ! -x "$DEST/yt-dlp/yt-dlp" ]; then
  if get "$DEST/yt-dlp/yt-dlp" "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_macos"; then
    chmod 755 "$DEST/yt-dlp/yt-dlp"; echo "    OK: yt-dlp"
  else echo "    [CANH BAO] Khong tai duoc yt-dlp (Download se tu tai khi dung lan dau)"; fi
else echo "  - yt-dlp da co"; fi

rm -rf "$TMP"
exit 0
