"""4 ô đếm chung (Đang chạy / Hàng đợi / Hoàn thành / Lỗi): lấy đúng các tác vụ đó trên MỌI nền tảng
(hiện ngay trong danh sách tác vụ của trang đang mở – TaskModel.scope)."""
from __future__ import annotations

GROUPS = {   # ô đếm → các trạng thái trong CSDL (giống cách ô đếm cộng)
    "running": ("running", "needs_user"),
    "queued": ("queued",),
    "done": ("done",),
    "failed": ("failed", "blocked"),
}


def jobs_by_group(db, key: str, limit: int = 2000) -> list[dict]:
    st = GROUPS[key]
    q = ",".join("?" * len(st))
    return db.query(
        "SELECT j.*, b.platform, b.page FROM jobs j JOIN batches b ON b.id=j.batch_id"
        f" WHERE j.status IN ({q}) ORDER BY j.updated_at DESC LIMIT ?", (*st, limit))
