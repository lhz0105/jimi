"""先前案例（人工判决沉淀）仓储。"""

from __future__ import annotations

from typing import Any

from app.core.clock import now_ms
from app.core.ids import new_id
from app.db.database import Database
from app.db.repositories.util import dumps_json, loads_json, row_to_dict


def _decorate(row: Any) -> dict[str, Any] | None:
    d = row_to_dict(row)
    if d is None:
        return None
    d["metadata"] = loads_json(d.pop("metadata_json", None), {})
    alpha = float(d.get("alpha") or 2.0)
    beta = float(d.get("beta") or 2.0)
    d["alpha"] = alpha
    d["beta"] = beta
    d["reliability"] = round(alpha / (alpha + beta), 4) if alpha + beta else 0.5
    return d


def _decorate_feedback(row: Any) -> dict[str, Any] | None:
    d = row_to_dict(row)
    if d is None:
        return None
    d["evidence_ids"] = loads_json(d.pop("evidence_ids_json", None), [])
    return d


async def feedback_for_review(db: Database, review_id: str) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "SELECT * FROM prior_case_feedback WHERE review_id = ? ORDER BY created_at",
        (review_id,),
    )
    return [_decorate_feedback(r) for r in rows]  # type: ignore[misc]


async def list_feedback(db: Database, case_id: str) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "SELECT * FROM prior_case_feedback WHERE case_id = ? ORDER BY created_at",
        (case_id,),
    )
    return [_decorate_feedback(r) for r in rows]  # type: ignore[misc]


async def add_feedback(
    db: Database,
    *,
    case_id: str,
    run_id: str,
    review_id: str,
    signal: str,
    confidence: float,
    rationale: str,
    evidence_ids: list[str],
    alpha_delta: float = 0.0,
    beta_delta: float = 0.0,
    source: str = "agent_inferred",
) -> dict[str, Any] | None:
    existing = await db.fetchone(
        "SELECT * FROM prior_case_feedback WHERE review_id = ? AND case_id = ?",
        (review_id, case_id),
    )
    if existing is not None:
        return _decorate_feedback(existing)
    case = await get(db, case_id)
    if case is None:
        return None
    alpha = float(case["alpha"]) + alpha_delta
    beta = float(case["beta"]) + beta_delta
    after = alpha / (alpha + beta) if alpha + beta else 0.5
    ts = now_ms()
    feedback_id = new_id("fb")
    await db.execute(
        """INSERT INTO prior_case_feedback(
               id, case_id, run_id, review_id, signal, source, confidence,
               weight_before, weight_after, rationale, evidence_ids_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            feedback_id,
            case_id,
            run_id,
            review_id,
            signal,
            source,
            confidence,
            case["reliability"],
            round(after, 4),
            rationale,
            dumps_json(evidence_ids),
            ts,
        ),
    )
    await db.execute(
        """UPDATE prior_cases
              SET alpha = ?, beta = ?,
                  adopted_count = adopted_count + ?,
                  overturned_count = overturned_count + ?,
                  feedback_count = feedback_count + 1,
                  last_feedback_at = ?
            WHERE id = ?""",
        (
            alpha,
            beta,
            1 if alpha_delta else 0,
            1 if beta_delta else 0,
            ts,
            case_id,
        ),
    )
    row = await db.fetchone(
        "SELECT * FROM prior_case_feedback WHERE review_id = ? AND case_id = ?",
        (review_id, case_id),
    )
    return _decorate_feedback(row)


async def create(
    db: Database,
    *,
    review_id: str,
    run_id: str,
    title: str,
    scenario: str,
    human_verdict: str,
    markdown: str,
    metadata: dict[str, Any] | None = None,
    content_hash: str = "",
) -> dict[str, Any]:
    case_id = new_id("case")
    await db.execute(
        """INSERT INTO prior_cases(id, review_id, run_id, title, scenario, human_verdict,
                                   markdown, metadata_json, content_hash, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            case_id,
            review_id,
            run_id,
            title,
            scenario,
            human_verdict,
            markdown,
            dumps_json(metadata or {}),
            content_hash,
            now_ms(),
        ),
    )
    return await get(db, case_id)  # type: ignore[return-value]


async def get(db: Database, case_id: str) -> dict[str, Any] | None:
    return _decorate(await db.fetchone("SELECT * FROM prior_cases WHERE id = ?", (case_id,)))


async def delete(db: Database, case_id: str) -> dict[str, Any] | None:
    """删除先前案例；反馈级联清理，来源复核重置为可重新生成。"""
    row = await db.fetchone(
        "SELECT id, review_id, title FROM prior_cases WHERE id = ?", (case_id,)
    )
    if row is None:
        return None
    review_reset = False
    async with db.write() as conn:
        await conn.execute("DELETE FROM prior_case_feedback WHERE case_id = ?", (case_id,))
        await conn.execute("DELETE FROM prior_cases WHERE id = ?", (case_id,))
        if row["review_id"]:
            cursor = await conn.execute(
                """UPDATE run_reviews
                      SET status = 'in_dialogue', generated_at = NULL,
                          generation_error = NULL, updated_at = ?
                    WHERE id = ? AND status = 'generated'""",
                (now_ms(), row["review_id"]),
            )
            review_reset = cursor.rowcount > 0
    return {
        "id": row["id"],
        "review_id": row["review_id"],
        "title": row["title"],
        "review_reset": review_reset,
    }


async def get_by_review(db: Database, review_id: str) -> dict[str, Any] | None:
    return _decorate(
        await db.fetchone("SELECT * FROM prior_cases WHERE review_id = ?", (review_id,))
    )


async def list_page(
    db: Database, *, scenario: str | None = None, limit: int = 20, offset: int = 0
) -> list[dict[str, Any]]:
    where = "WHERE scenario = ?" if scenario else ""
    params: tuple[Any, ...] = (scenario,) if scenario else ()
    rows = await db.fetchall(
        f"""SELECT * FROM prior_cases {where}
            ORDER BY created_at DESC LIMIT ? OFFSET ?""",
        (*params, limit, offset),
    )
    return [_decorate(r) for r in rows]  # type: ignore[misc]


async def count(db: Database, *, scenario: str | None = None) -> int:
    where = "WHERE scenario = ?" if scenario else ""
    params: tuple[Any, ...] = (scenario,) if scenario else ()
    return int(await db.fetchval(f"SELECT COUNT(*) FROM prior_cases {where}", params) or 0)


async def all_cases(db: Database) -> list[dict[str, Any]]:
    rows = await db.fetchall("SELECT * FROM prior_cases ORDER BY created_at")
    return [_decorate(r) for r in rows]  # type: ignore[misc]


async def mark_indexed(
    db: Database, case_id: str, *, error: str | None = None
) -> None:
    await db.execute(
        "UPDATE prior_cases SET indexed_at = ?, index_error = ? WHERE id = ?",
        (None if error else now_ms(), error, case_id),
    )
