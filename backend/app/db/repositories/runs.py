from __future__ import annotations

from typing import Any

from app.core.clock import now_ms
from app.db.database import Database
from app.db.repositories.util import dumps_json, loads_json, row_to_dict

TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")
ACTIVE_STATUSES = ("queued", "awaiting_confirm", "running")


async def create(
    db: Database,
    *,
    run_id: str,
    conversation_id: str | None,
    scenario: str,
    trigger_mode: str,
    status: str,
    rules_decision: dict[str, Any] | None = None,
    input_snapshot: dict[str, Any] | None = None,
    external_ref: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    callback_url: str | None = None,
) -> dict[str, Any]:
    ts = now_ms()
    await db.execute(
        """INSERT INTO analysis_runs(id, conversation_id, scenario, trigger_mode, status,
                                     rules_decision, input_snapshot, external_ref_json,
                                     idempotency_key, callback_url, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            run_id,
            conversation_id,
            scenario,
            trigger_mode,
            status,
            dumps_json(rules_decision or {}),
            dumps_json(input_snapshot or {}),
            dumps_json(external_ref or {}),
            idempotency_key,
            callback_url,
            ts,
        ),
    )
    return await get(db, run_id)  # type: ignore[return-value]


def _decorate(d: dict[str, Any] | None) -> dict[str, Any] | None:
    if d is None:
        return None
    for field in ("rules_decision", "input_snapshot", "verdict", "cost_json", "progress_json"):
        d[field] = loads_json(d.get(field), {} if field != "verdict" else None)
    d["external_ref"] = loads_json(d.pop("external_ref_json", None), None)
    return d


async def get(db: Database, run_id: str) -> dict[str, Any] | None:
    row = await db.fetchone("SELECT * FROM analysis_runs WHERE id = ?", (run_id,))
    return _decorate(row_to_dict(row))


async def get_by_idempotency(db: Database, key: str) -> dict[str, Any] | None:
    row = await db.fetchone("SELECT * FROM analysis_runs WHERE idempotency_key = ?", (key,))
    return _decorate(row_to_dict(row))


async def list_page(
    db: Database,
    *,
    status: str | None = None,
    scenario: str | None = None,
    conversation_id: str | None = None,
    q: str | None = None,
    review: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where, params = _filters(status, scenario, conversation_id, q, review)
    rows = await db.fetchall(
        f"""SELECT r.*, c.customer_name, rv.status AS review_status
              FROM analysis_runs r
              LEFT JOIN conversations c ON c.id = r.conversation_id
              LEFT JOIN run_reviews rv ON rv.run_id = r.id
             {where}
             ORDER BY r.created_at DESC
             LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        d = _decorate(dict(row))
        assert d is not None
        d["review_required"] = bool(d.get("review_required"))
        if d.get("review_status") is None:
            d["review_status"] = "needed" if d["review_required"] else "none"
        items.append(d)
    return items


async def count(
    db: Database,
    *,
    status: str | None = None,
    scenario: str | None = None,
    conversation_id: str | None = None,
    q: str | None = None,
    review: str | None = None,
) -> int:
    where, params = _filters(status, scenario, conversation_id, q, review)
    return int(
        await db.fetchval(
            f"""SELECT COUNT(*) FROM analysis_runs r
                LEFT JOIN run_reviews rv ON rv.run_id = r.id {where}""",
            params,
        )
        or 0
    )


def _filters(
    status: str | None,
    scenario: str | None,
    conversation_id: str | None,
    q: str | None,
    review: str | None = None,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("r.status = ?")
        params.append(status)
    if scenario:
        clauses.append("r.scenario = ?")
        params.append(scenario)
    if conversation_id:
        clauses.append("r.conversation_id = ?")
        params.append(conversation_id)
    if q:
        clauses.append("(r.id LIKE ? OR r.error LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if review == "needed":
        clauses.append(
            "r.review_required = 1 AND (rv.id IS NULL OR rv.status != 'generated')"
        )
    elif review == "reviewed":
        clauses.append("rv.status = 'generated'")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, tuple(params)


async def set_review_required(db: Database, run_id: str, required: bool) -> None:
    await db.execute(
        "UPDATE analysis_runs SET review_required = ? WHERE id = ?",
        (1 if required else 0, run_id),
    )


async def list_by_conversation(db: Database, conversation_id: str) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "SELECT * FROM analysis_runs WHERE conversation_id = ? ORDER BY created_at DESC",
        (conversation_id,),
    )
    return [_decorate(dict(r)) for r in rows]  # type: ignore[misc]


async def update_status(
    db: Database,
    run_id: str,
    status: str,
    *,
    error: str | None = None,
    mark_started: bool = False,
    mark_finished: bool = False,
) -> None:
    sets = ["status = ?"]
    params: list[Any] = [status]
    if error is not None:
        sets.append("error = ?")
        params.append(error)
    if mark_started:
        sets.append("started_at = ?")
        params.append(now_ms())
    if mark_finished:
        sets.append("finished_at = ?")
        params.append(now_ms())
    params.append(run_id)
    await db.execute(f"UPDATE analysis_runs SET {', '.join(sets)} WHERE id = ?", tuple(params))


async def set_progress(db: Database, run_id: str, progress: dict[str, Any]) -> None:
    await db.execute(
        "UPDATE analysis_runs SET progress_json = ? WHERE id = ?", (dumps_json(progress), run_id)
    )


async def set_verdict(
    db: Database,
    run_id: str,
    verdict: dict[str, Any],
    *,
    risk_level: str | None,
    confidence: float | None,
) -> None:
    await db.execute(
        "UPDATE analysis_runs SET verdict = ?, risk_level = ?, confidence = ? WHERE id = ?",
        (dumps_json(verdict), risk_level, confidence, run_id),
    )


async def set_cost(db: Database, run_id: str, cost: dict[str, Any]) -> None:
    await db.execute(
        "UPDATE analysis_runs SET cost_json = ? WHERE id = ?", (dumps_json(cost), run_id)
    )


async def update_input_snapshot(
    db: Database, run_id: str, snapshot: dict[str, Any]
) -> None:
    await db.execute(
        "UPDATE analysis_runs SET input_snapshot = ? WHERE id = ?",
        (dumps_json(snapshot), run_id),
    )


async def get_active_for_conversation(
    db: Database, conversation_id: str
) -> dict[str, Any] | None:
    """该会话进行中的运行（排队/待确认/运行中），用于避免并发重复分析。"""
    placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
    row = await db.fetchone(
        f"""SELECT * FROM analysis_runs
             WHERE conversation_id = ? AND status IN ({placeholders})
             ORDER BY created_at DESC LIMIT 1""",
        (conversation_id, *ACTIVE_STATUSES),
    )
    return _decorate(row_to_dict(row))


async def stats_since(db: Database, since_ms: int) -> dict[str, Any]:
    row = await db.fetchone(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded,
                  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                  SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled,
                  SUM(CASE WHEN status IN ('queued', 'awaiting_confirm', 'running') THEN 1 ELSE 0 END) AS active
             FROM analysis_runs WHERE created_at >= ?""",
        (since_ms,),
    )
    return dict(row) if row is not None else {}
