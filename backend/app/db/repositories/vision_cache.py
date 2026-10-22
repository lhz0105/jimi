from __future__ import annotations

import json
from typing import Any

from app.core.clock import now_ms
from app.db.database import Database
from app.db.repositories.util import loads_json


async def get(db: Database, sha256: str, prompt_hash: str, model: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        "SELECT result_json FROM vision_cache WHERE sha256 = ? AND prompt_hash = ? AND model = ?",
        (sha256, prompt_hash, model),
    )
    if row is None:
        return None
    return loads_json(row["result_json"], {})


async def put(
    db: Database, sha256: str, prompt_hash: str, model: str, result: dict[str, Any]
) -> None:
    await db.execute(
        """INSERT OR REPLACE INTO vision_cache(sha256, prompt_hash, model, result_json, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (sha256, prompt_hash, model, json.dumps(result, ensure_ascii=False), now_ms()),
    )
