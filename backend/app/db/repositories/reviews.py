"""人工复核记录与对话消息。"""

from __future__ import annotations

from typing import Any

from app.core.clock import now_ms
from app.core.ids import new_id
from app.db.database import Database
from app.db.repositories.util import dumps_json, loads_json, row_to_dict

_UPDATABLE = {
    "status",
    "agent_turns",
    "llm_usage_json",
    "generation_error",
    "generated_at",
    "verdict",
    "reason",
    "reviewer",
}


def _decorate(row: Any) -> dict[str, Any] | None:
    d = row_to_dict(row)
    if d is None:
        return None
    d["llm_usage"] = loads_json(d.pop("llm_usage_json", None), {})
    return d


async def create(
    db: Database,
    *,
    run_id: str,
    verdict: str,
    reason: str,
    reviewer: str,
    status: str = "in_dialogue",
) -> dict[str, Any]:
    review_id = new_id("rev")
    ts = now_ms()
    await db.execute(
        """INSERT INTO run_reviews(id, run_id, verdict, reason, reviewer, status,
                                   agent_turns, llm_usage_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 0, '{}', ?, ?)""",
        (review_id, run_id, verdict, reason, reviewer, status, ts, ts),
    )
    return await get(db, review_id)  # type: ignore[return-value]


async def get(db: Database, review_id: str) -> dict[str, Any] | None:
    return _decorate(await db.fetchone("SELECT * FROM run_reviews WHERE id = ?", (review_id,)))


async def get_by_run(db: Database, run_id: str) -> dict[str, Any] | None:
    return _decorate(await db.fetchone("SELECT * FROM run_reviews WHERE run_id = ?", (run_id,)))


async def update(db: Database, review_id: str, **fields: Any) -> dict[str, Any] | None:
    clean = {k: v for k, v in fields.items() if k in _UPDATABLE}
    clean["updated_at"] = now_ms()
    sets = ", ".join(f"{k} = ?" for k in clean)
    await db.execute(
        f"UPDATE run_reviews SET {sets} WHERE id = ?", (*clean.values(), review_id)
    )
    return await get(db, review_id)


async def add_message(
    db: Database,
    *,
    review_id: str,
    role: str,
    content: str,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message_id = new_id("rmsg")
    ts = now_ms()
    await db.execute(
        """INSERT INTO review_messages(id, review_id, role, content, meta_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (message_id, review_id, role, content, dumps_json(meta or {}), ts),
    )
    return {
        "id": message_id,
        "review_id": review_id,
        "role": role,
        "content": content,
        "meta": meta or {},
        "created_at": ts,
    }


async def list_messages(db: Database, review_id: str) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "SELECT * FROM review_messages WHERE review_id = ? ORDER BY created_at, rowid",
        (review_id,),
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["meta"] = loads_json(d.pop("meta_json", None), {})
        out.append(d)
    return out
