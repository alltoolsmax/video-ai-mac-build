"""Kiểm thử giao diện (offscreen): mở mọi trang, luồng thêm prompt → hàng đợi, workflow lưu/mở."""
import pytest


@pytest.fixture()
def win(db, qapp):
    from videoai.core.engine import Engine
    from videoai.services.characters import Characters
    from videoai.services.webhook import WebhookServer
    from videoai.ui.main_window import MainWindow
    from videoai.ui.theme import qss
    qapp.setStyleSheet(qss())
    eng = Engine(db)
    w = MainWindow(db, eng, Characters(db), WebhookServer(db, eng))
    w.show()
    yield w
    eng.loop.call_soon_threadsafe(eng.loop.stop)
    w.deleteLater()


def test_all_pages_open(win, qapp):
    for key in list(win.menu):
        win.go(key)
        qapp.processEvents()
        assert win.stack.currentWidget() is win.pages[key]
        assert win.menu[key].isChecked()
    assert len(win.menu) == 16


def test_menu_order(win):
    labels = [b.text() for b in win.group.buttons()]
    assert labels == ["Flow Ảnh", "Flow Video", "Google Vids", "Google Pics", "Dreamina", "GPT Image", "Meta Muse",
                      "Meta Vibes", "Grok Imagine", "Nhân Vật", "Workflow", "Webhook API", "Nâng Cấp Ảnh",
                      "Công Cụ Video", "Cài Đặt", "Log Chi Tiết"]


def test_enqueue_flow(win, db, qapp, monkeypatch):
    started = []
    monkeypatch.setattr(win.ctx.engine, "start_page", lambda *a: started.append(a))
    aid = db.add_account("flow", "me@x.com", "/tmp/pp")
    db.update_account(aid, status="ok")
    win.go("flow_image")
    page = win.pages["flow_image"]
    page.reload_accounts()
    page.editor.setPlainText("Phở bò\n\nHội An @Minh\n")
    win.ctx.characters.save("Minh", "chàng trai", [])
    page.prefix.setText("cinematic")
    page.count.setValue(2)
    assert page.pcount.text() == "2 prompt"
    page.start()
    jobs = db.query("SELECT prompt, count, mode FROM jobs ORDER BY row_no")
    assert [j["prompt"] for j in jobs] == ["cinematic Phở bò", "cinematic Hội An Minh (chàng trai)"]
    assert all(j["count"] == 2 for j in jobs)
    assert started and started[0][0] == "flow_image" and started[0][1] == [aid]
    qapp.processEvents()
    assert page.model.rowCount() == 2
    # dùng một prompt cho tất cả
    page.one_for_all.setChecked(True)
    page.repeat.setValue(4)
    assert page.pcount.text() == "4 prompt"


def test_i2v_requires_ref(win, db, monkeypatch):
    monkeypatch.setattr(win.ctx.engine, "start_page", lambda *a: None)
    db.add_account("flow", "v@x.com", "/tmp/pv")
    win.go("flow_video")
    page = win.pages["flow_video"]
    page.reload_accounts()
    page._set_mode("i2v")
    page.editor.setPlainText("cảnh 1")
    page.start()
    assert db.query("SELECT COUNT(*) n FROM jobs")[0]["n"] == 0


def test_workflow_roundtrip(win):
    win.go("workflow")
    wp = win.pages["workflow"]
    g = wp.scene.to_json()
    assert len(g["nodes"]) == 8 and len(g["edges"]) == 8
    wp.scene.from_json(g)
    key = lambda e: (e["from"], e["out"], e["to"], e["in"])
    assert sorted(wp.scene.to_json()["edges"], key=key) == sorted(g["edges"], key=key)
    # nối sai kiểu bị từ chối
    nodes = {n.id: n for n in wp.scene.nodes()}
    assert wp.scene.connect(nodes[1].outputs[0], nodes[5].inputs[0]) is None
