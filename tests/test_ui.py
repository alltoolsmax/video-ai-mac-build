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
    assert labels == ["Tạo ảnh Flow", "Tạo Video Flow", "Tạo ảnh Pics", "Tạo Video Vids", "Tạo Video Dreamina",
                      "Tạo ảnh GPT", "Tạo Video Muse", "Tạo Video Meta Vibes", "Tạo ảnh Grok", "Tạo Video Grok",
                      "Kho ảnh tham chiếu", "Workflow", "Nâng Cấp Ảnh", "Công Cụ Video", "Cài Đặt", "Log Chi Tiết"]
    assert "webhook" not in win.menu                      # ẩn mặc định
    assert win.menu["grok_video"].soon and not win.menu["flow_image"].soon
    for key in list(win.menu):
        win.go(key)
        qapp.processEvents()
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
    page.start()
    jobs = db.query("SELECT prompt, count, mode, refs FROM jobs ORDER BY row_no")
    assert [j["mode"] for j in jobs] == ["t2i", "i2i"]          # @Tên → tự dùng tham chiếu
    assert jobs[1]["prompt"] == "Minh (chàng trai) trên phố cổ" and all(j["count"] == 3 for j in jobs)
    assert started[0][1] == ids[:2] and started[0][2] == 1      # 2 tài khoản sẵn sàng, mỗi tài khoản 1 tác vụ
    # chế độ Tham chiếu: ảnh chọn từ kho dùng cho mọi prompt
    page.mode_seg.set_value("Tham chiếu")
    page._mode_changed("Tham chiếu")
    page.refs_strip.set_ids([r2])
    rows = page.build_rows()
    assert all(lib.get(r2)["path"] in r["refs"] for r in rows) and rows[1]["refs"][1] == lib.get(r1)["path"]
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
    page.mode_seg.set_value("Khung hình đầu/cuối")
    page._mode_changed("Khung hình đầu/cuối")
    page.editor.setPlainText("cảnh 1")
    assert page.build_rows() is None                   # chưa chọn ảnh đầu
    page.first.set_ids([s])
    page.model_cb.setCurrentText("Omni 1.2 Flash")
    page.dur.setValue(10)
    rows = page.build_rows()
    assert rows[0]["mode"] == "i2v" and rows[0]["refs"] == [lib.get(s)["path"]]
    assert page._params()["durations"] == "10 giây"
    page.model_cb.setCurrentText("Veo 3.1 - Fast")
    assert "durations" not in page._params() and page.dur_box.isHidden()


def test_refs_page(win, tmp_path, qapp):
    win.go("refs")
    page = win.pages["refs"]
    page._drop([_img(tmp_path / "a.png"), _img(tmp_path / "b.png", "green")])
    qapp.processEvents()
    assert page.grid.count() == 2
    page.grid.set_all(True)
    assert len(page.grid.checked_ids()) == 2


def test_video_editor_ops(win, tmp_path, qapp, clip):
    win.go("video_tools")
    ed = win.pages["video_tools"]
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
