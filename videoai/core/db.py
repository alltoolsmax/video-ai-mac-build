"""SQLite: một file, WAL, an toàn đa luồng nhờ khóa + kết nối riêng mỗi luồng."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .paths import data_dir

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS accounts (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  label TEXT NOT NULL,
  profile_dir TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'unknown' CHECK (status IN ('unknown','ok','expired','needs_user')),
  credits_left INTEGER,
  enabled INTEGER NOT NULL DEFAULT 1,
  last_check_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_accounts_platform ON accounts(platform, enabled);
CREATE TABLE IF NOT EXISTS characters (
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
  images TEXT NOT NULL DEFAULT '[]', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS refs (
  id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, grp TEXT NOT NULL DEFAULT 'Nhân vật',
  description TEXT NOT NULL DEFAULT '', path TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_refs_grp ON refs(grp);
CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY, platform TEXT NOT NULL, page TEXT NOT NULL,
  params TEXT NOT NULL DEFAULT '{}', save_dir TEXT NOT NULL,
  save_mode TEXT NOT NULL DEFAULT 'per_task' CHECK (save_mode IN ('per_task','flat','per_batch')),
  source TEXT NOT NULL DEFAULT 'ui' CHECK (source IN ('ui','workflow','webhook')),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
  account_id TEXT REFERENCES accounts(id) ON DELETE SET NULL,
  row_no INTEGER NOT NULL,
  mode TEXT NOT NULL,
  prompt TEXT NOT NULL,
  refs TEXT NOT NULL DEFAULT '[]',
  params TEXT NOT NULL DEFAULT '{}',
  count INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued','running','paused','done','failed','blocked','needs_user','cancelled')),
  progress INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  error_code TEXT, error_text TEXT, started_at TEXT, finished_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (batch_id, row_no)
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id);
CREATE TABLE IF NOT EXISTS outputs (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('image','video','audio')),
  path TEXT NOT NULL UNIQUE,
  width INTEGER, height INTEGER, duration_ms INTEGER,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outputs_job ON outputs(job_id);
CREATE TABLE IF NOT EXISTS workflows (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, graph TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS editor_projects (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stats_daily (
  day TEXT NOT NULL, platform TEXT NOT NULL,
  done INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, platform)
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id() -> str:
    return uuid.uuid4().hex


class Database:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_dir() / "app.db"
        self._lock = threading.RLock()
        self._local = threading.local()
        with self.conn() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)

    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys=ON")
            self._local.c = c
        return c

    # --- helpers -------------------------------------------------------
    def execute(self, sql: str, args: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            c = self.conn()
            cur = c.execute(sql, tuple(args))
            c.commit()
            return cur

    def query(self, sql: str, args: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self.conn().execute(sql, tuple(args)).fetchall()]

    def one(self, sql: str, args: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, args)
        return rows[0] if rows else None

    # --- settings ------------------------------------------------------
    def get_setting(self, key: str, default: Any = None) -> Any:
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        if not r:
            return default
        try:
            return json.loads(r["value"])
        except Exception:
            return r["value"]

    def set_setting(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )

    # --- accounts ------------------------------------------------------
    def add_account(self, platform: str, label: str, profile_dir: str) -> str:
        i = new_id()
        t = now()
        self.execute(
            "INSERT INTO accounts(id,platform,label,profile_dir,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (i, platform, label, profile_dir, t, t),
        )
        return i

    def accounts(self, platform: str | None = None) -> list[dict]:
        if platform:
            return self.query("SELECT * FROM accounts WHERE platform=? ORDER BY created_at", (platform,))
        return self.query("SELECT * FROM accounts ORDER BY platform, created_at")

    def update_account(self, account_id: str, **fields) -> None:
        if not fields:
            return
        fields["updated_at"] = now()
        cols = ",".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE accounts SET {cols} WHERE id=?", (*fields.values(), account_id))

    def delete_account(self, account_id: str) -> None:
        self.execute("DELETE FROM accounts WHERE id=?", (account_id,))

    # --- batches / jobs --------------------------------------------------
    def create_batch(self, platform: str, page: str, params: dict, save_dir: str,
                     save_mode: str, rows: list[dict], source: str = "ui") -> str:
        bid = new_id()
        t = now()
        with self._lock:
            c = self.conn()
            c.execute(
                "INSERT INTO batches(id,platform,page,params,save_dir,save_mode,source,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (bid, platform, page, json.dumps(params, ensure_ascii=False), save_dir, save_mode, source, t),
            )
            for n, r in enumerate(rows, 1):
                c.execute(
                    "INSERT INTO jobs(id,batch_id,row_no,mode,prompt,refs,params,count,created_at,updated_at)"
                    " VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id(), bid, n, r["mode"], r["prompt"],
                     json.dumps(r.get("refs", []), ensure_ascii=False),
                     json.dumps(r.get("params", {}), ensure_ascii=False),
                     int(r.get("count", 1)), t, t),
                )
            c.commit()
        return bid

    def update_job(self, job_id: str, **fields) -> None:
        fields["updated_at"] = now()
        cols = ",".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))

    def job(self, job_id: str) -> dict | None:
        return self.one("SELECT * FROM jobs WHERE id=?", (job_id,))

    def jobs_for_platform(self, platform: str, page: str, limit: int = 500) -> list[dict]:
        return self.query(
            "SELECT j.*, b.save_dir, b.save_mode, b.params AS batch_params, b.platform, b.page"
            " FROM jobs j JOIN batches b ON b.id=j.batch_id"
            " WHERE b.platform=? AND b.page=? ORDER BY b.created_at DESC, j.row_no LIMIT ?",
            (platform, page, limit),
        )

    def next_queued(self, exclude_pages: set[str] | None = None) -> list[dict]:
        return self.query(
            "SELECT j.*, b.save_dir, b.save_mode, b.params AS batch_params, b.platform, b.page"
            " FROM jobs j JOIN batches b ON b.id=j.batch_id WHERE j.status='queued'"
            " ORDER BY b.created_at, j.row_no"
        )

    def add_output(self, job_id: str, kind: str, path: str, **meta) -> None:
        self.execute(
            "INSERT OR IGNORE INTO outputs(id,job_id,kind,path,width,height,duration_ms,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (new_id(), job_id, kind, path, meta.get("width"), meta.get("height"), meta.get("duration_ms"), now()),
        )

    def outputs(self, job_id: str) -> list[dict]:
        return self.query("SELECT * FROM outputs WHERE job_id=? ORDER BY created_at", (job_id,))

    def bump_stat(self, platform: str, ok: bool) -> None:
        day = datetime.now().strftime("%Y-%m-%d")
        col = "done" if ok else "failed"
        self.execute(
            f"INSERT INTO stats_daily(day,platform,{col}) VALUES(?,?,1)"
            f" ON CONFLICT(day,platform) DO UPDATE SET {col}={col}+1",
            (day, platform),
        )

    def recover_running(self) -> int:
        """Gọi khi mở app: tác vụ đang chạy dở được đưa về hàng đợi."""
        cur = self.execute("UPDATE jobs SET status='queued', progress=0 WHERE status='running'")
        return cur.rowcount

    def counts_all(self) -> dict[str, int]:
        """Đếm tác vụ theo trạng thái trên MỌI nền tảng / trang (4 ô đếm dùng chung)."""
        rows = self.query("SELECT status, COUNT(*) n FROM jobs GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    def counts(self, platform: str, page: str) -> dict[str, int]:
        rows = self.query(
            "SELECT j.status, COUNT(*) n FROM jobs j JOIN batches b ON b.id=j.batch_id"
            " WHERE b.platform=? AND b.page=? GROUP BY j.status",
            (platform, page),
        )
        return {r["status"]: r["n"] for r in rows}
