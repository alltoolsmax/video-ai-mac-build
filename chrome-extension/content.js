// Chạy trên flow.google.com — nhận biết đã đăng nhập chưa và có đang hỏi xác minh (reCAPTCHA) không,
// rồi báo về service worker. KHÔNG tự bấm, KHÔNG điền gì, KHÔNG vượt xác minh — chỉ quan sát.
(function () {
  const RECAPTCHA = [
    "iframe[src*='recaptcha']", "iframe[src*='hcaptcha']", "iframe[src*='challenges.cloudflare']"
  ];
  const SIGNED_IN = ["button.mat-mdc-fab", "flow-tile-container", "a[href*='/project/']", "div.ProseMirror[contenteditable='true']"];

  function visible(el) {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  function has(selList) { return selList.some((s) => [...document.querySelectorAll(s)].some(visible)); }

  function snapshot() {
    const url = location.href;
    const onAccounts = /accounts\.google\.com/.test(url);
    const recaptcha = has(RECAPTCHA) || /verify (you are|that you'?re)|xác minh bạn/i.test(document.body?.innerText || "");
    const loggedIn = !onAccounts && has(SIGNED_IN);
    return { type: "flowStatus", loggedIn, recaptcha, url };
  }

  let last = "";
  function report() {
    const snap = snapshot();
    const key = JSON.stringify([snap.loggedIn, snap.recaptcha]);
    if (key === last) return;
    last = key;
    try { chrome.runtime.sendMessage(snap, () => void chrome.runtime.lastError); } catch (_e) {}
  }

  report();
  const obs = new MutationObserver(() => report());
  try { obs.observe(document.documentElement, { childList: true, subtree: true }); } catch (_e) {}
  setInterval(report, 4000);

  // Trang onboarding nhúng (nếu Tools mở) có thể hỏi trạng thái qua window.postMessage
  window.addEventListener("message", (e) => {
    if (e.data && e.data.__vai === "getFlow") {
      const snap = snapshot();
      window.postMessage({ __vai: "flow", loggedIn: snap.loggedIn, recaptcha: snap.recaptcha }, "*");
    }
  });
})();
