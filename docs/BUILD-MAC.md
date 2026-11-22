# Build bản macOS – Video AI Mr. Huỳnh

Bản Mac phải build TRÊN MÁY MAC (PyInstaller không build chéo từ Windows).

## Chuẩn bị (1 lần)
1. Cài **Python 3.12** cho macOS: https://www.python.org/downloads/macos/ → chọn *macOS 64-bit universal2 installer*.
2. Cài **Google Chrome** (để chạy thử).
3. Chép thư mục mã nguồn sang Mac. Nếu đã chạy `hosting\chuan-bi-hosting.bat` trên Windows, chép thêm file
   `videoai/license_config.json` từ máy Windows (hoặc để build tự hỏi khóa công khai từ máy chủ).

## Build
- Bấm đúp **`build Mac.command`**. Lần đầu macOS có thể báo "không mở được vì tải từ Internet":
  chuột phải (Control + bấm) vào file › **Mở** › **Mở**. Hoặc mở Terminal, gõ `bash "` rồi kéo file vào, gõ `"` và Enter.
- Nếu macOS hỏi cài *Command Line Tools* → bấm **Cài đặt**, xong chạy lại.
- Xong sẽ có:
  - `dist/Video AI - Mr Huynh.app` – chạy thử ngay.
  - `dist/VideoAI-MrHuynh-<phiên bản>-mac.dmg` – bộ cài.
  - `dist/downloads-mac-upload.zip` – gói tải lên trang tải.

## Chip
- Build trên **Mac chip Apple M** (M1…M4) → bộ cài chỉ chạy trên Mac chip M (đa số máy từ 2021).
- Build trên **Mac Intel** → chạy trên Mac Intel, và cả Mac chip M (qua Rosetta, chậm hơn một chút).

## Phát hành
1. cPanel › File Manager › `public_html/downloads/` › Upload `dist/downloads-mac-upload.zip` › Extract (ghi đè) › xóa zip.
   Thư mục có thêm `video_ai_mrhuynh_mac.dmg` và `mac.json`. Trang https://mrhuynh.net/downloads/ tự hiện thẻ **macOS**
   (máy Mac mở trang sẽ thấy phần macOS trước).
2. Trang quản trị › Video AI › Cập nhật phần mềm › chọn **★ File trên trang tải · macOS** › ghi "Có gì mới" › **Phát hành**.
   Máy chủ tự kiểm tra đúng file .dmg, đúng số phiên bản (mac.json) và tính SHA-256.
3. Bản Mac tự cập nhật riêng (hỏi `…/v1/app/version?os=mac`); bản Windows không bị ảnh hưởng.

## Khách cài trên Mac
- Mở .dmg → kéo **Video AI - Mr Huynh** vào **Applications**.
- Lần mở đầu: macOS báo không xác minh được nhà phát triển (vì chưa mua chữ ký Apple Developer 99 USD/năm) →
  Cài đặt hệ thống › Quyền riêng tư & Bảo mật › **Vẫn mở**. (Trang tải đã có hướng dẫn này.)
- Dữ liệu ứng dụng: `~/Library/Application Support/VideoAI-MrHuynh` · kết quả mặc định: `~/Movies/VideoAI-MrHuynh/output`.
- Cần Google Chrome (hoặc Microsoft Edge) trên máy.

## Cần kiểm tra khi chạy thử lần đầu trên Mac
- Chế độ trình duyệt ẩn: cửa sổ Chrome phải nằm ngoài màn hình. Nếu thấy cửa sổ Chrome hiện ra khi chạy tác vụ, báo lại.
- Công cụ nhanh / Xóa logo / Nâng cấp ảnh (ffmpeg, Real-ESRGAN) và Download (yt-dlp).
- Tự cập nhật: cần quyền ghi vào thư mục chứa ứng dụng (Applications – tài khoản quản trị của máy).
