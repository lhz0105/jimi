"""管理面板接口（/api/admin）：运行观测、事件流、知识库与规则管理。"""

from __future__ import annotations

from typing import Any

import orjson
from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import PlainTextResponse
from sse_starlette.sse import EventSourceResponse

from app.api.stream import resolve_from_seq, run_event_stream
from app.core.clock import now_ms
from app.core.errors import AppError, NotFoundError, ServiceUnavailableError
from app.db.repositories import (
    confirmations as confirmations_repo,
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
from app.db.repositories import (
    tool_calls as tool_calls_repo,
)
from app.deps import AppState, get_state, require_admin

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/health")
async def health(state: AppState = Depends(get_state)) -> dict:
    db_ok = False
    db_error: str | None = None
    try:
        await state.db.fetchval("SELECT 1")
        db_ok = True
    except Exception as exc:  # pragma: no cover - 健康检查需容忍失败
        db_error = str(exc)

    rules_version = None
    semantic_mode = "uninitialized"
    semantic_threshold = None
    kb_version = None
    rag_mode = "uninitialized"
    if state.rules is not None:
        rules_version = state.rules.version
        semantic_mode = state.rules.semantic_mode
        semantic_threshold = state.rules.ruleset.semantic.threshold
    if state.kb is not None:
        kb_version = state.kb.kb_version
        rag_mode = state.kb.rag_mode

    return {
        "status": "ok" if db_ok else "degraded",
        "uptime_s": int((now_ms() - state.started_at) / 1000),
        "db": {"ok": db_ok, "error": db_error},
        "rag": {"mode": rag_mode, "kb_version": kb_version},
        "rules": {
            "version": rules_version,
            "semantic": {"mode": semantic_mode, "threshold": semantic_threshold},
        },
        "trigger": {"window_messages": state.settings.trigger_window_messages},
        "image_duplicate_check": state.settings.image_duplicate_check_enabled,
        "sse_connections": state.sse_connections,
        "llm_mode": state.settings.llm_mode,
        "runner_ready": state.runner is not None,
    }


# ---------------------------------------------------------------- 运行观测


@router.get("/runs", summary="运行列表")
async def list_runs(
    status: str | None = None,
    scenario: str | None = None,
    conversation_id: str | None = None,
    q: str | None = None,
    review: str | None = None,
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
        q=q,
        review=review,
        limit=page_size,
        offset=offset,
    )
    total = await runs_repo.count(
        state.db,
        status=status,
        scenario=scenario,
        conversation_id=conversation_id,
        q=q,
        review=review,
    )
    return {
        "items": [
            {
                "run_id": r["id"],
                "conversation_id": r["conversation_id"],
                "customer_name": r.get("customer_name"),
                "external_ref": r.get("external_ref"),
                "input_summary": ((r.get("input_snapshot") or {}).get("text_digest") or "")[-120:],
                "review_required": bool(r.get("review_required")),
                "review_status": r.get("review_status") or "none",
                "scenario": r["scenario"],
                "trigger_mode": r["trigger_mode"],
                "status": r["status"],
                "risk_level": r["risk_level"],
                "confidence": r["confidence"],
                "cost": r.get("cost_json") or {},
                "created_at": r["created_at"],
                "started_at": r.get("started_at"),
                "finished_at": r.get("finished_at"),
            }
            for r in items
        ],
        "meta": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + len(items) < total,
        },
    }


@router.get("/runs/{run_id}", summary="运行详情")
async def run_detail(run_id: str, state: AppState = Depends(get_state)) -> dict:
    run = await runs_repo.get(state.db, run_id)
    if run is None:
        raise NotFoundError(f"运行不存在: {run_id}")
    confirmations = await confirmations_repo.list_by_run(state.db, run_id)
    event_counts = await events_repo.type_counts(state.db, run_id)
    tool_calls = await tool_calls_repo.list_by_run(state.db, run_id)
    report = await reports_repo.get_by_run(state.db, run_id)
    return {
        "run": run,
        "rules_decision": run.get("rules_decision") or {},
        "input_snapshot": run.get("input_snapshot") or {},
        "confirmations": confirmations,
        "event_counts": event_counts,
        "tool_calls": [
            {
                "id": tc["id"],
                "seq": tc["seq"],
                "tool": tc["tool"],
                "args": tc["args_json"],
                "result": tc["result_json"],
                "result_ref": tc["result_ref"],
                "status": tc["status"],
                "latency_ms": tc["latency_ms"],
                "cost": tc["cost_json"],
                "created_at": tc["created_at"],
            }
            for tc in tool_calls
        ],
        "report_id": report["id"] if report else None,
    }


@router.get("/runs/{run_id}/conversation", summary="运行对话记录")
async def run_conversation(
    run_id: str, state: AppState = Depends(get_state)
) -> dict:
    run = await runs_repo.get(state.db, run_id)
    if run is None:
        raise NotFoundError(f"运行不存在: {run_id}")

    snapshot = run.get("input_snapshot") or {}
    if run.get("conversation_id"):
        rows = await state.db.fetchall(
            """SELECT seq, role, content, created_at FROM messages
               WHERE conversation_id = ? ORDER BY seq LIMIT 200""",
            (run["conversation_id"],),
        )
        messages = [
            {
                "seq": row["seq"],
                "role": row["role"],
                "content": row["content"],
                "ts": row["created_at"],
            }
            for row in rows
        ]
        source = "conversation"
        note = "来自 Agent 会话存储（最多 200 条）"
    else:
        stored = snapshot.get("messages") or []
        messages = [
            {
                "seq": index + 1,
                "role": item.get("role", "customer"),
                "content": item.get("text", ""),
                "ts": item.get("ts"),
            }
            for index, item in enumerate(stored)
        ]
        if messages:
            source = "inline"
            note = (
                f"来自外部平台会话的历史回填（最近 {len(messages)} 条）"
                if snapshot.get("messages_backfilled")
                else f"来自外部平台提交的分析窗口（最近 {len(messages)} 条）"
            )
        else:
            digest = snapshot.get("text_digest") or ""
            messages = (
                [{"seq": 1, "role": "customer", "content": digest, "ts": None}]
                if digest
                else []
            )
            source = "digest"
            note = "该运行创建于对话持久化之前，仅保留文字摘要"
    return {
        "run_id": run_id,
        "source": source,
        "note": note,
        "messages": messages,
        "message_count": len(messages),
        "image_count": snapshot.get("image_count") or 0,
    }


@router.get("/runs/{run_id}/events", summary="事件历史（分页，正序）")
async def run_events(
    run_id: str,
    since_seq: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
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


@router.get("/runs/{run_id}/stream", summary="SSE 实时事件流（支持 Last-Event-ID 续传）")
async def run_stream(
    run_id: str,
    request: Request,
    from_seq: int = Query(default=0, ge=0),
    state: AppState = Depends(get_state),
):
    run = await runs_repo.get(state.db, run_id)
    if run is None:
        raise NotFoundError(f"运行不存在: {run_id}")
    start = resolve_from_seq(request, from_seq)
    return EventSourceResponse(
        run_event_stream(state, request, run_id, start),
        ping=state.settings.sse_heartbeat_s,
    )


@router.get("/runs/{run_id}/report", summary="报告（json / markdown）")
async def run_report(
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
    if state.runner is None:
        raise ServiceUnavailableError("分析引擎未就绪")
    run = await state.runner.cancel_run(run_id)
    return {"run_id": run["id"], "status": run["status"]}


@router.get("/runs/{run_id}/tool-calls", summary="工具调用清单")
async def run_tool_calls(run_id: str, state: AppState = Depends(get_state)) -> dict:
    run = await runs_repo.get(state.db, run_id)
    if run is None:
        raise NotFoundError(f"运行不存在: {run_id}")
    items: list[dict[str, Any]] = await tool_calls_repo.list_by_run(state.db, run_id)
    return {"run_id": run_id, "items": items}


# ---------------------------------------------------------------- 规则管理


@router.get("/rules", summary="读取当前规则集")
async def get_rules(state: AppState = Depends(get_state)) -> dict:
    if state.rules is None:
        raise ServiceUnavailableError("规则引擎未就绪")
    return {
        "version": state.rules.version,
        "yaml": state.rules.raw_yaml(),
    }


@router.put("/rules", summary="整体替换规则集（校验失败返回 422 且保留旧版）")
async def put_rules(payload: dict, state: AppState = Depends(get_state)) -> dict:
    if state.rules is None:
        raise ServiceUnavailableError("规则引擎未就绪")
    yaml_text = payload.get("yaml")
    if not yaml_text or not isinstance(yaml_text, str):
        raise AppError("请求体必须包含 yaml 字段（字符串）")
    ruleset = state.rules.replace(yaml_text)
    return {"version": ruleset.version, "rules": len(ruleset.rules)}


@router.post("/rules/reload", summary="从磁盘重载规则")
async def reload_rules(state: AppState = Depends(get_state)) -> dict:
    if state.rules is None:
        raise ServiceUnavailableError("规则引擎未就绪")
    ruleset = state.rules.load()
    return {"version": ruleset.version, "rules": len(ruleset.rules)}


# ---------------------------------------------------------------- 知识库管理


@router.get("/kb/documents", summary="知识库文档列表")
async def kb_documents(state: AppState = Depends(get_state)) -> dict:
    if state.kb is None:
        raise ServiceUnavailableError("知识库未就绪")
    docs = await state.kb.list_documents()
    return {
        "items": docs,
        "stats": state.kb.statistics(),
        "kb_version": state.kb.kb_version,
        "rag_mode": state.kb.rag_mode,
    }


@router.post("/kb/documents", summary="上传/更新知识库文档（md/txt）")
async def kb_add_document(payload: dict, state: AppState = Depends(get_state)) -> dict:
    if state.kb is None:
        raise ServiceUnavailableError("知识库未就绪")
    path = payload.get("path")
    content = payload.get("content")
    if not path or not isinstance(path, str) or not isinstance(content, str):
        raise AppError("请求体必须包含 path 与 content（字符串）")
    stats = await state.kb.add_document(path, content)
    return {"ok": True, "stats": stats}


@router.delete("/kb/documents/{doc_id}", summary="删除知识库文档并重索引")
async def kb_delete_document(doc_id: str, state: AppState = Depends(get_state)) -> dict:
    if state.kb is None:
        raise ServiceUnavailableError("知识库未就绪")
    stats = await state.kb.delete_document(doc_id)
    return {"ok": True, "stats": stats}


@router.post("/kb/reindex", summary="重建索引（rebuild=true 全量重建）")
async def kb_reindex(
    rebuild: bool = Query(default=False), state: AppState = Depends(get_state)
) -> dict:
    if state.kb is None:
        raise ServiceUnavailableError("知识库未就绪")
    stats = await state.kb.reindex(rebuild=rebuild)
    return {"ok": True, "stats": stats}


@router.get("/kb/search", summary="检索调试（返回双路分数与融合分，RAG 命中观测入口）")
async def kb_search(
    q: str = Query(..., min_length=1),
    scenario: str | None = None,
    top_k: int = Query(default=4, ge=1, le=20),
    state: AppState = Depends(get_state),
) -> dict:
    if state.kb is None:
        raise ServiceUnavailableError("知识库未就绪")
    hits = await state.kb.search(q, top_k=top_k, scenario=scenario)
    return {
        "query": q,
        "rag_mode": state.kb.rag_mode,
        "kb_version": state.kb.kb_version,
        "items": hits,
    }


# ---------------------------------------------------------------- 统计与配置


@router.get("/stats", summary="聚合统计（运行数/成功率/token/成本）")
async def stats(
    days: int = Query(default=7, ge=1, le=90), state: AppState = Depends(get_state)
) -> dict:
    since = now_ms() - days * 86400_000
    rows = await state.db.fetchall(
        """SELECT status, scenario, risk_level, cost_json, created_at
             FROM analysis_runs WHERE created_at >= ? ORDER BY created_at DESC LIMIT 2000""",
        (since,),
    )
    from app.db.repositories.util import loads_json

    totals = {
        "runs": 0,
        "succeeded": 0,
        "failed": 0,
        "cancelled": 0,
        "active": 0,
        "llm_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "tool_calls": 0,
        "est_cost": 0.0,
    }
    by_scenario: dict[str, int] = {}
    by_day: dict[str, dict[str, Any]] = {}

    for row in rows:
        totals["runs"] += 1
        status = row["status"]
        if status == "succeeded":
            totals["succeeded"] += 1
        elif status == "failed":
            totals["failed"] += 1
        elif status == "cancelled":
            totals["cancelled"] += 1
        else:
            totals["active"] += 1
        by_scenario[row["scenario"]] = by_scenario.get(row["scenario"], 0) + 1
        cost = loads_json(row["cost_json"], {}) or {}
        for key in ("llm_calls", "prompt_tokens", "completion_tokens", "tool_calls"):
            totals[key] += int(cost.get(key) or 0)
        totals["est_cost"] = round(totals["est_cost"] + float(cost.get("est_cost") or 0), 6)

        from datetime import datetime

        day = datetime.fromtimestamp(row["created_at"] / 1000).strftime("%Y-%m-%d")
        entry = by_day.setdefault(day, {"runs": 0, "est_cost": 0.0})
        entry["runs"] += 1
        entry["est_cost"] = round(entry["est_cost"] + float(cost.get("est_cost") or 0), 6)

    return {
        "window_days": days,
        "totals": totals,
        "by_scenario": by_scenario,
        "by_day": dict(sorted(by_day.items())),
    }


@router.get("/config", summary="脱敏配置快照（排障用）")
async def config_snapshot(state: AppState = Depends(get_state)) -> dict:
    s = state.settings

    def mask(value: str) -> str:
        if not value:
            return ""
        if len(value) <= 6:
            return "***"
        return value[:3] + "***" + value[-3:]

    return {
        "llm_mode": s.llm_mode,
        "llm_main": {
            "base_url": s.llm_main_base_url,
            "model": s.llm_main_model,
            "api_key": mask(s.llm_main_api_key),
        },
        "llm_vision": {
            "base_url": s.llm_vision_base_url,
            "model": s.llm_vision_model,
            "api_key": mask(s.llm_vision_api_key),
        },
        "tavily_api_key": mask(s.tavily_api_key),
        "rag": {
            "embedding_model": s.embedding_model,
            "top_k": s.rag_top_k,
            "mode": state.kb.rag_mode if state.kb else "uninitialized",
        },
        "budget": {
            "max_llm_calls": s.budget_max_llm_calls,
            "max_tool_calls": s.budget_max_tool_calls,
            "max_vision_calls": s.budget_max_vision_calls,
            "max_tavily_calls": s.budget_max_tavily_calls,
            "max_run_cost": s.budget_max_run_cost,
            "max_investigate_loops": s.max_investigate_loops,
        },
        "paths": {
            "data_dir": str(s.data_dir),
            "db_path": str(s.db_path),
            "workspace_dir": str(s.workspace_dir),
            "report_dir": str(s.report_dir),
        },
    }
