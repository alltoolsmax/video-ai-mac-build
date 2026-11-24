"""Kiểm thử giao diện (offscreen): menu, trang Flow mới, kho ảnh tham chiếu, công cụ video."""
from pathlib import Path

from PySide6.QtWidgets import QLabel
import json
import pytest


@pytest.fixture()
def win(db, qapp):
    from videoai.core.engine import Engine
    from videoai.services.refs import RefLibrary
    from videoai.services.webhook import WebhookServer
    from videoai.ui.main_window import MainWindow
    from videoai.ui.theme import qss
    qapp.setStyleSheet(qss())
    db.set_setting("flow_rights_ok", True)       # đã xác nhận quyền sử dụng tệp tải lên (không bật hộp thoại khi kiểm thử)
    db.set_setting("flow_terms_ok", True)        # đã đồng ý điều khoản Google Flow
    eng = Engine(db)
    w = MainWindow(db, eng, RefLibrary(db), WebhookServer(db, eng))
    w.show()
    yield w
    eng.loop.call_soon_threadsafe(eng.loop.stop)
    w.deleteLater()


def _img(path, color="red"):
    from videoai.media import ffmpeg
    ffmpeg.run(["-f", "lavfi", "-i", f"color=c={color}:s=96x96", "-frames:v", "1", str(path)])
    return str(path)


def test_menu_order_and_pages(win, qapp):
    labels = [b.text() for b in win.group.buttons()]
    assert labels == ["Tạo ảnh Flow", "Tạo ảnh GPT", "Tạo ảnh Grok", "Tạo ảnh Muse",
                      "Tạo Video Flow", "Tạo Video Muse", "Tạo Video Grok", "Clip Lip-Sync",
                      "Kho ảnh tham chiếu", "Workflow", "Nâng Cấp Ảnh", "Xóa Watermark (Logo)", "Công cụ nhanh", "Download", "Log Chi Tiết"]
    assert list(win.sections) == ["image", "video", "tools"]
    assert "webhook" not in win.menu                      # ẩn mặc định
    assert all(win.menu[k].soon for k in ("workflow",)) and not win.menu["quick_tools"].soon   # tạm khóa
    assert "video_tools" not in win.menu and not win.menu["watermark"].soon
    assert not win.menu["upscale"].soon
    assert win.menu["lipsync"].soon                         # Clip Lip-Sync: tạm khóa
    assert "meta_vibes" not in win.menu and not win.menu["flow_image"].soon and not win.menu["download"].soon
    assert not any(win.menu[k].soon for k in ("gpt_image", "grok_image", "muse_image", "meta_muse", "grok_video"))   # đã mở
    for key in list(win.menu) + ["settings"]:
        win.go(key)
        qapp.processEvents()
        if key in ("settings", "logs"):                      # mở cửa sổ riêng
            assert win._popups[key].isVisible()
            win._popups[key].close()
        else:
            assert win.stack.currentWidget() is win.pages[key]


def test_flow_image_auto_accounts_and_refs(win, db, qapp, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(win.ctx.engine, "start_page", lambda *a: started.append(a))
    ids = []
    for n, st in (("a@x.com", "ok"), ("b@x.com", "ok"), ("c@x.com", "expired")):
        i = db.add_account("flow", n, str(tmp_path / n))
        db.update_account(i, status=st)
        ids.append(i)
    lib = win.ctx.characters
    r1 = lib.add(_img(tmp_path / "minh.png"), "Minh", "Nhân vật", "chàng trai")
    r2 = lib.add(_img(tmp_path / "pho.png", "blue"), "PhoCo", "Bối cảnh", "")
    win.go("flow_image")
    page = win.pages["flow_image"]
    page.editor.setPlainText("Bát phở bò\n\n@Minh trên phố cổ\n")
    page.count.set_value("3")
    assert "2 prompt" in page.pcount.text() and "2 tài khoản" in page.pcount.text()
    page._sync_drafts()
    assert [r["status"] for r in page.model.rows] == ["draft", "draft"]          # hiện ngay khi nhập
    page.start()
    assert page.editor.toPlainText() == "" and all(not r["draft"] for r in page.model.rows)
    jobs = db.query("SELECT prompt, count, mode, refs FROM jobs ORDER BY row_no")
    assert [j["mode"] for j in jobs] == ["t2i", "i2i"]          # @Tên → tự dùng tham chiếu
    assert jobs[1]["prompt"] == "Minh (chàng trai) trên phố cổ" and all(j["count"] == 3 for j in jobs)
    assert started[0][1] == ids[:2] and started[0][2] == 1      # 2 tài khoản sẵn sàng, mỗi tài khoản 1 tác vụ
    # không còn nút chế độ: tác vụ có ảnh riêng (+ @Tên) tự dùng Tham chiếu, không có ảnh = Văn bản → Ảnh
    assert page.mode_seg.isHidden()
    page.model.draft_refs = {"Bát phở bò": [lib.get(r2)["path"]], "@Minh trên phố cổ": [lib.get(r2)["path"]]}
    rows = page.build_rows(["Bát phở bò", "@Minh trên phố cổ", "Không có ảnh"])
    assert all(lib.get(r2)["path"] in r["refs"] for r in rows[:2]) and rows[1]["refs"][1] == lib.get(r1)["path"]
    assert [r["mode"] for r in rows] == ["i2i", "i2i", "t2i"]
    # tick chọn + xóa
    page.model.reload()
    page.model.set_all(True)
    assert len(page.model.checked) == 2
    monkeypatch.setattr("videoai.ui.pages.flow_page.QMessageBox.question", lambda *a, **k: 16384)
    page._delete_checked()
    assert db.query("SELECT COUNT(*) n FROM jobs")[0]["n"] == 0


def test_flow_video_frames_from_library(win, db, tmp_path, monkeypatch):
    monkeypatch.setattr(win.ctx.engine, "start_page", lambda *a: None)
    db.update_account(db.add_account("flow", "v@x.com", str(tmp_path / "v")), status="ok")
    lib = win.ctx.characters
    s = lib.add(_img(tmp_path / "s.png"), "Dau")
    win.go("flow_video")
    page = win.pages["flow_video"]
    page.mode_seg.set_value("Ảnh → Video")
    page._mode_changed("Ảnh → Video")
    page.editor.setPlainText("cảnh 1")
    page._sync_drafts()
    assert page.build_rows() is None                   # tác vụ chưa có ảnh
    assert not page.refs_box.isVisible() and not page.refs_hint.isVisibleTo(page)   # Ảnh → Video: không dòng nhắc
    assert page.model.rows[0]["frames"]                                               # tác vụ hiện 2 ô Bắt đầu / Kết thúc
    from videoai.ui import refs_ui
    monkeypatch.setattr(refs_ui.RefPickerDialog, "exec", lambda self: 1)
    monkeypatch.setattr(refs_ui.RefPickerDialog, "selected_ids", lambda self: [s])
    page._task_frame(page.model.rows[0], 1)                 # chỉ chọn ảnh Kết thúc → chưa chạy được
    assert page.model.rows[0]["refs_list"] == ["", lib.get(s)["path"]]
    assert page.build_rows() is None
    page._task_frame(page.model.rows[0], 0)                 # ô Bắt đầu trống → mở kho, chọn ảnh
    assert page.model.rows[0]["refs_list"] == [lib.get(s)["path"], lib.get(s)["path"]]
    page._task_frame(page.model.rows[0], 1)                 # ô Kết thúc đang có ảnh → bấm để bỏ
    assert page.model.rows[0]["refs_list"] == [lib.get(s)["path"]]
    page.model_cb.setCurrentText("Omni 1.2 Flash")
    page.dur.setValue(10)
    rows = page.build_rows()
    assert rows[0]["mode"] == "i2v" and rows[0]["refs"] == [lib.get(s)["path"]]
    page._task_frame(page.model.rows[0], 0)            # bấm ô Bắt đầu đang có ảnh → bỏ ảnh
    assert page.model.rows[0]["refs_list"] == []
    assert page._params()["durations"] == "10 giây"
    assert page._params()["quality"] == "720p" and page._params()["resolutions"] == "720p"   # mặc định tối thiểu (v2.1.8)
    page.quality.set_value("4K")
    page.model_cb.setCurrentText("Veo 3.1 - Lite")
    assert "durations" not in page._params() and page.dur_box.isHidden() and page._params()["quality"] == "4K"
    assert [page.model_cb.itemText(i) for i in range(page.model_cb.count())] == ["Omni 1.2 Flash", "Veo 3.1 - Lite"]


def test_refs_page(win, tmp_path, qapp, monkeypatch):
    monkeypatch.setattr("videoai.ui.refs_ui.ImportRefsDialog.exec", lambda self: 1)   # bấm "Thêm vào kho"
    win.go("refs")
    page = win.pages["refs"]
    page._drop([_img(tmp_path / "a.png"), _img(tmp_path / "b.png", "green")])
    qapp.processEvents()
    assert page.grid.count() == 2
    page.grid.set_all(True)
    assert len(page.grid.checked_ids()) == 2


def test_draft_tasks_edit_and_run_selected(win, db, qapp, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(win.ctx.engine, "start_page", lambda *a: started.append(a))
    db.update_account(db.add_account("flow", "d@x.com", str(tmp_path / "d")), status="ok")
    win.go("flow_image")
    page = win.pages["flow_image"]
    page.quality.set_value("2K")
    page.editor.setPlainText("mèo\nchó\ngà")
    page._sync_drafts()
    m = page.model
    assert [r["prompt"] for r in m.rows] == ["mèo", "chó", "gà"]
    from videoai.ui.task_table import C_PROMPT
    assert m.setData(m.index(1, C_PROMPT), "chó con chạy trên cỏ")
    assert page.editor.toPlainText().splitlines()[1] == "chó con chạy trên cỏ"   # sửa riêng dòng 2
    m.checked = {m.rows[2]["id"]}
    page.run_selected()
    assert page.editor.toPlainText().splitlines() == ["mèo", "chó con chạy trên cỏ"]
    jobs = db.query("SELECT j.prompt FROM jobs j JOIN batches b ON b.id=j.batch_id")
    assert [j["prompt"] for j in jobs] == ["gà"]
    assert '"quality": "2K"' in db.query("SELECT params FROM batches")[0]["params"]
    # sửa prompt của tác vụ đã tạo không ảnh hưởng tác vụ khác
    page.model.reload()
    real = [i for i, r in enumerate(page.model.rows) if not r["draft"]][0]
    m.setData(m.index(real, C_PROMPT), "gà trống gáy")
    assert db.query("SELECT prompt FROM jobs")[0]["prompt"] == "gà trống gáy"


def test_viewer_and_import_names(win, tmp_path, qapp):
    from videoai.ui.viewer import MediaViewer
    a, b = _img(tmp_path / "a.png"), _img(tmp_path / "b.png", "blue")
    v = MediaViewer(win, [{"path": a, "kind": "image"}, {"path": b, "kind": "image"}], "thử")
    v.show_index(1)
    assert v.i == 1 and "2 / 2" in v.counter.text()
    v.close()
    # khung theo tỷ lệ ảnh (9:16 dọc), không chữ / tên file, lăn chuột phóng to – thu nhỏ
    from PySide6.QtGui import QColor, QImage, QWheelEvent
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtWidgets import QLabel
    im = QImage(540, 960, QImage.Format_RGB32)
    im.fill(QColor("green"))
    tall = str(tmp_path / "tall.png")
    im.save(tall)
    v = MediaViewer(win, [{"path": tall, "kind": "image"}], "prompt dài không được hiện")
    v.show()
    qapp.processEvents()
    assert abs(v.width() / v.height() - 540 / 960) < 0.03
    assert not [l for l in v.findChildren(QLabel) if l.isVisible() and l.text()]
    assert not v.b_prev.isVisible()
    z0 = v.view.transform().m11()

    def wheel(dy):
        c = QPointF(v.view.viewport().rect().center())
        ev = QWheelEvent(c, QPointF(v.view.viewport().mapToGlobal(c.toPoint())), QPoint(0, 0), QPoint(0, dy),
                         Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
        v.view.wheelEvent(ev)
    wheel(120)
    wheel(120)
    assert v.view.transform().m11() > z0 * 1.25
    for _ in range(6):
        wheel(-120)
    assert abs(v.view.transform().m11() - z0) < 0.01          # không nhỏ hơn vừa khung
    v.close()
    from videoai.ui.refs_ui import ImportRefsDialog
    d = ImportRefsDialog(win, win.ctx.characters, [a, b], "Bối cảnh")
    d.rows[0][1].setText("ChoNoi")
    d.rows[0][2].setText("chợ nổi sáng sớm")
    ids = d.save()
    r = win.ctx.characters.get(ids[0])
    assert r["name"] == "ChoNoi" and r["description"] == "chợ nổi sáng sớm" and r["grp"] == "Bối cảnh"


def test_per_task_refs_and_free_tier(win, db, qapp, tmp_path, monkeypatch):
    """Ảnh tham chiếu riêng từng tác vụ + gói Miễn phí chỉ 1 tác vụ/lần."""
    import json
    from PySide6.QtGui import QColor, QImage
    started = []
    monkeypatch.setattr(win.ctx.engine, "start_page", lambda *a: started.append(a))
    db.update_account(db.add_account("flow", "r@x.com", str(tmp_path / "r")), status="ok")
    imgs = []
    for i, c in enumerate(["red", "green", "blue"]):
        im = QImage(32, 32, QImage.Format_RGB32)
        im.fill(QColor(c))
        p = str(tmp_path / f"i{i}.png")
        im.save(p)
        imgs.append(p)
    win.go("flow_video")
    page = win.pages["flow_video"]
    page.editor.setPlainText("cảnh 1\ncảnh 2")
    page._sync_drafts()
    r0 = page.model.rows[0]
    page._set_task_refs(r0, imgs[:2])
    assert page.model.rows[0]["refs_list"] == imgs[:2] and page.model.rows[1]["refs_list"] == []
    rows = page.build_rows(["cảnh 1", "cảnh 2"])
    assert rows[0]["mode"] == "compose" and rows[0]["refs"] == imgs[:2]     # Văn bản → Video + ảnh riêng = Tham chiếu
    assert rows[1]["mode"] == "t2v" and rows[1]["refs"] == []
    # Ảnh → Video: ảnh riêng của tác vụ làm khung đầu/cuối, không cần ô Ảnh đầu chung
    page.mode_seg.set_value("Ảnh → Video")
    page._mode_changed("Ảnh → Video")
    rows = page.build_rows(["cảnh 1"])
    assert rows[0]["mode"] == "i2v" and rows[0]["refs"] == imgs[:2]
    # đổi ảnh cho tác vụ đã tạo
    page.mode_seg.set_value("Văn bản → Video")
    page._mode_changed("Văn bản → Video")
    page.editor.setPlainText("cảnh 2")
    page._sync_drafts()
    page.start()
    job = db.query("SELECT * FROM jobs")[0]
    page.model.reload()
    real = next(r for r in page.model.rows if not r["draft"])
    db.update_job(real["id"], status="failed")
    page.model.reload()
    real = next(r for r in page.model.rows if not r["draft"])
    page._set_task_refs(real, [imgs[2]])
    j = db.one("SELECT * FROM jobs WHERE id=?", (job["id"],))
    assert json.loads(j["refs"]) == [imgs[2]] and j["mode"] == "compose"

    # gói Miễn phí
    from videoai.core.license import Status
    win.lic.status = Status(False, reason="none")
    shown = []
    monkeypatch.setattr(win, "upsell", lambda reason: shown.append(reason))
    win._apply_tier()
    assert win.ctx.engine.max_total == 1
    page.editor.setPlainText("a\nb")
    page._sync_drafts()
    n_before = db.one("SELECT COUNT(*) n FROM jobs")["n"]
    page.start()                                               # 2 prompt → bị chặn (mỗi lần 1 prompt)
    assert shown and db.one("SELECT COUNT(*) n FROM jobs")["n"] == n_before
    page.editor.setPlainText("a")
    page._sync_drafts()
    page.start()                                               # 1 prompt → chạy
    assert db.one("SELECT COUNT(*) n FROM jobs")["n"] == n_before + 1
    page.apply_tier()
    assert page.editor.isReadOnly()                            # đang có tác vụ chạy → khóa ô nhập
    page.editor.setPlainText("c")
    page._sync_drafts()
    shown.clear()
    page.start()                                               # tác vụ trước chưa xong → chặn
    assert shown and db.one("SELECT COUNT(*) n FROM jobs")["n"] == n_before + 1
    db.execute("UPDATE jobs SET status='done'")
    page.apply_tier()
    assert not page.editor.isReadOnly()
    assert win.ctx.engine.max_total == 1
    # Xóa tất cả: không cần tick
    page.editor.setPlainText("x\ny")
    page._sync_drafts()
    page._delete_all(confirm=False)
    assert page.model.rowCount() == 0 and page.editor.toPlainText() == ""
    assert db.one("SELECT COUNT(*) n FROM jobs j JOIN batches b ON b.id=j.batch_id WHERE b.page='flow_video'")["n"] == 0


def test_eula_and_social(win, qapp):
    from videoai.ui.eula_ui import EulaDialog
    from videoai.ui.main_window import SOCIAL, SocialButton
    assert any("0979007367" in u for _, u, _, _ in SOCIAL)
    d = EulaDialog(win, first_run=True)
    assert not d.b_ok.isEnabled()
    d.show()
    qapp.processEvents()
    sb = d.text.verticalScrollBar()
    sb.setValue(sb.maximum())
    d.agree.setChecked(True)
    assert d.b_ok.isEnabled()
    d.close()
    btns = win.findChildren(SocialButton)
    assert len(btns) == 3 and all(not b.toolTip() for b in btns)
    assert "eula" not in win.menu and win.brand.b_eula.text() == "Thông tin bản quyền"
    win.go("flow_image")
    win.open_settings()
    st = win.pages["settings"]
    assert list(st.lang_btns) == ["vi", "en", "zh", "hi", "ja", "ko"] and len(st.theme_btns) == 4
    assert win.page_title.text() == "Tạo ảnh Flow"


def test_guide_button_and_wide_menu(win, qapp, monkeypatch):
    opened = []
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda u: opened.append(u.toString()))
    win.guides = {"flow_video": "https://youtu.be/vid2"}
    win.go("flow_image")
    assert win.b_guide.isHidden()                          # chưa có link cho chức năng này → ẩn nút
    win.go("flow_video")
    assert not win.b_guide.isHidden()
    win.b_guide.click()
    assert opened == ["https://youtu.be/vid2"]
    assert win.minimumWidth() >= 1324
    side = win.menu["flow_video"].window()
    from videoai.ui.widgets import MenuButton
    b = win.menu["meta_muse"]
    assert b.fontMetrics().horizontalAdvance(b.text()) < b.width() - 100   # tên dài vẫn hiện đủ cạnh nhãn "sắp có"


def test_update_dialog_mandatory_and_button(win, qapp, monkeypatch):
    """Có bản mới: nút ở menu đổi chữ; bản bắt buộc (min_version) không đóng được bằng Esc/Để sau."""
    from PySide6.QtCore import QTimer
    from videoai.core import updater
    from videoai.ui import updater_ui
    info = {"version": "99.0.0", "url": "https://x.example/s.exe", "notes": "- mới", "min_version": "99.0.0"}
    monkeypatch.setattr(updater, "manifest_url", lambda db=None: "https://x.example/v")
    monkeypatch.setattr(updater, "check", lambda db=None, timeout=15, **kw: info)
    monkeypatch.setattr(updater_ui.UpdateDialog, "start", lambda self: None)    # không tải thật
    seen = {}

    def fake_exec(self):
        seen["mandatory"] = self.mandatory
        seen["later"] = self.b_later.text()
        self.reject()                       # Esc → bị bỏ qua vì bắt buộc
        seen["still_open"] = self.result() == 0 and not getattr(self, "_closed", False)
        return 0
    monkeypatch.setattr(updater_ui.UpdateDialog, "exec", fake_exec)
    win.ctx.db.set_setting("auto_update", False)
    updater_ui.check_update(win, manual=False)
    import time
    for _ in range(300):
        qapp.processEvents()
        if seen:
            break
        time.sleep(0.02)
    assert seen, win.b_update.text()
    assert seen.get("mandatory") is True and seen["later"] != "Để sau"
    assert "99.0.0" in win.b_update.text()
    assert win._upd_info["version"] == "99.0.0" and not win._upd_open


def test_flow_video_extend_mode(win, qapp):
    """Tạo Video Flow: chế độ Kéo dài Video thay cho Tham chiếu; prompt 'cảnh đầu || đoạn kéo dài'."""
    page = win.go("flow_video") or win.pages["flow_video"]
    labels = [m.label for m in page.pdef.modes]
    assert "Kéo dài" in labels and "Tham chiếu" not in labels
    page.mode_seg.set_value("Kéo dài")
    page._mode_changed("Kéo dài")
    assert not page.ext_box.isHidden() and page.count_box.isHidden() and page.quality_box.isHidden()
    page.ext.setValue(6)
    assert page._params()["extend_secs"] == 6
    assert page.build_rows(["Chỉ có một cảnh"]) is None           # thiếu đoạn kéo dài → nhắc
    rows = page.build_rows(["Cô gái ngồi uống trà || Cô đứng dậy || Cô đi vào nhà"])
    assert rows[0]["mode"] == "extend" and rows[0]["count"] == 1
    page.mode_seg.set_value("Văn bản → Video")
    page._mode_changed("Văn bản → Video")
    assert page.ext_box.isHidden() and not page.count_box.isHidden()


def test_update_loop_guard(win, qapp, monkeypatch):
    """Đã cài bản X mà phần mềm vẫn là bản cũ → không tự cài lại (tránh vòng lặp cài – khởi động lại)."""
    import time
    from videoai.core import updater
    from videoai.core.paths import APP_VERSION
    from videoai.ui import updater_ui
    info = {"version": "99.1.0", "url": "https://x.example/s.exe", "notes": ""}
    monkeypatch.setattr(updater, "manifest_url", lambda db=None: "https://x.example/v")
    monkeypatch.setattr(updater, "check", lambda db=None, timeout=15, **kw: info)
    shown = []
    monkeypatch.setattr(updater_ui, "_show", lambda w, i, auto: shown.append(i["version"]))
    win.ctx.db.set_setting("update_attempt", {"version": "99.1.0", "from": APP_VERSION, "n": 1})
    win._upd_info = None
    updater_ui.check_update(win, manual=False)
    for _ in range(150):
        qapp.processEvents()
        if "99.1.0" in win.b_update.text():
            break
        time.sleep(0.02)
    assert not shown and "không thành công" in win.b_update.text()
    win.ctx.db.set_setting("update_attempt", {"version": "99.1.0", "from": "0.0.1", "n": 1})   # đã lên bản khác → xóa dấu
    win.check_update = type(win).check_update.__get__(win)
    monkeypatch.setattr(updater_ui, "check_update", lambda w, manual=False: None)
    win.check_update()
    assert win.ctx.db.get_setting("update_attempt", {}) == {}


def test_ref_cells_hit_individual_images(qapp):
    from PySide6.QtCore import QRectF
    from videoai.ui.task_table import ref_cells
    cells, plus = ref_cells(QRectF(0, 0, 200, 60), 2, True)
    assert len(cells) == 2 and plus is not None
    assert not cells[0].intersects(cells[1]) and not cells[1].intersects(plus)
    cells, plus = ref_cells(QRectF(0, 0, 200, 60), 3, False)
    assert len(cells) == 3 and plus is None



def _wait(qapp, cond, secs=60):
    import time
    t = time.time()
    while not cond() and time.time() - t < secs:
        qapp.processEvents()
        time.sleep(0.02)
    return cond()


def test_upscale_page_progress_and_compare(win, qapp, tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from videoai.ui.pages.upscale_page import CompareDialog
    a = _img(tmp_path / "a.png")
    win.go("upscale")
    pg = win.pages["upscale"]
    pg.out.edit.setText(str(tmp_path / "out"))
    pg._dropped([str(a)])
    seen = []
    orig = pg._progress
    pg._progress = lambda p, m: (seen.append(p), orig(p, m))
    pg.run()
    assert pg.busy and not pg.b_run.isEnabled()
    assert _wait(qapp, lambda: not pg.busy, 90)
    assert seen and str(a) in pg.results
    from PySide6.QtGui import QImageReader
    assert QImageReader(pg.results[str(a)]).size().width() == QImageReader(str(a)).size().width() * 4
    d = CompareDialog(str(a), pg.results[str(a)], win)
    d.show()
    qapp.processEvents()
    v = d.view
    from PySide6.QtCore import QPointF
    t = v._target()
    v._set_split(t.left() + t.width() * 0.25)
    assert abs(v.split - 0.25) < 0.01
    d.close()


def test_voice_button_next_to_license(win):
    lay = win.b_lic.parentWidget().layout()
    idx = [lay.indexOf(w) for w in (win.b_voice, win.b_lic)]
    assert idx[0] >= 0 and idx[1] == idx[0] + 2          # nút giọng nói ngay trước nút gói (cách 1 khoảng trống)


def test_download_page_flow(win, qapp, tmp_path):
    import pytest
    pytest.importorskip("yt_dlp")
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
    from test_media import _serve_clip
    srv, url = _serve_clip(tmp_path)
    try:
        win.go("download")
        pg = win.pages["download"]
        pg.out.edit.setText(str(tmp_path / "dl"))
        pg.links.setPlainText(f"xem {url}\n{url}\nkhông phải link")
        pg.run()
        assert len(pg.rows) == 1 and pg.busy
        assert _wait(qapp, lambda: not pg.busy, 120)
        r = pg.rows[0]
        assert r["state"] == "done" and r["file"].endswith(".mp4"), r
        assert pg.table.item(0, 4).text().startswith("✓")
    finally:
        srv.shutdown()


def test_upscale_popup_keeps_aspect(qapp, tmp_path):
    from PySide6.QtGui import QImage, QColor
    from videoai.ui.pages.upscale_page import popup_size, BAR_H
    for (w, h) in ((1280, 720), (720, 1280), (800, 800)):
        p = tmp_path / f"{w}x{h}.png"
        im = QImage(w, h, QImage.Format_RGB32)
        im.fill(QColor("red"))
        im.save(str(p))
        pw, ph = popup_size(str(p), None, 1920, 1080)
        assert abs(pw / (ph - BAR_H) - w / h) < 0.02, (w, h, pw, ph)


def test_settings_tabs_and_ai_agent_no_api(win, db, qapp):
    win.open_settings()
    sp = win.pages["settings"]
    assert [sp.tabs.tabText(i) for i in range(sp.tabs.count())] == ["Tài khoản", "AI Agent", "Thống kê"]
    assert not hasattr(sp, "ai_acc")                                            # không còn ô chọn tài khoản
    aid = db.add_account("gpt", "g@x", "/tmp/p")
    db.update_account(aid, status="ok")
    gid = db.add_account("flow", "f@x", "/tmp/pf")
    db.update_account(gid, status="ok")
    kid = db.add_account("grok", "k@x", "/tmp/pk")
    db.update_account(kid, status="ok")
    sp._reload_ai_accounts()
    rows = [(sp.ai_list.item(r, 0).text(), sp.ai_list.item(r, 1).text()) for r in range(sp.ai_list.rowCount())]
    assert rows == [("1", "Chat GPT · g@x")]                                    # chỉ Chat GPT (bỏ Gemini, Grok, Muse)
    assert set(sp.api_rows) == {"gemini", "openai"}                             # v2.1.6: khung API key + nút Lấy API
    # bấm vào hàng → tick chọn; bấm lần nữa → bỏ chọn
    sp._reload_accounts()
    r = next(i for i, a in enumerate(sp.accs) if a["id"] == kid)
    sp.acc_table.cellClicked.emit(r, 2)
    from PySide6.QtCore import Qt
    assert sp._acc_checked == {kid} and sp.acc_table.item(r, 0).checkState() == Qt.Checked
    sp.acc_table.cellClicked.emit(r, 3)
    assert sp._acc_checked == set()
    # chuột phải vào hàng → menu thao tác cho riêng hàng đó
    y = sp.acc_table.rowViewportPosition(r) + 5
    from PySide6.QtCore import QPoint
    sp._acc_menu(QPoint(20, y))
    m = sp._last_menu
    names = [a.text() for a in m.actions() if a.text()]
    assert names[1:] == ["Mở để đăng nhập", "Kiểm tra", "Bật dùng", "Tắt dùng", "Đổi tên", "Đóng trình duyệt", "Xóa"]
    assert sp._acc_checked == {kid}
    next(a for a in m.actions() if a.text() == "Tắt dùng").trigger()
    assert db.one("SELECT enabled FROM accounts WHERE id=?", (kid,))["enabled"] == 0
    m.close()

def test_download_done_row_has_folder_and_eye(win, qapp, tmp_path, monkeypatch):
    f = tmp_path / "v.mp4"
    f.write_bytes(b"x")
    win.go("download")
    pg = win.pages["download"]
    pg.links.setPlainText("https://youtu.be/abc")
    pg.add_links()
    assert pg.table.cellWidget(0, 5) is None
    pg.rows[0].update(state="done", file=str(f), title="t")
    pg._render()
    w = pg.table.cellWidget(0, 5)
    from PySide6.QtWidgets import QPushButton
    btns = w.findChildren(QPushButton)
    assert len(btns) == 2
    seen = []
    monkeypatch.setattr(pg, "reveal", lambda p: seen.append(("dir", p)))
    monkeypatch.setattr(pg, "view", lambda p: seen.append(("eye", p)))
    pg._render()                                  # dựng lại với hàm đã thay
    pg.table.removeCellWidget(0, 5)
    pg._render()
    for b in pg.table.cellWidget(0, 5).findChildren(QPushButton):
        b.click()
    assert seen == [("dir", str(f)), ("eye", str(f))]


def test_bulk_refs_to_checked_tasks(win, db, qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QColor, QImage
    from videoai.ui import refs_ui
    win.go("flow_image")
    page = win.pages["flow_image"]
    ids = []
    for i, c in enumerate(["red", "green"]):
        im = QImage(32, 32, QImage.Format_RGB32)
        im.fill(QColor(c))
        p = str(tmp_path / f"b{i}.png")
        im.save(p)
        ids.append(page.lib.add(p, f"Anh{i}"))
    page.editor.setPlainText("một\nhai\nba")
    page._sync_drafts()
    page.model.checked = {page.model.rows[0]["id"], page.model.rows[2]["id"]}
    page._set_task_refs(page.model.rows[2], page.lib.paths(ids[:1]), quiet=True)   # tác vụ 3 đã có ảnh 1

    class FakePicker:
        def __init__(self, *a, **k):
            pass

        def exec(self):
            return True

        def selected_ids(self):
            return ids
    monkeypatch.setattr(refs_ui, "RefPickerDialog", FakePicker)
    page.b_bulk_refs.click()
    rows = page.model.rows
    paths = page.lib.paths(ids)
    assert rows[0]["refs_list"] == paths            # đã tick → thêm cả 2 ảnh
    assert rows[1]["refs_list"] == []               # không tick → giữ nguyên
    assert rows[2]["refs_list"] == paths            # đã có ảnh 1 → chỉ thêm ảnh 2, không trùng


def test_stat_cards_show_all_platform_tasks_in_page(win, db, qapp, tmp_path, monkeypatch):
    """Bấm ô đếm: không mở cửa sổ mới, danh sách tác vụ của trang hiện đúng tác vụ trạng thái đó của mọi nền tảng."""
    b1 = db.create_batch("grok", "grok_video", {}, str(tmp_path), "flat", [{"mode": "t2v", "prompt": "lỗi grok", "count": 1}])
    b2 = db.create_batch("flow", "flow_image", {}, str(tmp_path), "flat", [{"mode": "t2i", "prompt": "lỗi flow", "count": 1},
                                                                            {"mode": "t2i", "prompt": "xong flow", "count": 1}])
    jobs = {r["prompt"]: r["id"] for r in db.query("SELECT id, prompt FROM jobs")}
    db.update_job(jobs["lỗi grok"], status="failed", error_code="timeout")
    db.update_job(jobs["lỗi flow"], status="blocked")
    db.update_job(jobs["xong flow"], status="done")
    from PySide6.QtWidgets import QDialog
    opened = []
    monkeypatch.setattr(QDialog, "exec", lambda self: opened.append(self))
    win.go("flow_image")
    pg = win.pages["flow_image"]
    pg.editor.setPlainText("nháp")
    pg._sync_drafts()
    pg.cards["failed"].clicked.emit("failed")
    assert not opened and win._cur_page == "flow_image"
    assert {r["prompt"] for r in pg.model.rows} == {"lỗi grok", "lỗi flow"}          # cả tác vụ của Grok, không có nháp
    assert not pg.scope_bar.isHidden() and "Lỗi" in pg.scope_lbl.text()
    from videoai.ui.task_table import C_PROMPT
    i = next(k for k, r in enumerate(pg.model.rows) if r["prompt"] == "lỗi grok")
    assert pg.model.data(pg.model.index(i, C_PROMPT)).startswith("[Tạo Video Grok]")
    started = []
    monkeypatch.setattr(win.ctx.engine, "start_page", lambda *a: started.append(a[0]))
    db.update_account(db.add_account("grok", "gk", str(tmp_path / "gk")), status="ok")
    pg._requeue([pg.model.rows[i]])                          # chạy lại tác vụ của trang khác: đúng trang Grok
    assert db.one("SELECT status FROM jobs WHERE id=?", (jobs["lỗi grok"],))["status"] == "queued"
    assert started == ["grok_video"]
    pg.cards["done"].clicked.emit("done")
    assert [r["prompt"] for r in pg.model.rows] == ["xong flow"]
    pg.cards["done"].clicked.emit("done")                    # bấm lại: về danh sách của trang
    assert pg.model.scope is None and pg.scope_bar.isHidden()
    assert any(r.get("draft") for r in pg.model.rows)


def test_free_plan_ai_agent_one_prompt(win, db, qapp, monkeypatch):
    from videoai.core.license import Status
    from videoai.services import llm
    win.lic.status = Status(False, reason="none")
    win._apply_tier()
    got, shown = [], []
    monkeypatch.setattr(llm, "fix_prompts", lambda db_, ps, eng=None, st=None: (got.append(list(ps)), [p.upper() for p in ps])[1])
    monkeypatch.setattr(llm, "write_story", lambda db_, idea, n, eng=None, st=None: (got.append(n), [f"scene {i}" for i in range(n)])[1])
    monkeypatch.setattr(win, "upsell", lambda reason, detail=None: shown.append(reason))
    win.go("flow_image")
    pg = win.pages["flow_image"]
    pg.editor.setPlainText("a\nb\nc")
    pg._ai_fix()
    assert _wait(qapp, lambda: not pg._ai_busy, 10)
    assert got[-1] == ["a"] and pg.editor.toPlainText().splitlines() == ["A", "b", "c"]
    assert shown


def test_ai_agent_button_fixes_prompts_directly(win, qapp, monkeypatch):
    """Nút "AI Agent": không còn menu, bấm là sửa ngay các prompt có sẵn (mọi trang tạo ảnh / video)."""
    for key in ("flow_image", "flow_video", "grok_image", "meta_muse"):
        win.go(key)
        pg = win.pages[key]
        called = []
        monkeypatch.setattr(pg, "_ai_fix", lambda *a, c=called: c.append(1))
        pg.b_ai.clicked.disconnect()
        pg.b_ai.clicked.connect(pg._ai_fix)
        assert pg.b_ai.text() == "Tối ưu Prompt của bạn"
        pg.b_ai.click()
        assert called == [1], key



def test_lipsync_page_pairs_and_free_cooldown(win, db, qapp, tmp_path, monkeypatch, clip):
    from videoai.media import ffmpeg
    img = _img(tmp_path / "nv.png")
    from videoai.ui.pages.lipsync_page import LipSyncPage      # đang tạm khóa trên menu, vẫn kiểm thử mã
    from videoai.core.platforms import PAGE_BY_KEY
    pg = LipSyncPage(win.ctx, PAGE_BY_KEY["lipsync"])
    win.pages["lipsync"] = pg
    assert pg.dur.value() == 8 and pg.quality.value() == "720p" and pg.count.value() == "1"
    pg.drafts.clear()
    pg.add_paths([clip, img])                                # 1 video + 1 ảnh → 1 tác vụ đủ cặp
    assert pg.drafts == [{"video": clip, "image": img}]
    pg._add_pairs([(clip, None)])                            # thêm video → dòng mới thiếu ảnh
    pg._add_pairs([(None, img)])                             # thêm ảnh → gắn vào dòng đang thiếu ảnh
    assert len(pg.drafts) == 2 and all(d["video"] and d["image"] for d in pg.drafts)
    pg.refresh()
    assert pg.table.rowCount() == 2
    # gói Miễn phí: nhiều tác vụ → chặn; 1 tác vụ → chạy; xong rồi phải chờ 10 phút
    from videoai.core.license import Status
    win.lic.status = Status(False, reason="none")
    win._apply_tier()
    shown, started = [], []
    monkeypatch.setattr(win, "upsell", lambda reason, detail=None: shown.append(reason))
    monkeypatch.setattr(win.ctx.engine, "start_page", lambda *a: started.append(a[0]))
    db.update_account(db.add_account("flow", "lf", str(tmp_path / "lf")), status="ok")
    pg.start()
    assert shown and not started                             # 2 tác vụ → chặn
    shown.clear()
    pg.drafts = pg.drafts[:1]
    pg.start()
    assert started == ["lipsync"] and not pg.drafts
    job = db.query("SELECT j.* FROM jobs j JOIN batches b ON b.id=j.batch_id WHERE b.page='lipsync'")[0]
    assert json.loads(job["refs"]) == [clip, img] and job["mode"] == "lipsync"
    from videoai.core.db import now
    db.update_job(job["id"], status="done", finished_at=now())
    assert 590 <= pg.cooldown_left() <= 600
    pg._free_ui()
    assert not pg.free_box.isHidden() and pg.b_start.text().startswith("Chờ")
    pg._add_pairs([(clip, img)])
    pg.start()
    assert shown and "chờ" in shown[-1]             # đang trong 10 phút chờ → thông báo nâng cấp


def test_script_dialog_to_tasks(win, db, qapp, tmp_path, monkeypatch):
    """Nút Quy trình tự động (bên phải tiêu đề khung Cấu hình) → popup: chủ đề, ảnh NV/SP/BC + giọng, thời lượng → AI viết → Lưu: mỗi cảnh
    thành 1 tác vụ có ảnh + tham số riêng (khung đầu, giọng, nối cảnh)."""
    from videoai.services import script as S
    from videoai.ui import script_dialog as SD
    from videoai.core.license import Status
    from PySide6.QtWidgets import QDialog
    monkeypatch.setattr(type(win), "is_pro", lambda self: True)
    win.go("flow_video")
    pg = win.pages["flow_video"]
    assert pg.b_script.text() == "Quy trình tự động" and pg.b_ai.text() == "Tối ưu Prompt của bạn"
    hdr = pg.b_script.parentWidget()                       # nằm bên phải tiêu đề khung "Cấu hình tạo video"
    from PySide6.QtWidgets import QLabel
    assert "Cấu hình tạo video" in [x.text() for x in hdr.findChildren(QLabel)]
    acc = db.add_account("gpt", "ai", str(tmp_path / "ai"))
    db.update_account(acc, status="ok")
    got = {}

    def fake_gen(db_, eng, b, st=None):
        got["brief"] = b
        return {"profiles": {}, "scenes": [{"time": "", "title": f"c{i}", "refs": ["NV1", "SP1"] if i == 0 else ["BC1"],
                                            "frame": f"khung {i}", "prompt": f"cảnh số {i}"} for i in range(b.n)]}
    monkeypatch.setattr(S, "generate", fake_gen)
    opened = {}

    def run(d):
        opened["d"] = d
        d.sec["NV"].add_paths([_img(tmp_path / "nv.png")])
        d.sec["SP"].add_paths([_img(tmp_path / "sp.png", "blue")])
        d.sec["BC"].add_paths([_img(tmp_path / "bc.png", "green")])
        d.sec["NV"].refs[0].voice = "Leda"
        d.sec["NV"].render()
        d.topics.button(1).click()                    # Quảng cáo
        d.idea.setPlainText("quảng cáo nước hoa")
        d.dur.setValue(3)
        assert d.cons.value() == "Nhanh" and "nhanh nhất" in d.cons_note.text()      # v2.1.10: mặc định Nhanh
        d.cons.btns["Nhất quán cao"].click()
        assert "CHẬM" in d.cons_note.text()
        d.chain.setChecked(True)
        d.generate()
        assert _wait(qapp, lambda: not d.busy and d.cards, 10)
        assert len(d.cards) == 3 and d.b_save.text() == "Bắt đầu chạy (3)"
        assert d.b_gen.text() == "Phân tích và tạo kịch bản"
        d.cards[1].edit.setPlainText("cảnh hai đã sửa")
        d.delete_scene(2)
        assert len(d.cards) == 2
        d.save()
        return QDialog.Accepted
    monkeypatch.setattr(SD.ScriptDialog, "exec", run)
    pg.open_script()
    b = got["brief"]
    assert b.topic == "ads" and b.n == 3 and [r.tag for r in b.refs] == ["NV1", "SP1", "BC1"] and b.refs[0].voice == "Leda"
    assert b.clip_secs == pg.clip_secs() and b.keyframe
    lines = pg._prompts()
    assert lines[-2:] == ["cảnh số 0", "cảnh hai đã sửa"] and pg.mode == "t2v"
    p0 = pg.draft_params["cảnh số 0"]
    assert p0["keyframe"] and p0["voices"] == ["Leda"] and p0["frame_prompt"] == "khung 0"
    assert pg.draft_params["cảnh hai đã sửa"]["chain"]
    assert [Path(x).name for x in pg.model.draft_refs["cảnh số 0"]] == ["NV1.png", "SP1.png"]
    rows = pg.build_rows(lines[-2:])
    assert rows[0]["mode"] == "compose" and rows[0]["params"]["keyframe"] and rows[1]["params"]["scene"] == 2
    # giọng nói: hộp chọn có 29 giọng, lọc Nữ
    vp = SD.VoicePicker(opened["d"], win.ctx, "NV1", "Leda")
    assert len(vp.cards) == 29
    vp.filt.button(1).click()
    assert all(S.voice_gender(n) == "Nữ" for n in vp.cards) and "Leda" in vp.cards
    vp._choose("Kore")
    assert vp.chosen == "Kore"


def test_script_dialog_other_platform_and_free(win, db, qapp, tmp_path, monkeypatch):
    from videoai.ui import script_dialog as SD
    from videoai.core.license import Status
    win.lic.status = Status(False, reason="none")
    win._apply_tier()
    win.go("grok_video")
    pg = win.pages["grok_video"]
    d = SD.ScriptDialog(pg)
    assert d.dur.maximum() == 1 and d.cons_box.isVisibleTo(d) and d.clip == 6
    win.go("flow_image")                                   # gói Miễn phí: popup ảnh cũng chỉ 1 ảnh = 1 prompt
    di = SD.ScriptDialog(win.pages["flow_image"])
    di.dur.setValue(5)
    assert di.dur.maximum() == 1 and di.dur.value() == 1 and di.brief().n == 1
    di.deleteLater()
    win.go("grok_video")
    nv, sp = _img(tmp_path / "nv.png"), _img(tmp_path / "sp.png", "blue")
    d.sec["NV"].add_paths([nv])
    assert d.sec["NV"].findChildren(SD.RefTile)[0].voice_btn is not None   # Grok: chọn kiểu giọng (mô tả trong prompt)
    pg.add_script_tasks([{"prompt": "cảnh A", "refs": [nv, sp], "params": {"scene": 1, "keyframe": True}},
                         {"prompt": "cảnh B", "refs": [], "params": {"scene": 2}},
                         {"prompt": "cảnh C", "refs": [nv, sp], "params": {"scene": 3}}])
    rows = pg.build_rows(["cảnh A", "cảnh B", "cảnh C"])
    # v2.1.11: Văn bản → Video – ảnh của cảnh là ảnh tham chiếu (compose), không phải ảnh Bắt đầu / Kết thúc
    assert [r["mode"] for r in rows] == ["compose", "t2v", "compose"] and "_mode" not in rows[0]["params"]
    assert not any(r["frames"] for r in pg.model.rows if r.get("draft"))
    assert len(rows[0]["refs"]) == 2 and len(rows[2]["refs"]) == 1
    d.deleteLater()


def test_script_dialog_muse_talk_toggle(win, qapp, tmp_path, monkeypatch):
    """v2.0: Lời thoại là hàng nút Tiếng Việt / Tiếng Anh / Không thoại (Muse mặc định có thoại). Không thoại → không có
    nút giọng, kịch bản gửi AI Agent là không thoại (nhịp nhanh + nhạc nền). Tỷ lệ video theo đúng nền tảng."""
    from videoai.ui import script_dialog as SD
    monkeypatch.setattr(type(win), "is_pro", lambda self: True)
    win.go("meta_muse")
    d = SD.ScriptDialog(win.pages["meta_muse"])
    assert list(d.lang.btns) == SD.LANG_SHORT and d.lang.value() == "Tiếng Việt"
    assert d.voices_on() and not d.brief().silent and d.brief().lang == "Tiếng Việt"
    assert d.ratio.currentText() == win.pages["meta_muse"].ratio_value()   # popup lấy tỷ lệ từ khung Cấu hình
    d.sec["NV"].add_paths([_img(tmp_path / "nv.png")])
    assert d.sec["NV"].findChildren(SD.RefTile)[0].voice_btn is not None
    d.lang.btns["Không thoại"].click()
    d._lang_changed()
    assert not d.voices_on()
    assert all(t.voice_btn is None for t in d.sec["NV"].findChildren(SD.RefTile) if t.isVisibleTo(d))
    b = d.brief()
    assert b.platform == "muse" and b.silent
    d.style.btns["Anime"].click()
    assert d.brief().style == "Anime"
    d.deleteLater()
    win.go("grok_video")
    d2 = SD.ScriptDialog(win.pages["grok_video"])
    assert d2.ratio.currentText() == win.pages["grok_video"].ratio_value()
    d2.deleteLater()


def test_script_start_runs_only_new_tasks(win, db, qapp, tmp_path, monkeypatch):
    """Nút "Bắt đầu chạy": đưa toàn bộ cảnh vào tác vụ, tự chọn đúng các tác vụ vừa thêm và chạy ngay;
    prompt nháp / tác vụ cũ giữ nguyên."""
    monkeypatch.setattr(type(win), "is_pro", lambda self: True)
    win.go("grok_video")
    pg = win.pages["grok_video"]
    acc = db.add_account("grok", "g1", str(tmp_path / "g1"))
    db.update_account(acc, status="ok")
    started = []
    monkeypatch.setattr(win.ctx.engine, "start_page", lambda *a, **k: started.append(a[0]))
    old = db.create_batch("grok", "grok_video", {}, str(tmp_path), "flat", [{"mode": "t2v", "prompt": "cũ", "count": 1}])
    pg._set_editor_lines(["nháp cũ"])
    pg.model.reload()
    pg.add_script_tasks([{"prompt": "cảnh 1", "refs": [], "params": {"scene": 1}},
                         {"prompt": "cảnh 2", "refs": [], "params": {"scene": 2}}], "1:1", run=True)
    assert started == ["grok_video"] and pg._prompts() == ["nháp cũ"]
    new = [r for r in pg.model.rows if not r["draft"] and r["prompt"] in ("cảnh 1", "cảnh 2")]
    assert len(new) == 2 and pg.model.checked == {r["id"] for r in new}
    assert all(json.loads(r["params"])["ratio"] == "1:1 Vuông" for r in new)


def test_watermark_page(win, db, qapp, tmp_path):
    """Xóa Watermark: thư viện chia Video / Ảnh, thêm vào danh sách, khoanh vùng, xóa logo → lưu tệp mới."""
    from videoai.media import ffmpeg
    clip = str(tmp_path / "v.mp4")
    ffmpeg.run(["-f", "lavfi", "-i", "testsrc=s=320x180:d=1", "-pix_fmt", "yuv420p", clip])
    img = _img(tmp_path / "a.png")
    bid = db.create_batch("flow", "flow_video", {}, str(tmp_path), "flat", [{"mode": "t2v", "prompt": "x", "count": 1}])
    jid = db.query("SELECT id FROM jobs WHERE batch_id=?", (bid,))[0]["id"]
    db.add_output(jid, "video", clip)
    db.add_output(jid, "image", img)
    win.go("watermark")
    pg = win.pages["watermark"]
    pg.reload_library()
    assert pg.grid_v.count() == 1 and pg.grid_i.count() == 1 and pg.tabs.tabText(0) == "Video (1)"
    pg.grid_v.item(0).setSelected(True)
    pg.grid_i.item(0).setSelected(True)
    pg._add_selected()
    assert len(pg.rows) == 2 and pg.b_go.text().endswith("(2)")
    pg.add_paths([clip])                                   # trùng → bỏ qua
    assert len(pg.rows) == 2
    pg.pos.setCurrentIndex(2)                              # góc trái dưới
    assert pg.region.box[0] < 0.1
    pg.region._set(0.5, 0.5, 0.2, 0.2)
    assert pg._pos_key() == "custom"
    pg.out_dir = str(tmp_path / "out")
    pg.run()
    assert _wait(qapp, lambda: not pg.busy, 60)
    outs = sorted(p.name for p in (tmp_path / "out").iterdir())
    assert outs == ["a_xoalogo.png", "v_xoalogo.mp4"] and all(r.out for r in pg.rows)
    assert win.db.get_setting("watermark")["pos"] == "custom"


def test_image_pages_auto_workflow(win, qapp, tmp_path, monkeypatch):
    """Mọi trang tạo ảnh có nút "Quy trình tự động" (kiểu Mạch dữ liệu) ở tiêu đề Cấu hình → popup ảnh → Lưu:
    mỗi ảnh thành 1 tác vụ kèm đúng ảnh tham chiếu, nhãn 🎬 Quy trình tự động."""
    from videoai.ui import script_dialog as SD
    from videoai.ui.widgets import AIButton
    monkeypatch.setattr(type(win), "is_pro", lambda self: True)
    for key in ("flow_image", "gpt_image", "grok_image", "muse_image", "flow_video", "meta_muse"):
        win.go(key)
        pg = win.pages[key]
        assert isinstance(pg.b_script, AIButton) and isinstance(pg.b_ai, AIButton), key
    win.go("grok_image")
    pg = win.pages["grok_image"]
    d = SD.ScriptDialog(pg)
    assert d.image and d.windowTitle() == "Quy trình tự động – Ảnh" and not d.cons_box.isVisibleTo(d)
    assert d.ratio.currentText() == pg.ratio.currentText() and d.b_gen.text() == "Phân tích và tạo nội dung"
    assert list(d.style.btns) == SD.STYLE_SHORT and d.dur.maximum() == 30
    assert d.topics.buttons()[0].text() == "Quảng cáo sản phẩm" and not d.voices_on()
    d.sec["SP"].add_paths([_img(tmp_path / "sp.png")])
    d.dur.setValue(2)
    d.text.btns["Có tiêu đề"].click()
    b = d.brief()
    assert b.kind == "image" and b.n == 2 and b.text_on and b.platform == "grok"
    d.script = {"profiles": {}, "scenes": [{"time": "", "title": "Hero", "refs": ["SP1"], "frame": "", "prompt": "hero A"},
                                           {"time": "", "title": "B", "refs": [], "frame": "", "prompt": "plain B"}]}
    d._render_scenes()
    assert "Ảnh 1" in d.cards[0].findChildren(QLabel)[1].text()
    d.save()
    pg.add_script_tasks(d.result_tasks, None)
    assert pg._prompts()[-2:] == ["hero A", "plain B"]
    assert len(pg.model.draft_refs["hero A"]) == 1 and "plain B" not in pg.model.draft_refs
    assert pg.draft_params["hero A"]["script_id"] and "_mode" not in pg.draft_params["hero A"]
    from videoai.ui.task_table import script_tag
    rt = d.ratio.currentText().split(" ")[0]
    assert script_tag(pg.draft_params["hero A"]) == f"🎬 Quy trình tự động · {rt} · ảnh 1"
    d.deleteLater()


def test_page_defaults_v202(win, db, qapp):
    """Mặc định khi mở (v2.1.8 – tối thiểu): 1 kết quả, chất lượng thấp nhất (1K / 720p), thời lượng ngắn nhất."""
    from videoai.ui.pages.flow_page import default_ratio
    assert default_ratio(["16:9 Ngang", "9:16 Dọc", "1:1 Vuông"]) == "9:16 Dọc"
    assert default_ratio(["1:1 Vuông", "3:2 Ngang", "2:3 Dọc"]) == "2:3 Dọc"
    for key in ("flow_image", "gpt_image", "grok_image", "muse_image"):
        db.execute("DELETE FROM settings WHERE key=?", (f"page_{key}",))
    for key in ("flow_video", "grok_video", "meta_muse"):
        db.execute("DELETE FROM settings WHERE key=?", (f"page_{key}",))
    from videoai.core.platforms import PAGE_BY_KEY
    from videoai.ui.pages.flow_page import FlowPage
    for key in ("flow_image", "gpt_image", "grok_image", "muse_image"):
        pg = FlowPage(win.ctx, PAGE_BY_KEY[key])
        assert "Dọc" in pg.ratio.currentText() and int(pg.count.value()) == 1, key
        if key == "flow_image":
            assert pg.quality.value() == "1K"
        pg.deleteLater()
    for key in ("flow_video", "grok_video", "meta_muse"):
        pg = FlowPage(win.ctx, PAGE_BY_KEY[key])
        assert pg.ratio.value() == "9:16" and int(pg.count.value()) == 1, key
        if key == "flow_video":
            assert pg.quality.value() == "720p" and pg.dur.value() == 8 and pg.ext.value() == 3
        pg.deleteLater()


def test_pro_applies_without_restart(win, db, qapp, monkeypatch):
    """Lỗi: khách chuyển khoản xong, bản quyền đã kích hoạt ở nền nhưng giao diện vẫn FREE tới khi khởi động lại."""
    import time as _t
    from videoai.ui import script_dialog as SD
    from videoai.core.license import Status
    win.lic.status = Status(False, reason="none")
    win._lic_sig = win._lic_signature()
    win._lic_button()
    win.go("flow_image")
    di = SD.ScriptDialog(win.pages["flow_image"])
    di.show()
    assert di.free and di.dur.maximum() == 1 and di.free_note.isVisible()
    assert "FREE" in win.b_lic.text() and win.ctx.engine.max_total == 1
    # kích hoạt xong ở luồng nền (cửa sổ Bản quyền / Thanh toán có thể đã đóng)
    win.lic.status = Status(True, kind="key", plan="pro30", plan_name="Chuyên nghiệp 30 ngày", exp=int(_t.time()) + 30 * 86400)
    t = _t.time()
    while _t.time() - t < 3 and "FREE" in win.b_lic.text():
        qapp.processEvents()
        _t.sleep(0.05)
    assert "PRO" in win.b_lic.text() and win.ctx.engine.max_total == 0
    assert not di.free and di.dur.maximum() == 30 and not di.free_note.isVisible()
    di.dur.setValue(6)
    assert di.dur.value() == 6
    di.close()
    di.deleteLater()


def test_pay_dialog_closed_early_still_activates(qapp, monkeypatch):
    """Khách chuyển khoản rồi đóng hộp Thanh toán trước khi tools nhận tin: vẫn theo dõi đơn ở nền và tự kích hoạt."""
    import time as _t
    from videoai.ui import license_ui as LU
    calls = {"status": 0, "act": []}

    class FakeLic:
        machine = "m"

        def order(self, plan):
            return {"code": "VAI123", "amount": 100000, "bank": {}, "qr_payload": "x"}

        def order_status(self, code):
            calls["status"] += 1
            return {"status": "paid", "key": "VAI-AAAA-BBBB-CCCC-DDDD"} if calls["status"] >= 2 else {"status": "pending"}

        def activate(self, key):
            calls["act"].append(key)
            return None, {}
    d = LU.PayDialog(None, FakeLic(), {"code": "pro30", "name": "PRO", "price": 100000})
    t = _t.time()
    while _t.time() - t < 3 and not d.order:
        qapp.processEvents()
        _t.sleep(0.05)
    assert d.order and d.timer.isActive()
    d.reject()                                   # khách đóng hộp sớm
    t = _t.time()
    while _t.time() - t < 15 and not calls["act"]:
        qapp.processEvents()
        _t.sleep(0.05)
    assert calls["act"] == ["VAI-AAAA-BBBB-CCCC-DDDD"]


def test_ref_cells_show_every_image(qapp):
    """v2.1.8: ô Ảnh tham chiếu hiện đủ mọi ảnh (không còn chỉ 3 ảnh + "+N"), không chồng nhau, nằm gọn trong ô."""
    from PySide6.QtCore import QRect
    from videoai.ui.task_table import REFS_W, ROW_H, ref_cells
    rect = QRect(0, 0, REFS_W, ROW_H)
    for n in range(0, 11):
        for editable in (True, False):
            cells, plus = ref_cells(rect, n, editable)
            assert len(cells) == n
            boxes = cells + ([plus] if plus is not None else [])
            for i, a in enumerate(boxes):
                assert rect.contains(a.toAlignedRect().adjusted(1, 1, -1, -1))
                assert all(not a.intersects(b) for b in boxes[i + 1:])


def test_shopee_video_button_coming_soon(win, qapp):
    """v2.1.9: trang tạo video có nút "Tạo Video từ link Shopee" (sắp ra mắt) ngay trên khung Cấu hình."""
    win.go("flow_video")
    pg = win.pages["flow_video"]
    assert pg.b_shopee.text() == "Tạo Video từ link Shopee" and pg.b_shopee.chip_text == "SẮP RA MẮT"
    pg.b_shopee.click()                                  # chỉ báo sắp ra mắt
    win.go("flow_image")
    assert not hasattr(win.pages["flow_image"], "b_shopee")
