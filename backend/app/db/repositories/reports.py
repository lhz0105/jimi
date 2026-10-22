from __future__ import annotations

from typing import Any

from app.core.clock import now_ms
from app.core.ids import new_id
from app.db.database import Database
from app.db.repositories.util import loads_json


async def upsert(
    db: Database,
    *,
    run_id: str,
    report: dict[str, Any],
    markdown: str,
    version: str = "v1",
) -> dict[str, Any]:
    import json

    existing = await get_by_run(db, run_id)
    payload = json.dumps(report, ensure_ascii=False)
    if existing is None:
        report_id = new_id("rep")
        await db.execute(
            """INSERT INTO reports(id, run_id, json, markdown, version, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (report_id, run_id, payload, markdown, version, now_ms()),
        )
    else:
        report_id = existing["id"]
        await db.execute(
            "UPDATE reports SET json = ?, markdown = ?, version = ? WHERE run_id = ?",
            (payload, markdown, version, run_id),
        )
    return await get_by_run(db, run_id)  # type: ignore[return-value]


async def get_by_run(db: Database, run_id: str) -> dict[str, Any] | None:
    row = await db.fetchone("SELECT * FROM reports WHERE run_id = ?", (run_id,))
    if row is None:
        return None
    d = dict(row)
    d["json"] = loads_json(d.get("json"), {})
    return d
