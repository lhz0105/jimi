from __future__ import annotations

from typing import Any

from app.core.clock import now_ms
from app.core.ids import new_id
from app.db.database import Database


async def add(
    db: Database, *, run_id: str, decision: str, decided_by: str = ""
) -> dict[str, Any]:
    conf_id = new_id("conf")
    ts = now_ms()
    await db.execute(
        """INSERT INTO run_confirmations(id, run_id, decision, decided_by, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (conf_id, run_id, decision, decided_by, ts),
    )
    return {
        "id": conf_id,
        "run_id": run_id,
        "decision": decision,
        "decided_by": decided_by,
        "created_at": ts,
    }


async def list_by_run(db: Database, run_id: str) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "SELECT * FROM run_confirmations WHERE run_id = ? ORDER BY created_at", (run_id,)
    )
    return [dict(r) for r in rows]
