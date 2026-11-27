"""SYNC API – chạy cùng Video AI, biến cookie của một tài khoản (Google Flow, Chat GPT, Grok, Muse) thành API key.

- store.py:  kho API key ↔ cookie (cookie lưu mã hóa trong app.db) và liên kết API key ↔ tài khoản Video AI.
- window.py: cửa sổ SYNC API (ô dán cookie, Lấy Cookie, Lưu, Sao chép API Key) + biểu tượng ở khay hệ thống.
- server.py: API HTTP cục bộ kiểu OpenAI (127.0.0.1) cho ứng dụng khác; mỗi yêu cầu chạy qua chính engine của Video AI.
- service.py: điểm vào dùng chung (SyncApi) cho giao diện và main.py.

Trong Video AI, API key là "tay nắm" của cookie: khi gắn key cho tài khoản, cookie của key được nạp vào hồ sơ trình
duyệt riêng của tài khoản đó (cùng đường với "Dán cookie" trước đây), nên mọi tính năng của engine giữ nguyên.
"""
APP_TITLE = "SYNC API"
