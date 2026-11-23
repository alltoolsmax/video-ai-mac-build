# Bản sao mã máy chủ đang chạy trên hosting (active.mrhuynh.net) – CHỈ ĐỂ LƯU TRỮ

Thư mục này KHÔNG phải gói để tải lên hosting. Gói cập nhật hosting của Video AI vẫn là `hosting/`.
Không có config.php, không có thư mục data/ (khóa bí mật, dữ liệu khách hàng không bao giờ đưa lên đây).

- `voice-ai/` – máy chủ Voice AI (bán key offline, SePay, version.json cho phần mềm tự cập nhật)
  - `active.mrhuynh.net/index.php` – CÒN THIẾU (API /api/plans, /api/orders, /api/app/version)
  - `version.json` do công cụ ký `keygen-update/KY-BAN-CAP-NHAT.bat` tạo (có sha256 + chữ ký),
    nhớ thêm dòng `url_mac` bằng tay. KHÔNG lưu ở trang quản trị › Voice AI › Thông báo bản mới
    (trang đó xóa mất chữ ký / url_mac).
- `gcloud-hub/` – máy chủ GCloud Hub (cập nhật + đếm máy)
  - `active.mrhuynh.net/gcloudhub/index.php` – CÒN THIẾU
- Trang quản trị chung + máy chủ Video AI: `hosting/active.mrhuynh.net/admin`, `hosting/active.mrhuynh.net/video`,
  `hosting/active_private/video/lib.php` (luôn ghép từ bản đang chạy để không mất phần của tool khác).

Mã nguồn phần mềm: Video AI = repo này; Voice AI = alltoolsmax/voice-ai-mac-build; GCloud Hub = alltoolsmax/gcloud-hub-build.
