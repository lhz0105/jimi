"""finalize：成本汇总、运行状态落库、callback 回推、run_end 事件。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.agent.budget import cost_summary
from app.db.repositories import runs as runs_repo
from app.observability.decorators import observed_node
from app.observability.events import EventType
from app.services.review_policy import requires_review

logger = logging.getLogger(__name__)


async def _push_callback(runtime: Any, state: dict[str, Any]) -> None:
    url = getattr(runtime, "callback_url", None)
    if not url:
        return
    verdict = state.get("verdict") or {}
    report = state.get("report") or {}
    body = {
        "run_id": runtime.run_id,
        "status": "succeeded",
        "scenario": state.get("scenario"),
        "conclusion": verdict.get("conclusion"),
        "risk_level": verdict.get("risk_level"),
        "confidence": verdict.get("confidence"),
        "summary": verdict.get("summary"),
        "report_id": report.get("report_id"),
        "cost": cost_summary(state.get("budget") or {}),
    }
    try:
        async with httpx.AsyncClient(timeout=runtime.settings.callback_timeout_s) as client:
            resp = await client.post(url, json=body)
            runtime.emitter.emit(
                EventType.WARNING,
                {
                    "code": "CALLBACK_PUSHED",
                    "message": f"callback 已回推 {url}（HTTP {resp.status_code}）",
                },
                node="finalize",
                level="info" if resp.status_code < 400 else "warn",
            )
    except Exception as exc:
        logger.warning("callback push failed: %s", exc)
        runtime.emitter.emit(
            EventType.WARNING,
            {"code": "CALLBACK_FAILED", "message": f"callback 回推失败：{exc}"},
            node="finalize",
            level="warn",
        )


@observed_node("finalize")
async def finalize(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    verdict = state.get("verdict") or {}
    cost = cost_summary(getattr(runtime, "budget", None) or state.get("budget") or {})

    await runs_repo.set_verdict(
        runtime.db,
        runtime.run_id,
        verdict,
        risk_level=verdict.get("risk_level"),
        confidence=verdict.get("confidence"),
    )
    await runs_repo.set_review_required(
        runtime.db, runtime.run_id, requires_review(verdict)
    )
    await runs_repo.set_cost(runtime.db, runtime.run_id, cost)
    await runs_repo.update_status(
        runtime.db, runtime.run_id, "succeeded", mark_finished=True, error=None
    )

    await _push_callback(runtime, state)

    # run_end 由 runner 在图完全退出后统一发射（保证它是本运行的最后一条事件）
    return {"budget": state.get("budget") or {}}
