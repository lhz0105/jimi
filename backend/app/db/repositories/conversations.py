from __future__ import annotations

from typing import Any

from app.core.clock import now_ms
from app.core.ids import new_id
from app.db.database import Database
from app.db.repositories.util import dumps_json, loads_json, row_to_dict


async def create(
    db: Database,
    *,
    customer_name: str = "",
    channel: str = "demo",
    mode: str = "manual",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    conv_id = new_id("conv")
    ts = now_ms()
    await db.execute(
        """INSERT INTO conversations(id, customer_name, channel, mode, meta, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (conv_id, customer_name, channel, mode, dumps_json(meta or {}), ts, ts),
    )
    return await get(db, conv_id)  # type: ignore[return-value]


async def get(db: Database, conv_id: str) -> dict[str, Any] | None:
    row = await db.fetchone("SELECT * FROM conversations WHERE id = ?", (conv_id,))
    d = row_to_dict(row)
    if d is not None:
        d["meta"] = loads_json(d.get("meta"), {})
    return d


async def list_page(db: Database, *, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        """SELECT c.*,
                  (SELECT m.content FROM messages m
                    WHERE m.conversation_id = c.id ORDER BY m.seq DESC LIMIT 1) AS last_message,
                  (SELECT r.status FROM analysis_runs r
                    WHERE r.conversation_id = c.id ORDER BY r.created_at DESC LIMIT 1) AS last_run_status
             FROM conversations c
            ORDER BY c.updated_at DESC
            LIMIT ? OFFSET ?""",
        (limit, offset),
    )
    out = []
    for row in rows:
        d = dict(row)
        d["meta"] = loads_json(d.get("meta"), {})
        out.append(d)
    return out


async def count(db: Database) -> int:
    return int(await db.fetchval("SELECT COUNT(*) FROM conversations") or 0)


async def set_mode(db: Database, conv_id: str, mode: str) -> bool:
    n = await db.execute(
        "UPDATE conversations SET mode = ?, updated_at = ? WHERE id = ?",
        (mode, now_ms(), conv_id),
    )
    return n > 0


async def touch(db: Database, conv_id: str) -> None:
    await db.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?", (now_ms(), conv_id)
    )
