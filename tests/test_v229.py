"""v2.2.9 – nút Xem hướng dẫn + Mở trình duyệt ở tab Tài khoản, 2 nút liên kết trên thanh trên (link sửa ở trang quản trị),
Quy trình tự động: khối "nhất quán xuyên suốt" + thời lượng mặc định thấp nhất, Flow video mặc định Veo 3.1 - Lite."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def win(db, qapp):
    from videoai.core.engine import Engine
    from videoai.services.refs import RefLibrary
    from videoai.services.webhook import WebhookServer
    from videoai.ui.main_window import MainWindow
    from videoai.ui.theme import qss
    from PySide6.QtGui import QFontDatabase
    from videoai.core.paths import assets_dir
    for f in (assets_dir() / "fonts").glob("*.ttf"):       # font của ứng dụng (như main.py) để bề rộng nút đúng như bản thật
        QFontDatabase.addApplicationFont(str(f))
    qapp.setStyleSheet(qss())
    db.set_setting("flow_rights_ok", True)
    db.set_setting("flow_terms_ok", True)
    eng = Engine(db)
    w = MainWindow(db, eng, RefLibrary(db), WebhookServer(db, eng))
    w.show()
    yield w
    eng.loop.call_soon_threadsafe(eng.loop.stop)
    w.deleteLater()


def test_consistency_block_in_system_prompt():
    """Quy trình tự động: hướng dẫn hệ thống buộc AI khóa nhân vật / sản phẩm / bối cảnh / ánh sáng / phong cách và chép
    nguyên văn vào mọi cảnh (video có thêm giọng nói, nhạc nền và sự liền mạch giữa các cảnh)."""
    from videoai.services import script as S
    v, _ = S.build_message(S.Brief(topic="review", idea="review son môi", total_secs=24, clip_secs=8))
    for part in ("NHẤT QUÁN XUYÊN SUỐT", "NHÂN VẬT", "SẢN PHẨM / ĐỒ VẬT", "BỐI CẢNH", "ÁNH SÁNG + MÀU SẮC", "PHONG CÁCH HÌNH ẢNH",
                 "ÂM THANH", "LIỀN MẠCH", "CHÉP LẠI NGUYÊN VĂN", "TỰ KIỂM TRA", "MỌI cảnh", "suốt video"):
        assert part in v, part
    assert v.index("NHẤT QUÁN XUYÊN SUỐT") < v.index("HƯỚNG DẪN THEO CHỦ ĐỀ") < v.index("ĐỊNH DẠNG TRẢ VỀ BẮT BUỘC")
    assert "{" not in v.split("ĐỊNH DẠNG TRẢ VỀ BẮT BUỘC")[0]                 # không còn chỗ trống chưa điền

    i, _ = S.build_image_message(S.Brief(topic="product", idea="ảnh sản phẩm", total_secs=0, clip_secs=1, kind="image", count=3))
    for part in ("NHẤT QUÁN XUYÊN SUỐT", "NHÂN VẬT", "BỐI CẢNH", "CHÉP LẠI NGUYÊN VĂN", "MỌI ảnh", "suốt bộ ảnh"):
        assert part in i, part
    assert "ÂM THANH:" not in i and "LIỀN MẠCH:" not in i                    # ảnh tĩnh: không có giọng nói / nối cảnh
    assert i.index("NHẤT QUÁN XUYÊN SUỐT") < i.index("HƯỚNG DẪN THEO MỤC ĐÍCH")


def test_flow_video_defaults_to_veo_lite_and_script_duration_lowest(win, qapp, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from videoai.core.platforms import PAGE_BY_KEY
    from videoai.ui import script_dialog as SD
    p = PAGE_BY_KEY["flow_video"]
    assert p.extra["default_model"] == "Veo 3.1 - Lite" and p.models == ["Omni 1.2 Flash", "Veo 3.1 - Lite"]
    monkeypatch.setattr(type(win), "is_pro", lambda self: True)
    win.go("flow_video")
    pg = win.pages["flow_video"]
    assert pg.model_cb.currentText() == "Veo 3.1 - Lite"                    # mở ứng dụng: chọn sẵn Veo 3.1 - Lite
    assert pg._params()["model"] == "Veo 3.1 - Lite"

    seen = {}

    def run(d):
        seen["scenes"], seen["min"] = d.dur.value(), d.dur.minimum()
        return QDialog.Rejected
    monkeypatch.setattr(SD.ScriptDialog, "exec", run)
    pg.open_script()
    assert seen == {"scenes": 1, "min": 1}                                   # thời lượng mặc định = mức thấp nhất (1 cảnh)


def test_topbar_link_buttons_use_admin_links(win, qapp, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    win.resize(2400, 900)                                  # đủ rộng: tên đầy đủ
    qapp.processEvents()
    assert win.b_autowf.text() == "Auto-WorkFlow trên Flow" and win.b_local.text() == "Tạo Video Local không tốn AI"
    win.resize(win.minimumWidth(), 900)                    # bề rộng tối thiểu: tên ngắn, không nút nào bị cắt chữ
    qapp.processEvents()
    top = win.b_voice.parentWidget()
    assert win.b_autowf.text() == "Auto-WorkFlow" and win.b_local.text() == "Video Local"
    assert top.layout().minimumSize().width() <= top.width()
    assert win.b_local.toolTip().startswith("Tạo Video Local không tốn AI")
    lay = win.b_voice.parentWidget().layout()
    order = [lay.itemAt(k).widget() for k in range(lay.count()) if lay.itemAt(k).widget() is not None]
    iv = order.index(win.b_voice)
    assert order[iv + 1] is win.b_autowf and order[iv + 2] is win.b_local   # nằm kế nút "Tạo giọng nói MIỄN PHÍ"

    win.guides = {}
    win.b_autowf.click()
    win.b_local.click()
    assert opened == ["https://mrhuynh.net/auto-workflow/", "https://mrhuynh.net/tools/"]   # chưa nhập ở quản trị: link mặc định

    win.guides = {"link_auto_workflow": "https://example.com/wf", "link_local_video": "http://khong-an-toan"}
    win._guide_button()
    opened.clear()
    win.b_autowf.click()
    win.b_local.click()
    assert opened == ["https://example.com/wf", "https://mrhuynh.net/tools/"]             # link quản trị (https) được dùng
    assert win.b_autowf.toolTip().endswith("https://example.com/wf")


def test_accounts_tab_guide_and_open_browser(win, db, qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QDesktopServices
    opened, logins = [], []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    monkeypatch.setattr(win.ctx.engine, "open_login", lambda acc, url: logins.append((acc["label"], url)))
    ids = [db.add_account(pl, nm, str(tmp_path / nm)) for pl, nm in
           (("flow", "g1"), ("grok", "k1"), ("gemini", "gem1"), ("muse", "m1"))]
    win.guides = {}
    win.open_settings()
    sp = win.pages["settings"]
    assert sp.b_acc_guide.text().strip() == "Xem hướng dẫn" and not sp.b_acc_guide.isHidden()   # chưa có link vẫn hiện
    sp.b_acc_guide.click()
    assert opened == []                                    # chưa có link → không mở gì, chỉ báo

    win.guides = {"settings_accounts": "https://youtu.be/tk"}
    win._guide_button()                                    # cửa sổ chính tải xong link → tab Tài khoản hiện nút
    assert not sp.b_acc_guide.isHidden() and sp.b_acc_guide.toolTip() == "https://youtu.be/tk"
    sp.b_acc_guide.click()
    assert opened == ["https://youtu.be/tk"]

    sp._acc_checked = set()
    sp._open_browser()
    assert logins == []                                    # chưa chọn tài khoản nào
    sp._reload_accounts()
    sp._acc_checked = set(ids)
    sp._open_browser()                                     # mở Chrome thường cho tối đa 3 tài khoản đã chọn
    assert len(logins) == 3 and {u for _, u in logins} <= {"https://flow.google.com/", "https://grok.com/",
                                                           "https://gemini.google.com/app", "https://muse.ai/"}
    from PySide6.QtWidgets import QPushButton
    assert "Mở trình duyệt" in [b.text() for b in sp.findChildren(QPushButton)]


def test_admin_page_lists_new_link_keys():
    """Trang quản trị (mục Video hướng dẫn) có 3 dòng mới; API quản trị nhận mã [a-z0-9_] nên không cần sửa PHP."""
    html = (ROOT / "hosting/active.mrhuynh.net/admin/index.html")
    if not html.exists():
        pytest.skip("mã trang quản trị không có trong kho công khai")
    text = html.read_text(encoding="utf-8")
    from videoai.ui.main_window import GUIDE_ACCOUNTS, LINKS
    for key in [GUIDE_ACCOUNTS, *LINKS]:
        assert f"['{key}'," in text, key
