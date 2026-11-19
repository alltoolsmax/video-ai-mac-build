"""Kho ảnh tham chiếu: mỗi ảnh có tên (@Tên), nhóm và mô tả. Ảnh được chép vào thư mục dữ liệu của ứng dụng
để kho không hỏng khi ảnh gốc bị di chuyển.

Dùng trong prompt: gõ @Tên → (tùy chọn) chèn mô tả vào prompt và gửi kèm ảnh làm tham chiếu cho dòng đó."""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from pathlib import Path

from ..core.db import Database, new_id, now
from ..core.paths import data_dir

TAG = re.compile(r"@([\wÀ-ỹ]+)", re.UNICODE)
GROUPS = ["Nhân vật", "Bối cảnh", "Trang phục", "Sản phẩm", "Đạo cụ", "Khác"]
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp")


def suggest_name(path: str) -> str:
    stem = Path(path).stem
    t = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    parts = re.split(r"[^A-Za-z0-9]+", t)
    name = "".join(p[:1].upper() + p[1:] for p in parts if p)
    return (name or "Anh")[:32]


class RefLibrary:
    def __init__(self, db: Database):
        self.db = db
        self.dir = data_dir() / "refs"
        self.dir.mkdir(parents=True, exist_ok=True)
        self._migrate_characters()

    # ---------------------------------------------------------------- dữ liệu
    def all(self, grp: str | None = None, query: str = "") -> list[dict]:
        rows = self.db.query("SELECT * FROM refs ORDER BY grp, name")
        if grp:
            rows = [r for r in rows if r["grp"] == grp]
        q = query.strip().lower()
        if q:
            rows = [r for r in rows if q in r["name"].lower() or q in r["description"].lower()]
        return rows

    def get(self, rid: str) -> dict | None:
        return self.db.one("SELECT * FROM refs WHERE id=?", (rid,))

    def by_name(self, name: str) -> dict | None:
        return self.db.one("SELECT * FROM refs WHERE name=? COLLATE NOCASE", (name,))

    def groups(self) -> list[tuple[str, int]]:
        rows = self.db.query("SELECT grp, COUNT(*) n FROM refs GROUP BY grp")
        counts = {r["grp"]: r["n"] for r in rows}
        extra = [g for g in counts if g not in GROUPS]
        return [(g, counts.get(g, 0)) for g in GROUPS + extra]

    def _unique_name(self, name: str, exclude_id: str | None = None) -> str:
        base = re.sub(r"[^\wÀ-ỹ]", "", name, flags=re.UNICODE)[:32] or "Anh"
        cand, k = base, 2
        while True:
            r = self.by_name(cand)
            if not r or r["id"] == exclude_id:
                return cand
            cand, k = f"{base}{k}", k + 1

    def add(self, src: str, name: str | None = None, grp: str = "Nhân vật", description: str = "") -> str:
        rid = new_id()
        ext = Path(src).suffix.lower() if Path(src).suffix.lower() in IMG_EXT else ".png"
        dst = self.dir / f"{rid}{ext}"
        shutil.copy(src, dst)
        t = now()
        self.db.execute("INSERT INTO refs(id,name,grp,description,path,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                        (rid, self._unique_name(name or suggest_name(src)), grp, description, str(dst), t, t))
        return rid

    def add_folder(self, folder: str, grp: str = "Nhân vật") -> int:
        n = 0
        for f in sorted(Path(folder).iterdir()):
            if f.suffix.lower() in IMG_EXT:
                self.add(str(f), None, grp)
                n += 1
        return n

    def update(self, rid: str, name: str, grp: str, description: str) -> str:
        nm = self._unique_name(name, rid)
        self.db.execute("UPDATE refs SET name=?, grp=?, description=?, updated_at=? WHERE id=?",
                        (nm, grp, description, now(), rid))
        return nm

    def replace_image(self, rid: str, src: str) -> None:
        r = self.get(rid)
        if not r:
            return
        ext = Path(src).suffix.lower() if Path(src).suffix.lower() in IMG_EXT else ".png"
        dst = self.dir / f"{rid}_{new_id()[:6]}{ext}"
        shutil.copy(src, dst)
        self.db.execute("UPDATE refs SET path=?, updated_at=? WHERE id=?", (str(dst), now(), rid))
        try:
            Path(r["path"]).unlink(missing_ok=True)
        except Exception:
            pass

    def delete(self, ids: list[str]) -> None:
        for rid in ids:
            r = self.get(rid)
            if r:
                self.db.execute("DELETE FROM refs WHERE id=?", (rid,))
                try:
                    Path(r["path"]).unlink(missing_ok=True)
                except Exception:
                    pass

    def paths(self, ids: list[str]) -> list[str]:
        out = []
        for rid in ids:
            r = self.get(rid)
            if r and Path(r["path"]).exists():
                out.append(r["path"])
        return out

    # ---------------------------------------------------------------- prompt
    def expand(self, prompt: str, with_description: bool = True) -> tuple[str, list[str]]:
        """@Tên → tên (+ mô tả); trả về (prompt mới, đường dẫn ảnh của các @Tên có trong kho)."""
        refs: list[str] = []

        def sub(m):
            r = self.by_name(m.group(1))
            if not r:
                return m.group(0)
            if Path(r["path"]).exists() and r["path"] not in refs:
                refs.append(r["path"])
            if with_description and r["description"].strip():
                return f"{r['name']} ({r['description'].strip()})"
            return r["name"]

        return TAG.sub(sub, prompt), refs

    # ---------------------------------------------------------------- chuyển dữ liệu cũ
    def _migrate_characters(self):
        try:
            if self.db.get_setting("refs_migrated"):
                return
            for c in self.db.query("SELECT * FROM characters"):
                imgs = [i for i in json.loads(c["images"] or "[]") if Path(i).exists()]
                if imgs and not self.by_name(c["name"]):
                    self.add(imgs[0], c["name"], "Nhân vật", c["description"])
            self.db.set_setting("refs_migrated", True)
        except Exception:
            pass


# tên cũ, để các phần khác (workflow, webhook) vẫn gọi được
Characters = RefLibrary
