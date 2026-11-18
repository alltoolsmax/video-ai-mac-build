"""Thư viện nhân vật: lưu tên, mô tả, ảnh. Trong prompt gõ @Ten để chèn mô tả + ảnh tham chiếu."""
from __future__ import annotations

import json
import re

from ..core.db import Database, new_id, now

TAG = re.compile(r"@([\wÀ-ỹ]+)", re.UNICODE)


class Characters:
    def __init__(self, db: Database):
        self.db = db

    def all(self) -> list[dict]:
        rows = self.db.query("SELECT * FROM characters ORDER BY name")
        for r in rows:
            r["images"] = json.loads(r["images"] or "[]")
        return rows

    def save(self, name: str, description: str, images: list[str], cid: str | None = None) -> str:
        t = now()
        if cid:
            self.db.execute("UPDATE characters SET name=?, description=?, images=?, updated_at=? WHERE id=?",
                            (name, description, json.dumps(images, ensure_ascii=False), t, cid))
            return cid
        cid = new_id()
        self.db.execute("INSERT INTO characters(id,name,description,images,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                        (cid, name, description, json.dumps(images, ensure_ascii=False), t, t))
        return cid

    def delete(self, cid: str) -> None:
        self.db.execute("DELETE FROM characters WHERE id=?", (cid,))

    def expand(self, prompt: str, with_description: bool = True) -> tuple[str, list[str]]:
        """Trả về (prompt đã thay @Ten, danh sách ảnh tham chiếu của các nhân vật được nhắc)."""
        chars = {c["name"].lower(): c for c in self.all()}
        refs: list[str] = []

        def sub(m):
            c = chars.get(m.group(1).lower())
            if not c:
                return m.group(0)
            for im in c["images"]:
                if im not in refs:
                    refs.append(im)
            if with_description and c["description"].strip():
                return f"{c['name']} ({c['description'].strip()})"
            return c["name"]

        return TAG.sub(sub, prompt), refs
