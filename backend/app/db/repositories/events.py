from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from app.db.database import Database
from app.db.repositories.util import loads_json


def _decorate(d: dict[str, Any]) -> dict[str, Any]:
    d["payload"] = loads_json(d.get("payload"), {})
    return d


async def insert_batch(db: Database, events: Iterable[dict[str, Any]]) -> int:
    rows = [
        (
            e["run_id"],
            int(e["seq"]),
            int(e["ts"]),
            e["type"],
            e.get("node"),
            e.get("level", "info"),
            json.dumps(e.get("payload", {}), ensure_ascii=False),
        )
        for e in events
    ]
    if not rows:
        return 0
    return await db.executemany(
        """INSERT OR REPLACE INTO run_events(run_id, seq, ts, type, node, level, payload)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )


async def list_after(
    db: Database,
    run_id: str,
    *,
    since_seq: int = 0,
    limit: int = 1000,
    ascending: bool = True,
) -> list[dict[str, Any]]:
    order = "ASC" if ascending else "DESC"
    rows = await db.fetchall(
        f"""SELECT * FROM run_events
             WHERE run_id = ? AND seq > ?
             ORDER BY seq {order}
             LIMIT ?""",
        (run_id, since_seq, limit),
    )
    return [_decorate(dict(r)) for r in rows]


async def list_latest(db: Database, run_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    events = await list_after(db, run_id, since_seq=0, limit=limit, ascending=False)
    return list(reversed(events))


async def max_seq(db: Database, run_id: str) -> int:
    return int(await db.fetchval("SELECT COALESCE(MAX(seq), 0) FROM run_events WHERE run_id = ?", (run_id,)) or 0)


async def count(db: Database, run_id: str) -> int:
    return int(await db.fetchval("SELECT COUNT(*) FROM run_events WHERE run_id = ?", (run_id,)) or 0)


async def delete_older_than(db: Database, ts: int) -> int:
    return await db.execute("DELETE FROM run_events WHERE ts < ?", (ts,))


async def type_counts(db: Database, run_id: str) -> dict[str, int]:
    rows = await db.fetchall(
        "SELECT type, COUNT(*) AS n FROM run_events WHERE run_id = ? GROUP BY type", (run_id,)
    )
    return {r["type"]: r["n"] for r in rows}
