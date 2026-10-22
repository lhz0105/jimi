"""对外分析接口（/api/v1/analyze）：供外部客服平台接入。"""

from __future__ import annotations

from typing import Any

import orjson
from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.api.schemas.analyze import (
    CheckRequest,
    CheckResponse,
    MatchedRuleOut,
    RunStartedResponse,
    RunStatusResponse,
    StartRunRequest,
)
from app.core.errors import AppError, NotFoundError, ServiceUnavailableError
from app.db.repositories import (
    conversations as conversations_repo,
)
from app.db.repositories import (
    events as events_repo,
)
from app.db.repositories import (
    reports as reports_repo,
)
from app.db.repositories import (
    runs as runs_repo,
)
from app.deps import AppState, get_state, require_external
from app.services.case_window import load_window
from app.services.trigger_service import guard_and_start

router = APIRouter(
    prefix="/api/v1/analyze", tags=["analyze"], dependencies=[Depends(require_external)]
)


def _require_runner(state: AppState) -> Any:
    if state.runner is None:
        raise ServiceUnavailableError("分析引擎未就绪")
    return state.runner


async def _resolve_inputs(state: AppState, req: CheckRequest | StartRunRequest) -> dict[str, Any]:
    """统一成 {text, image_count, channel, conversation_id, window}。

    会话输入取"最近 N 条消息窗口"：文本用于判定意图，窗口内图片作为证据
    （客服场景图与文常分开发送，窗口保证两者能对上）。
    """
    if req.conversation_id:
        conv = await conversations_repo.get(state.db, req.conversation_id)
        if conv is None:
            raise NotFoundError(f"会话不存在: {req.conversation_id}")
        window = await load_window(
            state.db, req.conversation_id, window=state.settings.trigger_window_messages
        )
        return {
            "text": window.text,
            "semantic_text": window.customer_text,
            "image_count": window.image_count,
            "channel": conv["channel"],
            "conversation_id": req.conversation_id,
            "window": window,
        }
    if req.inline is not None:
        text = "\n".join(m.text for m in req.inline.messages if m.text)
        return {
            "text": text,
            "semantic_text": text,
            "image_count": len(req.inline.images),
            "channel": req.inline.channel,
            "conversation_id": None,
            "window": None,
        }
    raise AppError("必须提供 conversation_id 或 inline 载荷")


def _decision_response(
    state: AppState,
    decision: Any,
    fingerprint: dict[str, Any],
    inputs: dict[str, Any],
) -> CheckResponse:
    decision_id = ""
    cache = state.extra.get("decision_cache")
    if cache is not None:
        decision_id = cache.put(decision, fingerprint)
    window = inputs.get("window")
    return CheckResponse(
        need_analysis=decision.need_analysis,
        scenario=decision.scenario,
        risk_hint=decision.risk_hint,
        require_confirm=decision.require_confirm,
        matched_rules=[MatchedRuleOut(**m.model_dump()) for m in decision.matched_rules],
        reason=decision.reason,
        rules_version=decision.rules_version,
        decision_id=decision_id,
        image_count=inputs["image_count"],
        message=_hint_message(decision),
        semantic_status=decision.semantic_status,
        semantic_hits=decision.semantic_hits,
        semantic_levels=decision.semantic_levels,
        window_size=len(window.messages) if window else 0,
    )


def _hint_message(decision: Any) -> str:
    if decision.need_analysis:
        return f"建议开始分析（场景：{decision.scenario}）"
    return "无需分析"


@router.post("/check", response_model=CheckResponse, summary="触发判断（规则引擎 + 语义相似度，不调用 LLM）")
async def check(req: CheckRequest, state: AppState = Depends(get_state)) -> CheckResponse:
    inputs = await _resolve_inputs(state, req)
    decision = state.rules.decide(  # type: ignore[union-attr]
        text=inputs["text"],
        image_count=inputs["image_count"],
        channel=inputs["channel"],
        semantic_text=inputs.get("semantic_text"),
    )
    window = inputs.get("window")
    fingerprint = {
        "conversation_id": inputs["conversation_id"],
        "image_count": inputs["image_count"],
        "text_digest": inputs["text"][-200:],
        **(window.snapshot_fields() if window else {}),
    }
    return _decision_response(state, decision, fingerprint, inputs)


@router.post(
    "/runs",
    response_model=RunStartedResponse,
    status_code=202,
    summary="启动分析（自动链确认后 / 手动链直接调用）",
)
async def start_run(
    req: StartRunRequest,
    state: AppState = Depends(get_state),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> RunStartedResponse:
    runner = _require_runner(state)
    inputs = await _resolve_inputs(state, req)
    external_ref = (
        req.external_ref.model_dump(exclude_none=True) if req.external_ref else None
    )

    decision = None
    if req.decision_id:
        cache = state.extra.get("decision_cache")
        cached = cache.get(req.decision_id) if cache is not None else None
        if cached is not None:
            decision = cached.decision
    if decision is None:
        decision = state.rules.decide(  # type: ignore[union-attr]
            text=inputs["text"],
            image_count=inputs["image_count"],
            channel=inputs["channel"],
            semantic_text=inputs.get("semantic_text"),
        )

    scenario = req.scenario or decision.scenario or "generic"
    if not decision.need_analysis and not req.scenario:
        raise AppError(
            "该输入未命中分析规则；如需强制分析请显式指定 scenario",
            detail={"matched_rules": [m.model_dump() for m in decision.matched_rules]},
        )

    # 手动链：调用方已显式启动 → 直接开跑；自动链：规则要求确认时先落 awaiting_confirm
    auto_confirm = (
        True
        if req.trigger_mode == "manual"
        else (req.auto_confirm and not decision.require_confirm)
    )

    window = inputs.get("window")
    inline_messages = (
        [
            {"role": m.role, "text": m.text[:2000], "ts": m.ts}
            for m in req.inline.messages[-20:]
        ]
        if req.inline and req.inline.messages
        else []
    )
    snapshot = {
        "text_digest": inputs["text"][-500:],
        "image_count": inputs["image_count"],
        "inline": bool(req.inline),
        **({"messages": inline_messages} if inline_messages else {}),
        **(window.snapshot_fields() if window else {}),
    }

    if inputs["conversation_id"] and window is not None:
        # 会话输入走去重：自动链同指纹不重复建运行；手动链为显式请求（跳过指纹，但仍不并发）
        decision.need_analysis = True
        decision.scenario = scenario
        outcome = await guard_and_start(
            state,
            conversation_id=inputs["conversation_id"],
            decision=decision,
            window=window,
            trigger_mode=req.trigger_mode,
            auto_confirm=auto_confirm,
            force=(req.trigger_mode == "manual"),
            input_snapshot=snapshot,
            inline=req.inline,
            external_ref=external_ref,
            idempotency_key=idempotency_key,
            callback_url=req.callback_url,
        )
        run = outcome.run or {}
        messages = {
            "start": "开始分析" if run.get("status") != "awaiting_confirm" else "等待确认后开始分析",
            "reuse": "已有进行中的分析，返回该运行",
            "skip": "相同诉求近期已分析，返回最近一次运行（可用 ?force 手动重新分析）",
        }
        return RunStartedResponse(
            run_id=run.get("id", ""),
            status=run.get("status", outcome.action),
            scenario=run.get("scenario", scenario),
            confirm_required=run.get("status") == "awaiting_confirm",
            message=messages.get(outcome.action, ""),
        )

    run = await runner.start_run(
        conversation_id=None,
        scenario=scenario,
        trigger_mode=req.trigger_mode,
        auto_confirm=auto_confirm,
        inline=req.inline,
        rules_decision=decision.model_dump(),
        input_snapshot=snapshot,
        external_ref=external_ref,
        idempotency_key=idempotency_key,
        callback_url=req.callback_url,
    )
    return RunStartedResponse(
        run_id=run["id"],
        status=run["status"],
        scenario=run["scenario"],
        confirm_required=run["status"] == "awaiting_confirm",
        message="开始分析" if run["status"] != "awaiting_confirm" else "等待确认后开始分析",
    )


@router.post("/runs/{run_id}/confirm", response_model=RunStartedResponse, summary="确认开始分析")
async def confirm_run(run_id: str, state: AppState = Depends(get_state)) -> RunStartedResponse:
    runner = _require_runner(state)
    run = await runner.confirm_run(run_id, decided_by="api")
    return RunStartedResponse(
        run_id=run["id"],
        status=run["status"],
        scenario=run["scenario"],
        confirm_required=False,
        message="已确认，开始分析",
    )


@router.get("/runs/{run_id}", response_model=RunStatusResponse, summary="查询运行状态")
async def get_run(run_id: str, state: AppState = Depends(get_state)) -> RunStatusResponse:
    run = await runs_repo.get(state.db, run_id)
    if run is None:
        raise NotFoundError(f"运行不存在: {run_id}")
    return RunStatusResponse(
        run_id=run["id"],
        status=run["status"],
        scenario=run["scenario"],
        trigger_mode=run["trigger_mode"],
        progress=run.get("progress_json") or {},
        verdict=run.get("verdict"),
        risk_level=run.get("risk_level"),
        confidence=run.get("confidence"),
        cost=run.get("cost_json") or {},
        error=run.get("error"),
        created_at=run["created_at"],
        started_at=run.get("started_at"),
        finished_at=run.get("finished_at"),
    )


@router.get("/runs", summary="运行列表（分页）")
async def list_runs(
    conversation_id: str | None = None,
    status: str | None = None,
    scenario: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    state: AppState = Depends(get_state),
) -> dict:
    offset = (page - 1) * page_size
    items = await runs_repo.list_page(
        state.db,
        status=status,
        scenario=scenario,
        conversation_id=conversation_id,
        limit=page_size,
        offset=offset,
    )
    total = await runs_repo.count(
        state.db, status=status, scenario=scenario, conversation_id=conversation_id
    )
    return {
        "items": [_run_brief(r) for r in items],
        "meta": {"total": total, "page": page, "page_size": page_size, "has_more": offset + len(items) < total},
    }


def _run_brief(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": r["id"],
        "conversation_id": r["conversation_id"],
        "external_ref": r.get("external_ref"),
        "scenario": r["scenario"],
        "trigger_mode": r["trigger_mode"],
        "status": r["status"],
        "risk_level": r["risk_level"],
        "confidence": r["confidence"],
        "cost": r.get("cost_json") or {},
        "created_at": r["created_at"],
        "finished_at": r.get("finished_at"),
    }


@router.get("/runs/{run_id}/report", summary="获取报告（json / markdown）")
async def get_report(
    run_id: str,
    format: str = Query(default="json", pattern="^(json|markdown)$"),
    state: AppState = Depends(get_state),
) -> Response:
    report = await reports_repo.get_by_run(state.db, run_id)
    if report is None:
        run = await runs_repo.get(state.db, run_id)
        if run is None:
            raise NotFoundError(f"运行不存在: {run_id}")
        raise NotFoundError("报告尚未生成（运行未完成或已失败）")
    if format == "markdown":
        return PlainTextResponse(report["markdown"], media_type="text/markdown; charset=utf-8")
    return Response(content=orjson.dumps(report["json"]), media_type="application/json")


@router.post("/runs/{run_id}/cancel", summary="取消运行（幂等）")
async def cancel_run(run_id: str, state: AppState = Depends(get_state)) -> dict:
    runner = _require_runner(state)
    run = await runner.cancel_run(run_id)
    return {"run_id": run["id"], "status": run["status"]}


@router.get("/runs/{run_id}/stream", summary="SSE 实时事件流（观测输入/思考/工具调用/证据）")
async def stream_run(
    run_id: str,
    request: Request,
    from_seq: int = Query(default=0, ge=0),
    state: AppState = Depends(get_state),
):
    run = await runs_repo.get(state.db, run_id)
    if run is None:
        raise NotFoundError(f"运行不存在: {run_id}")
    from sse_starlette.sse import EventSourceResponse

    from app.api.stream import resolve_from_seq, run_event_stream

    start = resolve_from_seq(request, from_seq)
    return EventSourceResponse(
        run_event_stream(state, request, run_id, start),
        ping=state.settings.sse_heartbeat_s,
    )


@router.get("/runs/{run_id}/events", summary="事件历史（不支持长连接的平台可用轮询）")
async def get_events(
    run_id: str,
    since_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    state: AppState = Depends(get_state),
) -> dict:
    run = await runs_repo.get(state.db, run_id)
    if run is None:
        raise NotFoundError(f"运行不存在: {run_id}")
    items = await events_repo.list_after(state.db, run_id, since_seq=since_seq, limit=limit)
    return {
        "run_id": run_id,
        "items": items,
        "next_seq": items[-1]["seq"] if items else (since_seq or None),
    }
