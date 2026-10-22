"""演示平台 API：会话 / 消息 / 图片 / 分析（对接 agent 对外接口）。"""

from __future__ import annotations

import logging
import re

import orjson
from typing import Any

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app import seed as seed_module
from app import service
from app.agent_client import AgentError
from app.config import Settings
from app.store import Store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

_SHA_FILE_RE = re.compile(r"^([0-9a-f]{64})(\.(png|jpg|webp|gif|img))$")
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


# ---------------------------------------------------------------- schemas


class CreateConversationRequest(BaseModel):
    customer_name: str = ""
    channel: str = "demo"


class PostMessageRequest(BaseModel):
    role: str = "customer"
    text: str = ""
    attachment_ids: list[str] = Field(default_factory=list)


class StartAnalysisRequest(BaseModel):
    decision_id: str | None = None
    scenario: str | None = None
    auto_confirm: bool = True


# ---------------------------------------------------------------- helpers


def _store(request: Request) -> Store:
    return request.app.state.store


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _agent(request: Request):
    return request.app.state.agent


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _attachment_out(settings: Settings, attachment: dict[str, Any]) -> dict[str, Any]:
    return {
        **attachment,
        "url": service.attachment_url(settings, attachment),
    }


# ---------------------------------------------------------------- 会话


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    agent_ok = True
    agent_error: str | None = None
    try:
        await _agent(request).get_run("__probe__")
    except AgentError as exc:
        # 404 说明 agent 可达（探针用的运行不存在是预期）
        if exc.status != 404:
            agent_ok = False
            agent_error = str(exc)
    return {
        "status": "ok",
        "agent": {"ok": agent_ok, "base_url": settings.agent_base_url, "error": agent_error},
    }


@router.post("/conversations")
async def create_conversation(req: CreateConversationRequest, request: Request) -> dict[str, Any]:
    conv = await _store(request).create_conversation(
        customer_name=req.customer_name or "新客户", channel=req.channel
    )
    return conv


@router.get("/conversations")
async def list_conversations(request: Request) -> list[dict[str, Any]]:
    store = _store(request)
    settings = _settings(request)
    conversations = await store.list_conversations()
    for conv in conversations:
        analyses = await store.list_analyses(conv["id"])
        attachments = await store.list_attachments(conv["id"])
        latest = analyses[0] if analyses else None
        conv["latest_analysis"] = (
            {
                "id": latest["id"],
                "run_id": latest["run_id"],
                "status": latest["status"],
                "risk_level": latest["risk_level"],
                "scenario": latest["scenario"],
            }
            if latest
            else None
        )
        conv["image_count"] = len(attachments)
        conv["attachments"] = [_attachment_out(settings, a) for a in attachments[:1]]
    return conversations


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, request: Request) -> Any:
    store = _store(request)
    settings = _settings(request)
    conv = await store.get_conversation(conv_id)
    if conv is None:
        return _error(404, "NOT_FOUND", "会话不存在")
    messages = await store.list_messages(conv_id)
    attachments = await store.list_attachments(conv_id)
    analyses = await store.list_analyses(conv_id)
    return {
        "conversation": conv,
        "messages": messages,
        "attachments": [_attachment_out(settings, a) for a in attachments],
        "analyses": [service.analysis_out(a) for a in analyses],
    }


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, request: Request) -> Any:
    store = _store(request)
    conv = await store.get_conversation(conv_id)
    if conv is None:
        return _error(404, "NOT_FOUND", "会话不存在")
    await store.delete_conversation(conv_id)
    return {"ok": True, "conversation_id": conv_id}


# ---------------------------------------------------------------- 消息 / 图片


@router.post("/conversations/{conv_id}/messages")
async def post_message(conv_id: str, req: PostMessageRequest, request: Request) -> Any:
    try:
        result = await service.post_message(
            _store(request),
            _agent(request),
            _settings(request),
            conversation_id=conv_id,
            role=req.role,
            text=req.text,
            attachment_ids=req.attachment_ids,
        )
    except ValueError as exc:
        return _error(404, "NOT_FOUND", str(exc))
    except AgentError as exc:
        return _error(502, exc.code, str(exc))
    return result


@router.post("/conversations/{conv_id}/upload")
async def upload(conv_id: str, request: Request, file: UploadFile = File(...)) -> Any:
    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        return _error(413, "PAYLOAD_TOO_LARGE", "图片超过 15MB")
    try:
        attachment = await service.store_image(
            _store(request), _settings(request), conversation_id=conv_id, data=data
        )
    except ValueError as exc:
        return _error(400, "INVALID_IMAGE", str(exc))
    return _attachment_out(_settings(request), attachment)


# ---------------------------------------------------------------- 分析


@router.post("/conversations/{conv_id}/analyze")
async def analyze(conv_id: str, req: StartAnalysisRequest, request: Request) -> Any:
    store = _store(request)
    conv = await store.get_conversation(conv_id)
    if conv is None:
        return _error(404, "NOT_FOUND", "会话不存在")
    try:
        result = await service.start_analysis(
            store,
            _agent(request),
            _settings(request),
            conv,
            decision_id=req.decision_id,
            scenario=req.scenario,
            trigger_mode="auto",
            auto_confirm=req.auto_confirm,
        )
    except AgentError as exc:
        return _error(502, exc.code, str(exc))
    return {**result, "analysis": service.analysis_out(result["analysis"])}


@router.get("/analyses/{analysis_id}")
async def get_analysis(analysis_id: str, request: Request) -> Any:
    store = _store(request)
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        return _error(404, "NOT_FOUND", "分析记录不存在")
    return await service.refresh_analysis(store, _agent(request), analysis)


@router.post("/analyses/{analysis_id}/confirm")
async def confirm_analysis(analysis_id: str, request: Request) -> Any:
    store = _store(request)
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        return _error(404, "NOT_FOUND", "分析记录不存在")
    try:
        await _agent(request).confirm_run(analysis["run_id"])
    except AgentError as exc:
        return _error(502, exc.code, str(exc))
    return await service.refresh_analysis(store, _agent(request), analysis)


@router.post("/analyses/{analysis_id}/cancel")
async def cancel_analysis(analysis_id: str, request: Request) -> Any:
    store = _store(request)
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        return _error(404, "NOT_FOUND", "分析记录不存在")
    try:
        await _agent(request).cancel_run(analysis["run_id"])
    except AgentError as exc:
        return _error(502, exc.code, str(exc))
    return await service.refresh_analysis(store, _agent(request), analysis)


@router.get("/analyses/{analysis_id}/report")
async def get_report(analysis_id: str, request: Request, format: str = "json") -> Any:
    store = _store(request)
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        return _error(404, "NOT_FOUND", "分析记录不存在")
    try:
        report = await _agent(request).get_report(analysis["run_id"], format)
    except AgentError as exc:
        return _error(exc.status or 502, exc.code, str(exc))
    if format == "markdown":
        return PlainTextResponse(str(report), media_type="text/markdown; charset=utf-8")
    return Response(content=orjson.dumps(report), media_type="application/json")


@router.get("/analyses/{analysis_id}/stream")
async def stream_analysis(analysis_id: str, request: Request, from_seq: int = 0) -> Any:
    store = _store(request)
    analysis = await store.get_analysis(analysis_id)
    if analysis is None:
        return _error(404, "NOT_FOUND", "分析记录不存在")
    last_event_id = request.headers.get("Last-Event-ID")
    return StreamingResponse(
        _agent(request).stream_run(
            analysis["run_id"], from_seq=from_seq, last_event_id=last_event_id
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------- 演示剧本


async def _seed_conversation(
    store: Store,
    settings: Settings,
    agent: Any,
    conv: dict[str, Any],
    scenario: str,
) -> dict[str, Any]:
    script = seed_module.get_scenario(scenario)
    created = 0
    for role, text, image_factory in script["messages"]:
        message = await store.add_message(conversation_id=conv["id"], role=role, content=text)
        if image_factory is not None:
            attachment = await service.store_image(
                store, settings, conversation_id=conv["id"], data=image_factory()
            )
            await store.bind_attachments([attachment["id"]], message["id"])
            created += 1
        # 每条客户消息都走一次触发判断（/check，零 LLM 成本；不自动启动分析）
        if role == "customer":
            await service.check_customer_message(store, agent, settings, conv, message["id"])
    return {"conversation_id": conv["id"], "scenario": scenario, "images": created}


@router.post("/conversations/{conv_id}/seed/{scenario}")
async def seed_existing(conv_id: str, scenario: str, request: Request) -> Any:
    store = _store(request)
    conv = await store.get_conversation(conv_id)
    if conv is None:
        return _error(404, "NOT_FOUND", "会话不存在")
    try:
        return await _seed_conversation(store, _settings(request), _agent(request), conv, scenario)
    except KeyError:
        return _error(400, "UNKNOWN_SCENARIO", f"未知剧本：{scenario}")


@router.post("/conversations/{conv_id}/recheck")
async def recheck_conversation(conv_id: str, request: Request, force: bool = False) -> Any:
    """补齐历史消息的触发判断（旧版本灌入的剧本没有 check_result）；force=true 全量重算。"""
    store = _store(request)
    conv = await store.get_conversation(conv_id)
    if conv is None:
        return _error(404, "NOT_FOUND", "会话不存在")
    checked = await service.recheck_conversation(
        store, _agent(request), _settings(request), conv, force=force
    )
    return {"conversation_id": conv_id, "checked": checked}


@router.post("/demo/seed/{scenario}")
async def seed_new(scenario: str, request: Request) -> Any:
    store = _store(request)
    try:
        script = seed_module.get_scenario(scenario)
    except KeyError:
        return _error(400, "UNKNOWN_SCENARIO", f"未知剧本：{scenario}")
    conv = await store.create_conversation(
        customer_name=script["customer_name"], channel=script["channel"]
    )
    result = await _seed_conversation(store, _settings(request), _agent(request), conv, scenario)
    return {**result, "conversation": conv}


# ---------------------------------------------------------------- 静态图片


def files_router() -> APIRouter:
    files = APIRouter()

    @files.get("/files/{filename}")
    async def serve_file(filename: str, request: Request) -> Any:
        match = _SHA_FILE_RE.match(filename)
        if not match:
            return _error(400, "INVALID_FILE", "非法的文件标识")
        settings = _settings(request)
        path = settings.upload_dir / filename
        if not path.exists():
            return _error(404, "NOT_FOUND", "文件不存在")
        return FileResponse(path)

    return files
