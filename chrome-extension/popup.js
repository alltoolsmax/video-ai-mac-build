// Giao diện bảng điều khiển — hỏi service worker, hiển thị trạng thái, và gửi lệnh tạm dừng/tiếp tục.
const $ = (id) => document.getElementById(id);
const send = (msg) => new Promise((res) => chrome.runtime.sendMessage(msg, (r) => res(r || { ok: false, error: chrome.runtime.lastError?.message })));

function renderLogs(logs) {
  const ul = $("log");
  ul.innerHTML = "";
  if (!logs || !logs.length) { ul.innerHTML = '<li class="empty">Chưa có hoạt động.</li>'; return; }
  for (const it of logs.slice(-40).reverse()) {
    const li = document.createElement("li");
    const t = document.createElement("span"); t.className = "t"; t.textContent = it.t || "";
    const m = document.createElement("span"); m.className = it.level || ""; m.textContent = it.msg || "";
    li.append(t, m); ul.appendChild(li);
  }
}

function render(state, status) {
  $("ver").textContent = status?.version ? "v" + status.version : "";
  const connected = !!state.connected;
  $("dot").className = "dot " + (connected ? "on" : "off");
  $("connState").textContent = connected ? "Đã kết nối Tools" : (state.lastError ? "Chưa kết nối — " + state.lastError : "Chưa kết nối Tools");
  $("connUrl").textContent = state.baseUrl || "";
  $("btnConnect").textContent = connected ? "Ngắt" : "Kết nối";
  $("baseUrl").value = state.baseUrl || "";
  $("token").value = state.token || "";

  const st = status || state.lastStatus || {};
  const paused = !!st.paused;
  $("btnPause").classList.toggle("hidden", paused);
  $("btnResume").classList.toggle("hidden", !paused);

  const flow = st.flow_logged_in;
  $("flowState").textContent = "Đăng nhập Google Flow: " + (flow == null ? "—" : (flow + " tài khoản"));

  const c = st.counts || {};
  $("cQueued").textContent = c.queued || 0;
  $("cRunning").textContent = c.running || 0;
  $("cDone").textContent = c.done || 0;
  $("cFailed").textContent = c.failed || 0;

  $("recaptcha").classList.toggle("hidden", !st.recaptcha);
  renderLogs(st.logs);
}

async function refresh() {
  const r = await send({ type: "getState" });
  if (r && r.state) render(r.state, r.status);
}

$("btnConnect").onclick = async () => {
  const r = await send({ type: "getState" });
  if (r.state.connected) { await send({ type: "disconnect" }); }
  else { await send({ type: "connect", baseUrl: $("baseUrl").value.trim() || undefined, token: $("token").value.trim() }); }
  refresh();
};
$("btnSave").onclick = async () => {
  await send({ type: "connect", baseUrl: $("baseUrl").value.trim() || undefined, token: $("token").value.trim() });
  refresh();
};
$("btnReconnect").onclick = () => send({ type: "command", action: "reconnect" }).then(refresh);
$("btnPause").onclick = () => send({ type: "command", action: "pause" }).then(refresh);
$("btnResume").onclick = () => send({ type: "command", action: "resume" }).then(refresh);

refresh();
setInterval(refresh, 1500);
