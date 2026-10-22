"""演示客服平台接口（/api/demo）与图片静态服务（/files）。"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse

from app.api.schemas.demo import (
    CreateConversationRequest,
    PostMessageRequest,
    SeedResponse,
    TriggerAnalysisRequest,
    UploadResponse,
)
from app.core.errors import AppError, NotFoundError, PayloadTooLarge, ServiceUnavailableError
from app.db.repositories import attachments as attachments_repo
from app.deps import AppState, get_state, require_external
from app.services import demo_service
from app.services.trigger_service import guard_and_start

router = APIRouter(
    prefix="/api/demo", tags=["demo"], dependencies=[Depends(require_external)]
)
files_router = APIRouter(tags=["files"], dependencies=[Depends(require_external)])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@router.post("/conversations", summary="创建演示会话")
async def create_conversation(
    req: CreateConversationRequest, state: AppState = Depends(get_state)
) -> dict:
    conv = await demo_service.create_conversation(
        state, customer_name=req.customer_name, channel=req.channel, mode=req.mode
    )
    return conv


@router.get("/conversations", summary="会话列表（含最新消息与最近运行状态）")
async def list_conversations(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    state: AppState = Depends(get_state),
) -> dict:
    from app.db.repositories import conversations as conversations_repo

    offset = (page - 1) * page_size
    items = await conversations_repo.list_page(state.db, limit=page_size, offset=offset)
    total = await conversations_repo.count(state.db)
    return {
        "items": items,
        "meta": {
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + len(items) < total,
        },
    }


@router.get("/conversations/{conv_id}", summary="会话详情（消息/附件/运行）")
async def get_conversation(conv_id: str, state: AppState = Depends(get_state)) -> dict:
    return await demo_service.conversation_detail(state, conv_id)


@router.post("/conversations/{conv_id}/messages", summary="发送消息（客户消息自动触发规则判断）")
async def post_message(
    conv_id: str, req: PostMessageRequest, state: AppState = Depends(get_state)
) -> dict:
    return await demo_service.post_message(
        state, conv_id, role=req.role, text=req.text, attachment_ids=req.attachment_ids
    )


@router.post(
    "/conversations/{conv_id}/upload",
    response_model=UploadResponse,
    summary="上传图片（按 sha256 去重存储）",
)
async def upload_image(
    conv_id: str, file: UploadFile = File(...), state: AppState = Depends(get_state)
) -> UploadResponse:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise PayloadTooLarge(f"图片超过大小上限 {MAX_UPLOAD_BYTES // 1024 // 1024}MB")
    att, dedup = await demo_service.store_image(state, conv_id, data)
    return UploadResponse(
        attachment_id=att["id"],
        sha256=att["sha256"],
        mime=att["mime"],
        width=att["width"],
        height=att["height"],
        bytes=att["bytes"],
        url=f"/files/{att['sha256']}/image{demo_service.suffix_for_mime(att['mime'])}",
        deduplicated=dedup,
    )


@router.post("/conversations/{conv_id}/trigger-analysis", summary="人工启动分析（手动执行链）")
async def trigger_analysis(
    conv_id: str, req: TriggerAnalysisRequest, state: AppState = Depends(get_state)
) -> dict:
    if state.runner is None:
        raise ServiceUnavailableError("分析引擎未就绪")
    decision, case_window = await demo_service.check_conversation(state, conv_id)
    scenario = req.scenario or decision.scenario
    if not scenario:
        # 客户诉求可能已滑出窗口（例如先投诉、之后只在追问）：回退到该会话最近一次运行的场景
        from app.db.repositories import runs as runs_repo

        previous = await runs_repo.list_by_conversation(state.db, conv_id)
        scenario = previous[0]["scenario"] if previous else None
    if not scenario:
        raise AppError("无法确定分析场景：窗口内无命中且该会话没有历史运行，请显式指定 scenario")

    # 人工启动为显式请求：跳过"证据指纹"去重，但仍不并发（有进行中的运行则复用）
    decision.need_analysis = True
    decision.scenario = scenario
    outcome = await guard_and_start(
        state,
        conversation_id=conv_id,
        decision=decision,
        window=case_window,
        trigger_mode="manual",
        auto_confirm=req.auto_confirm,
        force=True,
        input_snapshot={"manual": True, **case_window.snapshot_fields()},
    )
    run = outcome.run or {}
    return {
        "run_id": run.get("id"),
        "status": run.get("status"),
        "scenario": run.get("scenario", scenario),
        "confirm_required": run.get("status") == "awaiting_confirm",
        "trigger": outcome.to_hint(),
    }


@router.post(
    "/conversations/{conv_id}/seed",
    response_model=SeedResponse,
    summary="向会话灌入内置演示剧本（不触发分析）",
)
async def seed_conversation(
    conv_id: str,
    scenario: str = Query(..., pattern="^(product_damage_claim|medical_cert_claim|seeding_post)$"),
    state: AppState = Depends(get_state),
) -> SeedResponse:
    result = await demo_service.seed_into_conversation(state, conv_id, scenario)
    return SeedResponse(**result)


@router.post(
    "/seed/{scenario}",
    response_model=SeedResponse,
    summary="一键新建会话并灌入剧本",
)
async def seed_new(
    scenario: str,
    state: AppState = Depends(get_state),
) -> SeedResponse:
    result = await demo_service.seed_new_conversation(state, scenario)
    return SeedResponse(**result)


@router.post("/runs/{run_id}/confirm", summary="确认开始分析（自动链第二步）")
async def confirm_run(run_id: str, state: AppState = Depends(get_state)) -> dict:
    if state.runner is None:
        raise ServiceUnavailableError("分析引擎未就绪")
    run = await state.runner.confirm_run(run_id, decided_by="demo")
    return {"run_id": run["id"], "status": run["status"], "scenario": run["scenario"]}


@files_router.get("/files/{sha256}/{name}", summary="图片文件服务")
async def serve_file(sha256: str, name: str, state: AppState = Depends(get_state)):
    if not _SHA_RE.match(sha256):
        raise AppError("非法的文件标识")
    atts = await attachments_repo.list_by_sha(state.db, sha256)
    if not atts:
        raise NotFoundError("文件不存在")
    att = atts[0]
    return FileResponse(att["path"], media_type=att["mime"], filename=name)
