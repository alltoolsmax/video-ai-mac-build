// Video AI · Mr. Huỳnh — Service worker (Manifest V3)
// Giữ kết nối với Tools (máy chủ cục bộ 127.0.0.1), cập nhật huy hiệu số tác vụ, và nhắc khi cần xác minh reCAPTCHA.
// KHÔNG tự tạo video, KHÔNG lách kiểm tra của Google — chỉ theo dõi và điều khiển Tools.

const DEFAULT_BASE = "http://127.0.0.1:47817";
const BADGE_BG = "#22d3ee";

async function getState() {
  const d = await chrome.storage.local.get({
    baseUrl: DEFAULT_BASE, token: "", connected: false, paused: false,
    lastStatus: null, lastError: "", recaptcha: false
  });
  return d;
}
const setState = (patch) => chrome.storage.local.set(patch);

async function api(path, { method = "GET", body = null } = {}) {
  const { baseUrl, token } = await getState();
  const url = baseUrl.replace(/\/+$/, "") + path + (path.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(token);
  const res = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined
  });
  if (!res.ok) throw new Error("HTTP " + res.status);
  return res.json();
}

async function updateBadge(status) {
  let text = "";
  let color = BADGE_BG;
  if (!status) { text = ""; }
  else if (status.paused) { text = "❚❚"; color = "#fbbf24"; }
  else {
    const n = (status.counts?.queued || 0) + (status.counts?.running || 0);
    text = n > 0 ? String(n > 999 ? "999+" : n) : "";
    if ((status.counts?.failed || 0) > 0 && n === 0) { text = "!"; color = "#fb7185"; }
  }
  await chrome.action.setBadgeText({ text });
  await chrome.action.setBadgeBackgroundColor({ color });
}

async function notifyRecaptcha() {
  chrome.notifications.create("recaptcha", {
    type: "basic",
    iconUrl: "icons/icon128.png",
    title: "Cần xác minh trên Google Flow",
    message: "Google đang yêu cầu xác minh (reCAPTCHA). Hãy mở cửa sổ Chrome của Tools và tự tick xác minh để chạy tiếp.",
    priority: 2
  });
}

// Kéo trạng thái từ Tools; cập nhật kết nối, huy hiệu, nhắc reCAPTCHA. Lỗi fetch = mất kết nối (tự thử lại lần sau).
async function poll() {
  const prev = await getState();
  try {
    const status = await api("/ext/status");
    const wasRecaptcha = prev.recaptcha;
    await setState({ connected: true, lastStatus: status, lastError: "", paused: !!status.paused, recaptcha: !!status.recaptcha });
    await updateBadge(status);
    if (status.recaptcha && !wasRecaptcha) await notifyRecaptcha();
    return status;
  } catch (e) {
    await setState({ connected: false, lastError: String(e.message || e) });
    await chrome.action.setBadgeText({ text: "" });
    return null;
  }
}

chrome.runtime.onInstalled.addListener(async () => {
  const s = await getState();
  if (!s.baseUrl) await setState({ baseUrl: DEFAULT_BASE });
  chrome.alarms.create("poll", { periodInMinutes: 0.5 }); // nhịp tim: Chrome tối thiểu ~30 giây
  poll();
});
chrome.runtime.onStartup.addListener(() => { chrome.alarms.create("poll", { periodInMinutes: 0.5 }); poll(); });
chrome.alarms.onAlarm.addListener((a) => { if (a.name === "poll") poll(); });

chrome.notifications.onClicked.addListener(() => {
  chrome.tabs.create({ url: "https://flow.google.com/" });
});

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "getState") { const st = await getState(); const live = await poll(); sendResponse({ ok: true, state: await getState(), status: live || st.lastStatus }); }
      else if (msg.type === "connect") { await setState({ baseUrl: msg.baseUrl || DEFAULT_BASE, token: msg.token || "" }); const st = await poll(); sendResponse({ ok: !!st, status: st, error: st ? "" : (await getState()).lastError }); }
      else if (msg.type === "disconnect") { await setState({ connected: false }); await chrome.action.setBadgeText({ text: "" }); sendResponse({ ok: true }); }
      else if (msg.type === "command") { const r = await api("/ext/command", { method: "POST", body: { action: msg.action } }); await poll(); sendResponse({ ok: true, result: r }); }
      else if (msg.type === "flowStatus") { // từ content.js trên flow.google.com
        if (msg.recaptcha) { const p = await getState(); if (!p.recaptcha) notifyRecaptcha(); await setState({ recaptcha: true }); }
        try { await api("/ext/flow", { method: "POST", body: { logged_in: !!msg.loggedIn, recaptcha: !!msg.recaptcha, url: msg.url || "" } }); } catch (_e) {}
        sendResponse({ ok: true });
      }
      else if (msg.type === "onboardingDone") { try { await api("/ext/onboarded", { method: "POST", body: { ok: true } }); } catch (_e) {} sendResponse({ ok: true }); }
      else sendResponse({ ok: false, error: "unknown message" });
    } catch (e) { sendResponse({ ok: false, error: String(e.message || e) }); }
  })();
  return true; // async
});
