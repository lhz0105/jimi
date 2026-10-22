"""管理面板：人工判决对话与先前案例库。"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from app.core.errors import AppError, NotFoundError, ServiceUnavailableError
from app.db.repositories import prior_cases as prior_cases_repo
from app.deps import AppState, get_state, require_admin
from app.services.review_service import ReviewService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/admin", tags=["admin-reviews"], dependencies=[Depends(require_admin)]
)


class StartReviewRequest(BaseModel):
    verdict: Literal["fraud", "genuine", "insufficient"]
    reason: str = Field(min_length=1, max_length=4000)
    reviewer: str = Field(default="人工复核员", max_length=80)


class ReviewMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ReviewStreamRequest(BaseModel):
    action: Literal["start", "answer", "generate"]
    verdict: Literal["fraud", "genuine", "insufficient"] | None = None
    reason: str | None = Field(default=None, max_length=4000)
    reviewer: str | None = Field(default=None, max_length=80)
    content: str | None = Field(default=None, max_length=2000)


@router.get("/runs/{run_id}/review", summary="人工复核状态")
async def get_review(run_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    return await ReviewService(state).snapshot(run_id)


@router.post("/runs/{run_id}/review", summary="提交人工判决并启动追问")
async def start_review(
    run_id: str, req: StartReviewRequest, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    return await ReviewService(state).start(
        run_id, verdict=req.verdict, reason=req.reason, reviewer=req.reviewer
    )


@router.post("/runs/{run_id}/review/messages", summary="人工回复并触发 Agent 追问")
async def post_review_message(
    run_id: str, req: ReviewMessageRequest, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    return await ReviewService(state).add_message(run_id, req.content)


@router.post("/runs/{run_id}/review/generate", summary="强制生成先前案例")
async def generate_prior_case(
    run_id: str, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    return await ReviewService(state).generate(run_id)


@router.post("/runs/{run_id}/review/stream", summary="人工复核流式输出（SSE）")
async def stream_review(
    run_id: str, req: ReviewStreamRequest, state: AppState = Depends(get_state)
) -> EventSourceResponse:
    service = ReviewService(state)
    if req.action == "start":
        if not req.verdict or not (req.reason or "").strip():
            raise AppError("提交判决需要 verdict 与 reason")
        events = service.stream_start(
            run_id,
            verdict=req.verdict,
            reason=req.reason,
            reviewer=req.reviewer or "",
        )
    elif req.action == "answer":
        if not (req.content or "").strip():
            raise AppError("回复内容不能为空")
        events = service.stream_answer(run_id, req.content)
    else:
        events = service.stream_generate(run_id)

    async def event_generator():
        try:
            async for event in events:
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"], ensure_ascii=False),
                }
        except Exception as exc:
            logger.exception("review stream failed")
            yield {
                "event": "error",
                "data": json.dumps({"message": str(exc)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator(), ping=15)


@router.get("/prior-cases", summary="先前案例列表")
async def list_prior_cases(
    scenario: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    state: AppState = Depends(get_state),
) -> dict[str, Any]:
    offset = (page - 1) * page_size
    items = await prior_cases_repo.list_page(
        state.db, scenario=scenario, limit=page_size, offset=offset
    )
    total = await prior_cases_repo.count(state.db, scenario=scenario)
    return {
        "items": items,
        "meta": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + len(items) < total,
        },
    }


@router.get("/prior-cases/{case_id}", summary="先前案例详情")
async def get_prior_case(case_id: str, state: AppState = Depends(get_state)) -> dict[str, Any]:
    case = await prior_cases_repo.get(state.db, case_id)
    if case is None:
        raise NotFoundError(f"先前案例不存在: {case_id}")
    return case


@router.delete("/prior-cases/{case_id}", summary="删除先前案例")
async def delete_prior_case(
    case_id: str, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    deleted = await prior_cases_repo.delete(state.db, case_id)
    if deleted is None:
        raise NotFoundError(f"先前案例不存在: {case_id}")

    removed = 0
    service = state.extra.get("prior_case_service")
    if service is not None and getattr(service, "ready", False):
        try:
            removed = await service.delete_case(case_id)
        except Exception:  # pragma: no cover - 索引失败不阻断删除
            logger.exception("prior case index delete failed: %s", case_id)

    return {
        "ok": True,
        "case_id": case_id,
        "title": deleted["title"],
        "index_chunks_removed": removed,
        "review_reset": bool(deleted.get("review_reset")),
    }


@router.get("/prior-cases/{case_id}/feedback", summary="先前案例权重发展")
async def get_prior_case_feedback(
    case_id: str, state: AppState = Depends(get_state)
) -> dict[str, Any]:
    case = await prior_cases_repo.get(state.db, case_id)
    if case is None:
        raise NotFoundError(f"先前案例不存在: {case_id}")
    return {
        "case": case,
        "feedback": await prior_cases_repo.list_feedback(state.db, case_id),
    }


@router.post("/prior-cases/reindex", summary="重建先前案例索引")
async def reindex_prior_cases(state: AppState = Depends(get_state)) -> dict[str, Any]:
    service = state.extra.get("prior_case_service")
    if service is None:
        raise ServiceUnavailableError("先前案例索引服务未就绪")
    stats = await service.reindex()
    return {"ok": True, "stats": stats}
