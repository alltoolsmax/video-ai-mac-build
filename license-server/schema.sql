-- Máy chủ bản quyền Mr. Huỳnh (Cloudflare D1). Dùng chung cho nhiều phần mềm: cột product.
CREATE TABLE IF NOT EXISTS plans (
  product     TEXT NOT NULL,
  code        TEXT NOT NULL,            -- m1, m3, m6, y1, life
  name        TEXT NOT NULL,
  days        INTEGER NOT NULL,         -- 0 = vĩnh viễn
  price       INTEGER NOT NULL,         -- VNĐ
  sort        INTEGER NOT NULL DEFAULT 0,
  badge       TEXT,                     -- "Phổ biến", "Tiết kiệm nhất"...
  active      INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (product, code)
);

CREATE TABLE IF NOT EXISTS keys (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  key              TEXT NOT NULL UNIQUE, -- VAI-XXXX-XXXX-XXXX-XXXX
  product          TEXT NOT NULL,
  plan             TEXT NOT NULL,
  days             INTEGER NOT NULL,     -- 0 = vĩnh viễn
  status           TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','active','merged','revoked')),
  machine          TEXT,                 -- mã máy đang dùng key
  activated_at     INTEGER,
  expires_at       INTEGER,              -- unix giây; 0 = vĩnh viễn
  transfers        INTEGER NOT NULL DEFAULT 0,
  last_transfer_at INTEGER,
  merged_into      TEXT,                 -- key gia hạn đã cộng vào key nào
  customer         TEXT,                 -- tên / SĐT / Zalo khách
  note             TEXT,
  order_code       TEXT,
  price            INTEGER NOT NULL DEFAULT 0,
  created_at       INTEGER NOT NULL,
  last_check_at    INTEGER
);
CREATE INDEX IF NOT EXISTS keys_machine ON keys(product, machine);
CREATE INDEX IF NOT EXISTS keys_created ON keys(created_at);

CREATE TABLE IF NOT EXISTS trials (
  product     TEXT NOT NULL,
  machine     TEXT NOT NULL,
  started_at  INTEGER NOT NULL,
  expires_at  INTEGER NOT NULL,
  PRIMARY KEY (product, machine)
);

CREATE TABLE IF NOT EXISTS orders (
  code        TEXT PRIMARY KEY,          -- nội dung chuyển khoản, vd VAI8K2P4Q
  product     TEXT NOT NULL,
  plan        TEXT NOT NULL,
  amount      INTEGER NOT NULL,
  machine     TEXT,
  status      TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','paid','expired')),
  key         TEXT,
  bank_ref    TEXT UNIQUE,               -- mã giao dịch ngân hàng (chống cộng 2 lần)
  created_at  INTEGER NOT NULL,
  paid_at     INTEGER
);

CREATE TABLE IF NOT EXISTS events (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  at      INTEGER NOT NULL,
  kind    TEXT NOT NULL,
  key     TEXT,
  machine TEXT,
  detail  TEXT
);
CREATE INDEX IF NOT EXISTS events_at ON events(at);

-- Bảng giá mặc định của Video AI - Mr. Huỳnh (sửa được trong trang quản trị, phần mềm tự cập nhật)
INSERT OR IGNORE INTO plans (product, code, name, days, price, sort, badge) VALUES
  ('videoai', 'm1',   '1 tháng',    30,  50000,  1, NULL),
  ('videoai', 'm3',   '3 tháng',    90,  120000, 2, 'Tiết kiệm 20%'),
  ('videoai', 'm6',   '6 tháng',    180, 220000, 3, 'Phổ biến'),
  ('videoai', 'y1',   '1 năm',      365, 400000, 4, 'Tiết kiệm 33%'),
  ('videoai', 'life', 'Vĩnh viễn',  0,   800000, 5, 'Mua 1 lần');
