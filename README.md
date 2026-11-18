# Video AI - Mr. Huỳnh

Tạo ảnh/video AI hàng loạt trên tài khoản của chính bạn (Google Flow, Grok, Dreamina, GPT Image, Meta…),
kèm workflow, nhân vật, nâng cấp ảnh, công cụ video và webhook.

## Chạy thử từ mã nguồn (Windows)
1. Cài Python 3.12 (python.org, tick "Add to PATH") và Google Chrome.
2. Mở PowerShell trong thư mục này:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   python -m playwright install chromium
   python run.py
   ```
3. Cài ffmpeg (winget install Gyan.FFmpeg) nếu muốn dùng Công Cụ Video ngay.

## Lần đầu dùng
Cài Đặt › Tài khoản › chọn nền tảng › Thêm tài khoản → tự đăng nhập trong cửa sổ trình duyệt → Kiểm tra.

## Khi một nền tảng đổi giao diện
Cài Đặt › Nền tảng › Mở thư mục selector → sửa file `<nền tảng>.json` (không cần cài lại).

## Kiểm thử
`pip install pytest && python -m pytest -q tests/`
