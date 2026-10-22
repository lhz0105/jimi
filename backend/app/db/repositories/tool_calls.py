from __future__ import annotations

import json
from typing import Any

from app.core.clock import now_ms
from app.core.ids import new_id
from app.db.database import Database
from app.db.repositories.util import loads_json


async def add(
    db: Database,
    *,
    run_id: str,
    seq: int,
    tool: str,
    args: dict[str, Any],
    status: str = "ok",
    result: dict[str, Any] | None = None,
    result_ref: str | None = None,
    latency_ms: int | None = None,
    cost: dict[str, Any] | None = None,
) -> str:
    tc_id = new_id("tc")
    await db.execute(
        """INSERT INTO tool_calls(id, run_id, seq, tool, args_json, result_json, result_ref,
                                  status, latency_ms, cost_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            tc_id,
            run_id,
            seq,
            tool,
            json.dumps(args, ensure_ascii=False),
            json.dumps(result, ensure_ascii=False) if result is not None else None,
            result_ref,
            status,
            latency_ms,
            json.dumps(cost or {}, ensure_ascii=False),
            now_ms(),
        ),
    )
    return tc_id


def _decorate(d: dict[str, Any]) -> dict[str, Any]:
    d["args_json"] = loads_json(d.get("args_json"), {})
    d["result_json"] = loads_json(d.get("result_json"), None)
    d["cost_json"] = loads_json(d.get("cost_json"), {})
    return d


async def list_by_run(db: Database, run_id: str) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY seq, created_at", (run_id,)
    )
    return [_decorate(dict(r)) for r in rows]
