# Trang hướng dẫn cài Tiện ích Chrome + đăng nhập Google Flow (bridge phục vụ tại /ext/onboard).
# __TOKEN__, __BASE__, __VER__ được ExtBridge thay trước khi gửi.
ONBOARD_HTML = r"""<!doctype html><html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Trợ lý Chrome · Video AI - Mr. Huỳnh</title>
<style>
:root{--bg:#070b24;--surface:#0d1442;--surface2:#101a52;--input:#0b1030;--border:#22357a;--bin:#4a5fb0;
--text:#eaf0ff;--muted:#9aa6d6;--faint:#7f8bc4;--cyan:#22d3ee;--indigo:#6366f1;--gold:#fbbf24;--green:#4ade80}
*{box-sizing:border-box;font-family:"Be Vietnam Pro","Segoe UI",system-ui,sans-serif}
body{margin:0;background:radial-gradient(1200px 600px at 50% -10%,#0d1850,#070b24);color:var(--text);min-height:100vh}
.wrap{max-width:720px;margin:0 auto;padding:34px 20px 60px}
.hd{display:flex;align-items:center;gap:14px;margin-bottom:8px}
.hd h1{font-size:22px;margin:0}.hd .sub{color:var(--muted);font-size:13px}
.badge{margin-left:auto;font-size:11px;color:var(--faint);border:1px solid var(--border);border-radius:20px;padding:4px 10px}
.step{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:18px 20px;margin-top:16px;
box-shadow:0 10px 30px -18px #000}
.step h2{font-size:15px;margin:0 0 8px;display:flex;align-items:center;gap:10px}
.n{display:inline-flex;width:26px;height:26px;border-radius:50%;background:linear-gradient(135deg,var(--cyan),var(--indigo));
color:#021;align-items:center;justify-content:center;font-weight:800;font-size:13px}
.step p,.step li{color:var(--muted);font-size:13px;line-height:1.6}
.tokrow{display:flex;gap:8px;margin-top:10px}
.tok{flex:1;background:var(--input);border:1px solid var(--bin);border-radius:8px;padding:10px 12px;color:var(--cyan);
font-family:ui-monospace,Consolas,monospace;font-size:13px;user-select:all;overflow:auto;white-space:nowrap}
button{border:0;cursor:pointer;border-radius:9px;font-weight:700;font-size:13px;padding:11px 16px;color:#021}
.cy{background:linear-gradient(90deg,var(--cyan),#38bdf8)}.gd{background:linear-gradient(90deg,var(--gold),#f59e0b)}
.gn{background:linear-gradient(90deg,var(--green),#22c55e)}
.ghost{background:transparent;color:var(--muted);border:1px solid var(--bin)}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px;align-items:center}
.done{display:none;margin-top:16px;background:var(--surface2);border:1px solid var(--green);border-radius:12px;padding:16px 18px}
.done.show{display:block}.done h2{color:#bbf7d0}
kbd{background:#0b1030;border:1px solid var(--bin);border-radius:5px;padding:1px 6px;font-size:12px}
.hint{color:var(--faint);font-size:12px;margin-top:6px}
</style></head><body><div class="wrap">
<div class="hd"><img src="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='44' height='44'><rect width='44' height='44' rx='11' fill='%2322d3ee'/><text x='22' y='30' font-size='22' text-anchor='middle' fill='%23021'>▶</text></svg>" width="44" height="44" alt="">
<div><h1>Trợ lý Chrome</h1><div class="sub">Video AI · Mr. Huỳnh</div></div><div class="badge">v__VER__</div></div>

<div class="step"><h2><span class="n">1</span> Cài tiện ích vào Chrome</h2>
<ol><li>Giải nén tệp <b>video-ai-tro-ly-chrome.zip</b> ra một thư mục cố định (không xoá sau khi cài).</li>
<li>Mở trang <b>chrome://extensions</b> (gõ vào thanh địa chỉ).</li>
<li>Bật <b>Chế độ dành cho nhà phát triển</b> (Developer mode) ở góc trên bên phải.</li>
<li>Bấm <b>Tải tiện ích đã giải nén</b> (Load unpacked) rồi chọn thư mục vừa giải nén.</li></ol>
<div class="row"><button class="cy" onclick="openExt()">Mở trang chrome://extensions</button></div>
<div class="hint">Nếu nút không mở được, hãy tự gõ <kbd>chrome://extensions</kbd> vào thanh địa chỉ.</div></div>

<div class="step"><h2><span class="n">2</span> Kết nối với Tools</h2>
<p>Tiện ích tự tìm Tools ở <b>__BASE__</b>. Nếu cần nhập mã kết nối, hãy sao chép mã bên dưới và dán vào mục
<b>Cài đặt kết nối</b> trong tiện ích:</p>
<div class="tokrow"><div class="tok" id="tok">__TOKEN__</div><button class="ghost" onclick="copyTok()">Sao chép</button></div></div>

<div class="step"><h2><span class="n">3</span> Đăng nhập Google Flow</h2>
<p>Mở Google Flow và đăng nhập tài khoản Google bạn muốn dùng. Đăng nhập ngay trong cửa sổ Chrome này được xem như
đã đăng nhập trên trình duyệt.</p>
<div class="row"><button class="gd" onclick="openFlow()">Mở Google Flow để đăng nhập</button></div></div>

<div class="step"><h2><span class="n">4</span> Hoàn tất</h2>
<p>Đăng nhập xong, bấm nút bên dưới. Tools sẽ tự kiểm tra tài khoản và kết nối với tiện ích.</p>
<div class="row"><button class="gn" id="fin" onclick="finish()">Đã đăng nhập xong</button></div>
<div class="done" id="done"><h2>✓ Đã gửi cho Tools</h2>
<p>Bạn có thể đóng cửa sổ này và quay lại Tools. Tools đang kiểm tra đăng nhập và kết nối tiện ích.</p></div></div>
</div>
<script>
var TOKEN="__TOKEN__", BASE="__BASE__";
function openExt(){ try{ window.open("chrome://extensions","_blank"); }catch(e){} }
function openFlow(){ window.open("https://flow.google.com/","_blank"); }
function copyTok(){ navigator.clipboard.writeText(TOKEN).then(()=>{}); }
function finish(){
  fetch(BASE+"/ext/onboarded?token="+encodeURIComponent(TOKEN),{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"})
    .finally(()=>{ document.getElementById("done").classList.add("show"); document.getElementById("fin").disabled=true;
      setTimeout(()=>{ try{ window.close(); }catch(e){} }, 1500); });
}
</script></body></html>"""
