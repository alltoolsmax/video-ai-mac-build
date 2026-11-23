# Bản sao mã máy chủ đang chạy trên hosting (active.mrhuynh.net) – CHỈ ĐỂ LƯU TRỮ

Thư mục này KHÔNG phải gói để tải lên hosting. Gói cập nhật hosting của Video AI vẫn là `hosting/`.
Không có config.php, không có thư mục data/ (khóa bí mật, dữ liệu khách hàng không bao giờ đưa lên đây).

- `voice-ai/` – máy chủ Voice AI (bán key offline, SePay, version.json cho phần mềm tự cập nhật)
  - `active.mrhuynh.net/index.php` – API /api/plans, /api/orders, /api/app/version, /api/app/announcement, /api/app/video
  - `admin.php` – trang quản trị riêng của Voice AI (đơn hàng, cấp key tay, thông báo popup, link video, sửa link/điểm mới của version.json mà GIỮ chữ ký)
  - `version.json` do công cụ ký `keygen-update/KY-BAN-CAP-NHAT.bat` tạo (có sha256 + chữ ký),
    nhớ thêm dòng `url_mac` bằng tay. Trang quản trị chung › Voice AI › Thông báo bản mới (từ 23/11/2026)
    giữ nguyên url_mac/sha256/chữ ký; đổi số phiên bản ở đó thì chữ ký bị bỏ (app chỉ mở link tải).
- `gcloud-hub/` – máy chủ GCloud Hub (cập nhật + đếm máy)
  - `active.mrhuynh.net/gcloudhub/index.php` + `.htaccess` – API /gcloudhub/v1/app/version
- Trang quản trị chung + máy chủ Video AI: `hosting/active.mrhuynh.net/admin`, `hosting/active.mrhuynh.net/video`,
  `hosting/active_private/video/lib.php` (luôn ghép từ bản đang chạy để không mất phần của tool khác).

Mã nguồn phần mềm: Video AI = repo này; Voice AI = alltoolsmax/voice-ai-mac-build; GCloud Hub = alltoolsmax/gcloud-hub-build.
