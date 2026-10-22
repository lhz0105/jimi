from __future__ import annotations

import json
from typing import Any

from app.core.clock import now_ms
from app.db.database import Database
from app.db.repositories.util import loads_json


async def upsert(
    db: Database,
    *,
    sha256: str,
    phash: str | None,
    dhash: str | None,
    ahash: str | None,
    width: int | None,
    height: int | None,
    mime: str | None,
    exif: dict[str, Any] | None,
    first_run_id: str | None = None,
) -> None:
    await db.execute(
        """INSERT INTO image_hashes(sha256, phash, dhash, ahash, width, height, mime,
                                    exif_json, first_run_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(sha256) DO UPDATE SET
             phash=excluded.phash, dhash=excluded.dhash, ahash=excluded.ahash,
             width=excluded.width, height=excluded.height, mime=excluded.mime,
             exif_json=excluded.exif_json""",
        (
            sha256,
            phash,
            dhash,
            ahash,
            width,
            height,
            mime,
            json.dumps(exif or {}, ensure_ascii=False),
            first_run_id,
            now_ms(),
        ),
    )


async def get(db: Database, sha256: str) -> dict[str, Any] | None:
    row = await db.fetchone("SELECT * FROM image_hashes WHERE sha256 = ?", (sha256,))
    if row is None:
        return None
    d = dict(row)
    d["exif_json"] = loads_json(d.get("exif_json"), {})
    return d


async def list_with_phash(db: Database, *, exclude_sha: str | None = None, limit: int = 500) -> list[dict[str, Any]]:
    if exclude_sha:
        rows = await db.fetchall(
            "SELECT * FROM image_hashes WHERE phash IS NOT NULL AND sha256 != ? LIMIT ?",
            (exclude_sha, limit),
        )
    else:
        rows = await db.fetchall(
            "SELECT * FROM image_hashes WHERE phash IS NOT NULL LIMIT ?", (limit,)
        )
    return [dict(r) for r in rows]
