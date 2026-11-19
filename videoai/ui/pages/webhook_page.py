"""Webhook API: bật/tắt máy chủ cục bộ, xem token, ví dụ gọi."""
from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLineEdit, QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget

from ..widgets import Card, button, field, label
from ...core.i18n import tr


class WebhookPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.db = ctx.db
        self.wh = ctx.webhook
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(12)
        v.addWidget(label("Webhook API", "h1"))
        hint = label("Cho phép công cụ khác (n8n, Make, Zapier qua tunnel, script Python…) gửi prompt vào hàng đợi. "
                     "Chỉ lắng nghe trên máy này (127.0.0.1).", "muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        c = Card("Máy chủ", "link")
        row = QHBoxLayout()
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(int(self.db.get_setting("webhook_port", 8787)))
        self.conc = QSpinBox()
        self.conc.setRange(1, 6)
        self.conc.setValue(int(self.db.get_setting("webhook_concurrency", 1)))
        self.auto = QCheckBox(tr("Tự bật khi mở ứng dụng"))
        self.auto.setChecked(bool(self.db.get_setting("webhook_enabled", False)))
        row.addWidget(field("Cổng", self.port))
        row.addWidget(field("Số hàng đồng thời", self.conc))
        row.addWidget(self.auto)
        row.addStretch()
        c.add(row)
        tk = QHBoxLayout()
        self.token = QLineEdit(self.wh.token)
        self.token.setReadOnly(True)
        b_copy = button("Sao chép", "chip", "save", "#67e8f9")
        b_copy.clicked.connect(lambda: (QGuiApplication.clipboard().setText(self.token.text()), self.ctx.toast("ok", tr("Đã sao chép token."))))
        b_new = button("Tạo token mới", "chip", "retry", "#fbbf24")
        b_new.clicked.connect(lambda: (self.token.setText(self.wh.regenerate_token()), self._example()))
        tk.addWidget(field("Token (Authorization: Bearer …)", self.token), 1)
        tk.addWidget(b_copy)
        tk.addWidget(b_new)
        c.add(tk)
        br = QHBoxLayout()
        self.b_toggle = button("Bật webhook", "start", "play")
        self.b_toggle.clicked.connect(self.toggle)
        self.state = label("", "muted")
        br.addWidget(self.b_toggle)
        br.addWidget(self.state)
        br.addStretch()
        c.add(br)
        v.addWidget(c)
        ex = Card("Ví dụ", "list")
        self.ex = QPlainTextEdit()
        self.ex.setReadOnly(True)
        self.ex.setStyleSheet("font-family:'Cascadia Mono','Consolas',monospace;font-size:12px;")
        ex.add(self.ex)
        v.addWidget(ex, 1)
        self._example()
        self._ui()

    def _example(self):
        p = self.port.value()
        t = self.token.text()
        self.ex.setPlainText(
            f"""# Tạo hàng loạt (PowerShell)
$h = @{{ Authorization = "Bearer {t}" }}
$b = @{{ page = "flow_video"; mode = "t2v"; count = 1;
        prompts = @("Flycam bay qua ruộng bậc thang lúc bình minh", "Phố cổ Hội An về đêm") }} | ConvertTo-Json
Invoke-RestMethod -Uri http://127.0.0.1:{p}/api/jobs -Method Post -Headers $h -Body $b -ContentType "application/json"

# curl
curl -X POST http://127.0.0.1:{p}/api/jobs -H "Authorization: Bearer {t}" -H "Content-Type: application/json" \\
     -d '{{"page":"flow_image","prompts":["a red fox in snow"],"count":2,"callback_url":"http://127.0.0.1:5678/webhook/done"}}'

# Xem trạng thái + đường dẫn file kết quả
curl http://127.0.0.1:{p}/api/jobs/<batch_id> -H "Authorization: Bearer {t}"

# Các trang hợp lệ:  GET /api/pages
# page: flow_image, flow_video, gvids, gpics, dreamina, gpt_image, muse_image, meta_muse, meta_vibes, grok
# mode: t2i, i2i, t2v, i2v, compose  (refs: ["C:/anh/khung_dau.png"] cho chế độ cần ảnh)
""")

    def toggle(self):
        self.db.set_setting("webhook_port", self.port.value())
        self.db.set_setting("webhook_concurrency", self.conc.value())
        self.db.set_setting("webhook_enabled", self.auto.isChecked())
        if self.wh.running():
            self.wh.stop()
        else:
            try:
                self.wh.start(self.port.value())
            except OSError as e:
                self.ctx.toast("error", tr("Không mở được cổng") + f" {self.port.value()}: {e}")
        self._example()
        self._ui()

    def _ui(self):
        on = self.wh.running()
        self.b_toggle.setText(tr("Tắt webhook") if on else tr("Bật webhook"))
        self.b_toggle.setProperty("kind", "stop" if on else "start")
        self.b_toggle.style().unpolish(self.b_toggle)
        self.b_toggle.style().polish(self.b_toggle)
        self.state.setText(f"● {tr('Đang chạy tại')} http://127.0.0.1:{self.port.value()}" if on else "○ " + tr("Đang tắt"))
