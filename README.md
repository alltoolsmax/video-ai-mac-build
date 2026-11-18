# Video AI - Mr. Huỳnh

Tạo ảnh/video AI hàng loạt trên tài khoản của chính bạn (Google Flow, Grok, Dreamina, GPT Image, Meta…),
kèm workflow, nhân vật, nâng cấp ảnh, công cụ video và webhook.

## Build file .exe (Windows 10/11, 64-bit)
Bấm đúp **`build Windows.bat`**. File này tự làm hết:
1. Tìm Python 3.10–3.13 (chưa có thì tự cài Python 3.12 qua winget).
2. Tạo môi trường ảo `.venv-build`, cài thư viện + PyInstaller.
3. Đóng gói ra `dist\VideoAI-MrHuynh\VideoAI-MrHuynh.exe`.
4. Tải ffmpeg, Real-ESRGAN và Chromium dự phòng vào cạnh file exe.
5. Nếu máy có Inno Setup 6 thì tạo thêm bộ cài `dist\VideoAI-MrHuynh-Setup-1.0.0.exe`.

Lần đầu mất khoảng 5–15 phút tùy mạng. Cần Internet. Mang sang máy khác: copy **cả thư mục** `dist\VideoAI-MrHuynh`
(hoặc dùng bộ cài). Windows SmartScreen có thể cảnh báo vì exe chưa ký số: bấm "More info" › "Run anyway".

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
