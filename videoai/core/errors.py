"""Lỗi có mã + thông điệp dễ hiểu cho người dùng."""
from __future__ import annotations

MESSAGES = {
    "not_logged_in": "Tài khoản chưa đăng nhập hoặc phiên đã hết hạn. Vào Cài Đặt › Tài khoản để đăng nhập lại.",
    "needs_user": "Trang yêu cầu xác minh (captcha/đăng nhập). Hãy xử lý trong cửa sổ trình duyệt, ứng dụng sẽ tự chạy tiếp.",
    "no_account": "Chưa có tài khoản nào cho nền tảng này. Thêm ở Cài Đặt › Tài khoản.",
    "blocked": "Prompt bị nền tảng từ chối (vi phạm chính sách nội dung). Hãy sửa prompt rồi chạy lại.",
    "flagged": "Flow báo \"hoạt động bất thường\" trên tài khoản này và từ chối tạo (không tính phí). Tài khoản được tạm ngưng trong lần chạy này; "
               "hãy mở Flow bằng trình duyệt thường, dùng thủ công một lúc rồi mới chạy lại, và chạy ít tác vụ hơn.",
    "quota": "Tài khoản đã hết lượt/credit. Tác vụ dừng lại cho tới khi bạn nạp thêm hoặc đợi làm mới.",
    "timeout": "Quá thời gian chờ kết quả. Có thể trang đang chậm, thử chạy lại.",
    "ui_changed": "Không tìm thấy ô nhập/nút trên trang (giao diện web có thể đã thay đổi). Kiểm tra file selector trong Cài Đặt › Nền tảng.",
    "download": "Không tải được kết quả về máy.",
    "ref_missing": "Chế độ này cần ảnh tham chiếu.",
    "browser": "Không mở được trình duyệt. Kiểm tra Chrome hoặc chạy lại 'playwright install chromium'.",
    "unknown": "Lỗi không xác định. Xem Log Chi Tiết.",
}


class JobError(Exception):
    def __init__(self, code: str, detail: str = ""):
        self.code = code if code in MESSAGES else "unknown"
        self.detail = detail
        super().__init__(f"{self.code}: {detail}")

    @property
    def friendly(self) -> str:
        return MESSAGES[self.code]


def friendly(code: str | None) -> str:
    return MESSAGES.get(code or "unknown", MESSAGES["unknown"])
