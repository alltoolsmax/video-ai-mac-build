"""Kiểm thử giao diện (offscreen): menu, trang Flow mới, kho ảnh tham chiếu, công cụ video."""
from pathlib import Path

import pytest


@pytest.fixture()
def win(db, qapp):
    from videoai.core.engine import Engine
    from videoai.services.refs import RefLibrary
    from videoai.services.webhook import WebhookServer
    from videoai.ui.main_window import MainWindow
    from videoai.ui.theme import qss
    qapp.setStyleSheet(qss())
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
                      "Tạo Video Flow", "Tạo Video Dreamina", "Tạo Video Muse", "Tạo Video Meta Vibes", "Tạo Video Grok",
                      "Kho ảnh tham chiếu", "Workflow", "Nâng Cấp Ảnh", "Công Cụ Video", "Log Chi Tiết"]
    assert list(win.sections) == ["image", "video", "tools"]
    assert "webhook" not in win.menu                      # ẩn mặc định
    assert all(win.menu[k].soon for k in ("workflow", "upscale", "video_tools"))   # tạm khóa
    assert win.menu["grok_video"].soon and not win.menu["flow_image"].soon
    assert not any(win.menu[k].soon for k in ("gpt_image", "grok_image", "muse_image", "meta_muse"))   # đã mở
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
    assert page._params()["quality"] == "720p" and page._params()["resolutions"] == "720p"
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


def test_video_editor_ops(win, tmp_path, qapp, clip):
    from videoai.ui.pages.video_tools_page import VideoToolsPage      # đang tạm khóa trên menu, vẫn kiểm thử mã
    ed = VideoToolsPage(win.ctx)
    ed.import_media([clip, clip, _img(tmp_path / "x.png")], add_to_timeline=True)
    p = ed.project
    assert len(p.clips) == 3 and p.clips[2].kind == "image" and abs(p.video_duration - 9.0) < 0.2
    ed.timeline.playhead = 1.5
    ed.timeline.sel_id = None
    ed.split()
    assert len(ed.project.clips) == 4
    ed.undo()
    assert len(ed.project.clips) == 3
    ed.redo()
    assert len(ed.project.clips) == 4
    ed.add_text("Tiêu đề")
    assert ed.project.texts[-1].start == 1.5 and ed.project.texts[-1].pos == "Giữa"
    ed.timeline.sel_id = ed.project.clips[0].id
    ed.detach_audio()
    assert ed.project.audios and ed.project.clips[0].volume == 0
    ed.timeline.sel_id = ed.project.clips[1].id
    ed.delete()
    assert len(ed.project.clips) == 3
    from videoai.editor.render import export
    out = export(ed.project, str(tmp_path / "out.mp4"))
    from videoai.media import ffmpeg
    assert abs(ffmpeg.duration(out) - ed.project.video_duration) < 0.3
    from videoai.media import capcut
    d = capcut.export_project(ed.project, str(tmp_path / "cc"))
    assert (d / "draft_content.json").exists()


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
    page.start()                                               # 2 prompt → bị chặn
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
    b = win.menu["meta_vibes"]
    assert b.fontMetrics().horizontalAdvance(b.text()) < b.width() - 100   # tên dài vẫn hiện đủ cạnh nhãn "sắp có"


def test_update_dialog_mandatory_and_button(win, qapp, monkeypatch):
    """Có bản mới: nút ở menu đổi chữ; bản bắt buộc (min_version) không đóng được bằng Esc/Để sau."""
    from PySide6.QtCore import QTimer
    from videoai.core import updater
    from videoai.ui import updater_ui
    info = {"version": "99.0.0", "url": "https://x.example/s.exe", "notes": "- mới", "min_version": "99.0.0"}
    monkeypatch.setattr(updater, "manifest_url", lambda db=None: "https://x.example/v")
    monkeypatch.setattr(updater, "check", lambda db=None, timeout=15: info)
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
