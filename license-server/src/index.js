// Máy chủ bản quyền Mr. Huỳnh — Cloudflare Worker + D1.
// Phần mềm gửi mã máy + key, máy chủ trả về "giấy phép" có chữ ký Ed25519.
// Phần mềm kiểm tra chữ ký bằng khóa công khai gắn sẵn nên khách không tự sửa được ngày hết hạn.
import ADMIN_HTML from "./admin.html";

const DAY = 86400;
const now = () => Math.floor(Date.now() / 1000);
const ALPH = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

function rand(n) {
  const b = new Uint8Array(n);
  crypto.getRandomValues(b);
  return [...b].map((x) => ALPH[x % ALPH.length]).join("");
}
const newKey = (prefix) => `${prefix}-${rand(4)}-${rand(4)}-${rand(4)}-${rand(4)}`;
const mask = (k) => (k ? k.slice(0, 4) + "••••-••••-" + k.slice(-4) : "");

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" },
  });
const fail = (code, message, status = 400, extra = {}) => json({ ok: false, code, message, ...extra }, status);

function b64url(bytes) {
  let s = "";
  for (const x of bytes) s += String.fromCharCode(x);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

let _key = null;
async function signer(env) {
  if (!_key) {
    const jwk = JSON.parse(env.SIGNING_KEY);
    _key = await crypto.subtle.importKey("jwk", jwk, { name: "Ed25519" }, false, ["sign"]);
  }
  return _key;
}

// Giấy phép = base64url(JSON) + "." + base64url(chữ ký)
async function issue(env, product, machine, info) {
  const t = now();
  const payload = {
    v: 1, p: product, m: machine, iat: t,
    kind: info.kind,                 // trial | key
    key: info.key ? mask(info.key) : "",
    plan: info.plan, plan_name: info.plan_name,
    exp: info.exp,                   // 0 = vĩnh viễn
    chk: t + Number(env.RECHECK_HOURS || 24) * 3600, // nên kiểm tra lại sau thời điểm này
    grace: Number(env.OFFLINE_GRACE_DAYS || 3) * DAY,  // được dùng không mạng tối đa
  };
  const body = b64url(new TextEncoder().encode(JSON.stringify(payload)));
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, await signer(env), new TextEncoder().encode(body)));
  return { token: `${body}.${b64url(sig)}`, license: payload };
}

const validMachine = (m) => typeof m === "string" && /^[a-f0-9]{32,64}$/.test(m);
const validProduct = (p) => typeof p === "string" && /^[a-z0-9_-]{2,32}$/.test(p);

async function log(env, kind, key, machine, detail) {
  try {
    await env.DB.prepare("INSERT INTO events (at, kind, key, machine, detail) VALUES (?,?,?,?,?)")
      .bind(now(), kind, key || null, machine || null, detail ? String(detail).slice(0, 500) : null).run();
  } catch (_) { /* nhật ký không được làm hỏng yêu cầu */ }
}

async function planOf(env, product, code) {
  return env.DB.prepare("SELECT * FROM plans WHERE product=? AND code=?").bind(product, code).first();
}

async function keyToken(env, k) {
  const plan = await planOf(env, k.product, k.plan);
  return issue(env, k.product, k.machine, {
    kind: "key", key: k.key, plan: k.plan, plan_name: plan ? plan.name : k.plan, exp: k.expires_at,
  });
}

const alive = (k) => k && k.status === "active" && (k.expires_at === 0 || k.expires_at > now());

async function activeKeyOnMachine(env, product, machine, exceptKey) {
  const rows = await env.DB.prepare(
    "SELECT * FROM keys WHERE product=? AND machine=? AND status='active' ORDER BY expires_at=0 DESC, expires_at DESC")
    .bind(product, machine).all();
  return (rows.results || []).find((k) => k.key !== exceptKey && alive(k)) || null;
}

// ------------------------------------------------------------------ API cho phần mềm
async function apiPlans(env, product) {
  const rows = await env.DB.prepare("SELECT code, name, days, price, badge FROM plans WHERE product=? AND active=1 ORDER BY sort")
    .bind(product).all();
  return json({
    ok: true, plans: rows.results || [],
    trial_days: Number(env.TRIAL_DAYS || 10),
    payment: Boolean(env.BANK_ID && env.BANK_ACCOUNT && env.SEPAY_API_KEY),
    contact: { zalo: env.CONTACT_ZALO || "", phone: env.CONTACT_PHONE || "", name: env.CONTACT_NAME || "" },
  });
}

async function apiTrial(env, b) {
  const { product, machine } = b;
  const k = await activeKeyOnMachine(env, product, machine);
  if (k) return json({ ok: true, ...(await keyToken(env, k)) });
  let t = await env.DB.prepare("SELECT * FROM trials WHERE product=? AND machine=?").bind(product, machine).first();
  if (!t) {
    const days = Number(env.TRIAL_DAYS || 10);
    t = { started_at: now(), expires_at: now() + days * DAY };
    await env.DB.prepare("INSERT INTO trials (product, machine, started_at, expires_at) VALUES (?,?,?,?)")
      .bind(product, machine, t.started_at, t.expires_at).run();
    await log(env, "trial_start", null, machine, product);
  }
  if (t.expires_at <= now()) return fail("trial_expired", "Đã hết thời gian dùng thử. Vui lòng mua key để tiếp tục.", 403);
  return json({ ok: true, ...(await issue(env, product, machine, { kind: "trial", plan: "trial", plan_name: "Dùng thử", exp: t.expires_at })) });
}

async function apiActivate(env, b) {
  const { product, machine } = b;
  const code = String(b.key || "").trim().toUpperCase();
  const k = await env.DB.prepare("SELECT * FROM keys WHERE key=?").bind(code).first();
  if (!k || k.product !== product) {
    await log(env, "bad_key", code.slice(0, 40), machine);
    return fail("bad_key", "Key không đúng. Kiểm tra lại từng ký tự.", 404);
  }
  if (k.status === "revoked") return fail("revoked", "Key đã bị khóa. Liên hệ người bán.", 403);
  if (k.status === "merged") {
    if (k.merged_into) {   // key gia hạn đã cộng vào key chính: trả giấy phép của key chính nếu cùng máy
      const main = await env.DB.prepare("SELECT * FROM keys WHERE key=?").bind(k.merged_into).first();
      if (main && main.machine === machine && alive(main)) return json({ ok: true, ...(await keyToken(env, main)), full_key: main.key });
    }
    return fail("used", "Key này đã được dùng để gia hạn.", 409);
  }

  if (k.status === "new") {
    const cur = await activeKeyOnMachine(env, product, machine, k.key);
    if (cur) {   // GIA HẠN CỘNG DỒN: thêm thời gian vào key đang dùng trên máy này
      if (cur.expires_at === 0) return fail("already_lifetime", "Máy này đã có bản quyền vĩnh viễn, không cần gia hạn.", 409);
      const exp = k.days === 0 ? 0 : Math.max(cur.expires_at, now()) + k.days * DAY;
      const plan = k.days === 0 ? k.plan : cur.plan;
      await env.DB.batch([
        env.DB.prepare("UPDATE keys SET expires_at=?, plan=? WHERE id=?").bind(exp, plan, cur.id),
        env.DB.prepare("UPDATE keys SET status='merged', merged_into=?, machine=?, activated_at=? WHERE id=?")
          .bind(cur.key, machine, now(), k.id),
      ]);
      await log(env, "renew", k.key, machine, `+${k.days} ngày vào ${cur.key}`);
      const main = await env.DB.prepare("SELECT * FROM keys WHERE id=?").bind(cur.id).first();
      return json({ ok: true, renewed: true, added_days: k.days, ...(await keyToken(env, main)), full_key: main.key });
    }
    const exp = k.days === 0 ? 0 : now() + k.days * DAY;
    await env.DB.prepare("UPDATE keys SET status='active', machine=?, activated_at=?, expires_at=? WHERE id=?")
      .bind(machine, now(), exp, k.id).run();
    await log(env, "activate", k.key, machine);
    const k2 = await env.DB.prepare("SELECT * FROM keys WHERE id=?").bind(k.id).first();
    return json({ ok: true, ...(await keyToken(env, k2)), full_key: k2.key });
  }

  // key đã kích hoạt
  if (k.expires_at !== 0 && k.expires_at <= now()) return fail("expired", "Key đã hết hạn. Nhập key mới để gia hạn.", 403);
  if (k.machine !== machine) {   // khách chuyển sang máy mới
    const cd = Number(env.TRANSFER_COOLDOWN_DAYS || 30) * DAY;
    if (k.last_transfer_at && now() - k.last_transfer_at < cd) {
      const left = Math.ceil((k.last_transfer_at + cd - now()) / DAY);
      return fail("transfer_cooldown", `Key đang dùng trên máy khác. Bạn chỉ được tự chuyển máy 1 lần mỗi ${env.TRANSFER_COOLDOWN_DAYS || 30} ngày (còn ${left} ngày). Liên hệ người bán để được hỗ trợ.`, 409);
    }
    await env.DB.prepare("UPDATE keys SET machine=?, transfers=transfers+1, last_transfer_at=? WHERE id=?")
      .bind(machine, now(), k.id).run();
    await log(env, "transfer", k.key, machine, `từ ${k.machine}`);
  }
  const k2 = await env.DB.prepare("SELECT * FROM keys WHERE id=?").bind(k.id).first();
  return json({ ok: true, ...(await keyToken(env, k2)), full_key: k2.key });
}

async function apiCheck(env, b) {
  const { product, machine } = b;
  if (!b.key) return fail("no_key", "Chưa có key (đang dùng gói Miễn phí).", 400);
  let k = await env.DB.prepare("SELECT * FROM keys WHERE key=?").bind(String(b.key).toUpperCase()).first();
  if (k && k.status === "merged" && k.merged_into) k = await env.DB.prepare("SELECT * FROM keys WHERE key=?").bind(k.merged_into).first();
  if (!k || k.product !== product) return fail("bad_key", "Key không tồn tại.", 404);
  if (k.status === "revoked") return fail("revoked", "Key đã bị khóa. Liên hệ người bán.", 403);
  if (k.machine !== machine) return fail("moved", "Key đã được chuyển sang máy khác.", 403);
  if (k.expires_at !== 0 && k.expires_at <= now()) return fail("expired", "Key đã hết hạn. Nhập key mới để gia hạn.", 403);
  await env.DB.prepare("UPDATE keys SET last_check_at=? WHERE id=?").bind(now(), k.id).run();
  return json({ ok: true, ...(await keyToken(env, k)), full_key: k.key });
}

// ------------------------------------------------------------------ mua key tự động (VietQR + SePay)
async function apiOrder(env, b) {
  if (!(env.BANK_ID && env.BANK_ACCOUNT && env.SEPAY_API_KEY)) return fail("no_payment", "Chưa bật thanh toán tự động.", 400);
  const plan = await planOf(env, b.product, b.plan);
  if (!plan || !plan.active) return fail("bad_plan", "Gói không tồn tại.", 404);
  const code = "VAI" + rand(6);
  await env.DB.prepare("INSERT INTO orders (code, product, plan, amount, machine, created_at) VALUES (?,?,?,?,?,?)")
    .bind(code, b.product, plan.code, plan.price, b.machine, now()).run();
  const qr = `https://img.vietqr.io/image/${encodeURIComponent(env.BANK_ID)}-${encodeURIComponent(env.BANK_ACCOUNT)}-compact2.png` +
    `?amount=${plan.price}&addInfo=${code}&accountName=${encodeURIComponent(env.BANK_NAME || "")}`;
  return json({ ok: true, code, amount: plan.price, plan: plan.name, qr_url: qr,
    bank: { id: env.BANK_ID, account: env.BANK_ACCOUNT, name: env.BANK_NAME || "" }, expires_in: 1800 });
}

async function apiOrderStatus(env, code, machine) {
  const o = await env.DB.prepare("SELECT * FROM orders WHERE code=?").bind(String(code || "")).first();
  if (!o || (o.machine && machine && o.machine !== machine)) return fail("not_found", "Không thấy đơn hàng.", 404);
  if (o.status === "pending" && now() - o.created_at > 86400) return json({ ok: true, status: "expired" });
  return json({ ok: true, status: o.status, key: o.status === "paid" ? o.key : null });
}

async function sepayWebhook(env, request) {
  const auth = request.headers.get("authorization") || "";
  if (!env.SEPAY_API_KEY || auth.trim() !== `Apikey ${env.SEPAY_API_KEY}`) return fail("unauthorized", "Sai khóa SePay", 401);
  const b = await request.json().catch(() => ({}));
  if (b.transferType && b.transferType !== "in") return json({ success: true, ignored: "out" });
  const m = String(b.content || b.description || "").toUpperCase().match(/VAI[A-Z0-9]{6}/);
  if (!m) return json({ success: true, ignored: "no_code" });
  const o = await env.DB.prepare("SELECT * FROM orders WHERE code=?").bind(m[0]).first();
  if (!o) return json({ success: true, ignored: "unknown_order" });
  if (o.status === "paid") return json({ success: true, duplicate: true });
  if (Number(b.transferAmount || 0) < o.amount) {
    await log(env, "underpaid", null, o.machine, `${m[0]}: ${b.transferAmount}/${o.amount}`);
    return json({ success: true, ignored: "underpaid" });
  }
  const plan = await planOf(env, o.product, o.plan);
  const key = newKey(env.KEY_PREFIX || "VAI");
  const ref = String(b.id || b.referenceCode || m[0]);
  try {
    await env.DB.batch([
      env.DB.prepare("INSERT INTO keys (key, product, plan, days, price, order_code, customer, note, created_at) VALUES (?,?,?,?,?,?,?,?,?)")
        .bind(key, o.product, o.plan, plan ? plan.days : 30, o.amount, o.code, b.accountNumber ? `TK ${b.accountNumber}` : null, "Tự động qua SePay", now()),
      env.DB.prepare("UPDATE orders SET status='paid', key=?, paid_at=?, bank_ref=? WHERE code=? AND status='pending'")
        .bind(key, now(), ref, o.code),
    ]);
  } catch (e) {   // bank_ref trùng: SePay gửi lại cùng giao dịch
    return json({ success: true, duplicate: true });
  }
  await log(env, "paid", key, o.machine, `${o.code} ${o.amount}đ`);
  return json({ success: true });
}

// ------------------------------------------------------------------ quản trị
function adminOK(env, request) {
  const t = request.headers.get("x-admin-token") || "";
  return env.ADMIN_TOKEN && env.ADMIN_TOKEN.length >= 12 && t === env.ADMIN_TOKEN;
}

async function admin(env, path, request) {
  const b = request.method === "POST" ? await request.json().catch(() => ({})) : {};
  const url = new URL(request.url);
  const product = (b.product || url.searchParams.get("product") || env.DEFAULT_PRODUCT || "videoai").toLowerCase();
  const DB = env.DB;
  switch (path) {
    case "stats": {
      const t = now(), d30 = t - 30 * DAY, d0 = t - (t % DAY) - 7 * 3600; // đầu ngày giờ VN (gần đúng)
      const one = async (sql, ...a) => (await DB.prepare(sql).bind(...a).first()) || {};
      return json({ ok: true,
        active: (await one("SELECT COUNT(*) n FROM keys WHERE product=? AND status='active' AND (expires_at=0 OR expires_at>?)", product, t)).n,
        unused: (await one("SELECT COUNT(*) n FROM keys WHERE product=? AND status='new'", product)).n,
        trials: (await one("SELECT COUNT(*) n FROM trials WHERE product=? AND expires_at>?", product, t)).n,
        trials_total: (await one("SELECT COUNT(*) n FROM trials WHERE product=?", product)).n,
        revenue_30d: (await one("SELECT COALESCE(SUM(price),0) s FROM keys WHERE product=? AND created_at>? AND status!='revoked'", product, d30)).s,
        revenue_today: (await one("SELECT COALESCE(SUM(price),0) s FROM keys WHERE product=? AND created_at>? AND status!='revoked'", product, d0)).s,
        revenue_all: (await one("SELECT COALESCE(SUM(price),0) s FROM keys WHERE product=? AND status!='revoked'", product)).s,
        payment: Boolean(env.BANK_ID && env.BANK_ACCOUNT && env.SEPAY_API_KEY),
      });
    }
    case "keys": {
      const q = `%${(url.searchParams.get("q") || "").trim()}%`;
      const rows = await DB.prepare(
        "SELECT * FROM keys WHERE product=? AND (key LIKE ? OR IFNULL(customer,'') LIKE ? OR IFNULL(note,'') LIKE ? OR IFNULL(machine,'') LIKE ?) ORDER BY id DESC LIMIT 300")
        .bind(product, q, q, q, q).all();
      return json({ ok: true, keys: rows.results || [], now: now() });
    }
    case "create": {
      const plan = await planOf(env, product, b.plan);
      if (!plan) return fail("bad_plan", "Gói không tồn tại");
      const n = Math.min(Math.max(parseInt(b.count || 1, 10), 1), 200);
      const days = b.days !== undefined && b.days !== "" ? parseInt(b.days, 10) : plan.days;
      const price = b.price !== undefined && b.price !== "" ? parseInt(b.price, 10) : plan.price;
      const made = [];
      const st = [];
      for (let i = 0; i < n; i++) {
        const k = newKey(env.KEY_PREFIX || "VAI");
        made.push(k);
        st.push(DB.prepare("INSERT INTO keys (key, product, plan, days, price, customer, note, created_at) VALUES (?,?,?,?,?,?,?,?)")
          .bind(k, product, plan.code, days, price, b.customer || null, b.note || null, now()));
      }
      await DB.batch(st);
      await log(env, "admin_create", made[0], null, `${n} key ${plan.code}`);
      return json({ ok: true, keys: made });
    }
    case "revoke":
      await DB.prepare("UPDATE keys SET status='revoked' WHERE key=?").bind(b.key).run();
      await log(env, "admin_revoke", b.key);
      return json({ ok: true });
    case "unrevoke":
      await DB.prepare("UPDATE keys SET status=CASE WHEN machine IS NULL THEN 'new' ELSE 'active' END WHERE key=? AND status='revoked'").bind(b.key).run();
      return json({ ok: true });
    case "extend": {
      const k = await DB.prepare("SELECT * FROM keys WHERE key=?").bind(b.key).first();
      if (!k) return fail("bad_key", "Không thấy key");
      const d = parseInt(b.days, 10) || 0;
      if (k.status === "new") await DB.prepare("UPDATE keys SET days=days+? WHERE id=?").bind(d, k.id).run();
      else if (k.expires_at !== 0) await DB.prepare("UPDATE keys SET expires_at=?+?*86400 WHERE id=?").bind(Math.max(k.expires_at, now()), d, k.id).run();
      await log(env, "admin_extend", b.key, null, `+${d}`);
      return json({ ok: true });
    }
    case "lifetime":
      await DB.prepare("UPDATE keys SET expires_at=CASE WHEN status='new' THEN expires_at ELSE 0 END, days=0, plan='life' WHERE key=?").bind(b.key).run();
      return json({ ok: true });
    case "reset_machine":
      await DB.prepare("UPDATE keys SET machine=NULL, status=CASE WHEN status='active' THEN 'active' ELSE status END, last_transfer_at=NULL WHERE key=?").bind(b.key).run();
      await log(env, "admin_reset", b.key);
      return json({ ok: true });
    case "note":
      await DB.prepare("UPDATE keys SET customer=?, note=? WHERE key=?").bind(b.customer || null, b.note || null, b.key).run();
      return json({ ok: true });
    case "plans": {
      if (request.method === "POST") {
        for (const p of b.plans || []) {
          await DB.prepare("UPDATE plans SET name=?, days=?, price=?, badge=?, active=? WHERE product=? AND code=?")
            .bind(p.name, parseInt(p.days, 10), parseInt(p.price, 10), p.badge || null, p.active ? 1 : 0, product, p.code).run();
        }
      }
      const rows = await DB.prepare("SELECT * FROM plans WHERE product=? ORDER BY sort").bind(product).all();
      return json({ ok: true, plans: rows.results || [] });
    }
    case "orders": {
      const rows = await DB.prepare("SELECT * FROM orders WHERE product=? ORDER BY created_at DESC LIMIT 200").bind(product).all();
      return json({ ok: true, orders: rows.results || [] });
    }
    case "trials": {
      const rows = await DB.prepare("SELECT * FROM trials WHERE product=? ORDER BY started_at DESC LIMIT 300").bind(product).all();
      return json({ ok: true, trials: rows.results || [], now: now() });
    }
    case "trial_extend":
      await DB.prepare("UPDATE trials SET expires_at=MAX(expires_at, ?)+?*86400 WHERE product=? AND machine=?")
        .bind(now(), parseInt(b.days, 10) || 0, product, b.machine).run();
      return json({ ok: true });
    case "events": {
      const rows = await DB.prepare("SELECT * FROM events ORDER BY id DESC LIMIT 200").all();
      return json({ ok: true, events: rows.results || [] });
    }
  }
  return fail("not_found", "Không có chức năng này", 404);
}

// ------------------------------------------------------------------ chống dò key (giới hạn đơn giản theo IP)
const hits = new Map();
function limited(ip, max = 30) {
  const t = Math.floor(Date.now() / 60000);
  const k = `${ip}:${t}`;
  const n = (hits.get(k) || 0) + 1;
  hits.set(k, n);
  if (hits.size > 5000) hits.clear();
  return n > max;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    const ip = request.headers.get("cf-connecting-ip") || "local";
    try {
      if (path === "/" || path === "/admin") {
        return new Response(ADMIN_HTML, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
      }
      if (path.startsWith("/admin/api/")) {
        if (!adminOK(env, request)) {
          if (limited("adm:" + ip, 10)) return fail("rate", "Thử quá nhiều lần", 429);
          return fail("unauthorized", "Sai mật khẩu quản trị", 401);
        }
        return admin(env, path.slice("/admin/api/".length), request);
      }
      if (path === "/v1/sepay" && request.method === "POST") return sepayWebhook(env, request);
      if (path === "/v1/plans") return apiPlans(env, (url.searchParams.get("product") || "videoai").toLowerCase());
      if (path === "/v1/order" && request.method === "GET")
        return apiOrderStatus(env, url.searchParams.get("code"), url.searchParams.get("machine"));

      if (request.method !== "POST") return fail("not_found", "Không có", 404);
      if (limited(ip)) return fail("rate", "Bạn thao tác quá nhanh, thử lại sau 1 phút.", 429);
      const b = await request.json().catch(() => ({}));
      if (!validProduct(b.product)) return fail("bad_request", "Thiếu mã sản phẩm");
      if (!validMachine(b.machine)) return fail("bad_request", "Mã máy không hợp lệ");
      if (path === "/v1/trial") return apiTrial(env, b);
      if (path === "/v1/activate") return apiActivate(env, b);
      if (path === "/v1/check") return apiCheck(env, b);
      if (path === "/v1/order") return apiOrder(env, b);
      return fail("not_found", "Không có", 404);
    } catch (e) {
      return fail("server", "Lỗi máy chủ: " + (e && e.message ? e.message : e), 500);
    }
  },
};
