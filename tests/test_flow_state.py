"""v2.2.3: ô video đã xong nhưng chỉ hiện ảnh poster (chưa có <video>) phải được nhận là 'video' (đã xong),
không bị nhận nhầm là 'image' khiến tool gửi tạo lại nhiều lần."""
import pytest
from playwright.sync_api import sync_playwright

from videoai.adapters.flow import JS_STATE

TILES = """
<flow-tile-container><flow-pending-tile>image 5%</flow-pending-tile></flow-tile-container>
<flow-tile-container><flow-video-tile>
  <img class="image" src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" width="300">
  <span>chú chó chạy</span></flow-video-tile></flow-tile-container>
<flow-tile-container><flow-image-tile>
  <img class="image" src="data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==" width="300"></flow-image-tile></flow-tile-container>
<flow-tile-container><flow-video-tile><div>Không thể tạo video vì hoạt động bất thường</div></flow-video-tile></flow-tile-container>
"""


def test_poster_only_video_tile_is_done():
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        pg = b.new_page()
        pg.set_content("<div id='g'>" + TILES + "</div>")
        pg.wait_for_timeout(200)
        st = pg.evaluate(JS_STATE, [])
        states = [t["state"] for t in st["tiles"]]
        b.close()
    # pending (đang tạo), video (poster – ĐÃ XONG), image (ảnh thật), other (lỗi)
    assert states == ["pending", "video", "image", "other"], states
