"""业务编排：把平台会话组装成 agent 的 inline 载荷，并驱动对外接口流程。"""

from __future__ import annotations

import json
import logging
import mimetypes
from typing import Any

from app.agent_client import AgentClient, AgentError
from app.config import Settings
from app.store import Store

logger = logging.getLogger(__name__)

_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def file_ext(mime: str | None) -> str:
    return _EXT_BY_MIME.get(mime or "", ".img")


def attachment_url(settings: Settings, attachment: dict[str, Any]) -> str:
    return f"{settings.public_base_url.rstrip('/')}/files/{attachment['sha256']}{file_ext(attachment.get('mime'))}"


def build_inline(
    settings: Settings,
    conversation: dict[str, Any],
    messages: list[dict[str, Any]],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    """最近 N 条对话 + 最近 M 条消息内的图片 URL（agent 会按 URL 拉取）。

    文字窗口与图片窗口分开：客户常先发文字、后补图，或反过来；
    这里与 agent 的 5 条窗口语义保持一致，避免把很久以前的旧图带上。
    """
    recent = messages[-settings.context_window_messages :]
    image_window = messages[-settings.context_window_images :] or []
    window_ids = {m["id"] for m in image_window}
    window_start = image_window[0]["created_at"] if image_window else 0

    images: list[dict[str, Any]] = []
    for attachment in attachments:
        linked = attachment.get("message_id") in window_ids
        unbound_recent = attachment.get("message_id") is None and attachment["created_at"] >= window_start
        if linked or unbound_recent:
            # 只传 url：inline.sha256 语义是"引用 agent 自己库里的附件"，
            # 演示平台的图片保存在本地，必须由 agent 按 URL 拉取。
            images.append(
                {
                    "url": attachment_url(settings, attachment),
                    "mime": attachment.get("mime"),
                }
            )

    return {
        "messages": [
            {"role": m["role"], "text": m["content"], "ts": m["created_at"]} for m in recent
        ],
        "images": images,
        "channel": conversation.get("channel") or "demo",
    }


async def inline_for_conversation(
    store: Store, settings: Settings, conversation: dict[str, Any]
) -> dict[str, Any]:
    messages = await store.list_messages(conversation["id"])
    attachments = await store.list_attachments(conversation["id"])
    return build_inline(settings, conversation, messages, attachments)


async def check_customer_message(
    store: Store,
    agent: AgentClient,
    settings: Settings,
    conversation: dict[str, Any],
    message_id: str,
) -> dict[str, Any]:
    """对单条客户消息做触发判断（仅 /check，不启动分析），结果写回消息。

    演示剧本灌入 / 历史会话补算都走这里：规则判断零 LLM 成本，
    但每条客户消息都能在界面上看到"是否命中、命中什么"。
    """
    inline = await inline_for_conversation(store, settings, conversation)
    try:
        check = await agent.check(inline)
    except AgentError as exc:
        check = {"error": str(exc), "code": exc.code}
    await store.update_message_check(message_id, check)
    return check


async def recheck_conversation(
    store: Store,
    agent: AgentClient,
    settings: Settings,
    conversation: dict[str, Any],
    *,
    force: bool = False,
    limit: int = 10,
) -> int:
    """补齐没有判断结果的客户消息（历史种子会话）；force=true 时重算全部。

    规则更新后可用 force 刷新旧结果，返回本次补算条数。
    """
    messages = await store.list_messages(conversation["id"])
    targets = [m for m in messages if m["role"] == "customer"]
    if not force:
        targets = [m for m in targets if not m.get("check_result")]
    for message in targets[-limit:]:
        await check_customer_message(store, agent, settings, conversation, message["id"])
    return len(targets[-limit:])


# ---------------------------------------------------------------- 流程


async def post_message(
    store: Store,
    agent: AgentClient,
    settings: Settings,
    *,
    conversation_id: str,
    role: str,
    text: str,
    attachment_ids: list[str] | None = None,
) -> dict[str, Any]:
    conversation = await store.get_conversation(conversation_id)
    if conversation is None:
        raise ValueError("会话不存在")

    message = await store.add_message(conversation_id=conversation_id, role=role, content=text)
    if attachment_ids:
        await store.bind_attachments(attachment_ids, message["id"])

    check: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    if role == "customer":
        check = await check_customer_message(store, agent, settings, conversation, message["id"])
        message["check_result"] = check

        # 规则未要求确认（如种草渠道）→ 自动开始分析；要求确认时由前端弹窗确认
        if check.get("need_analysis") and not check.get("require_confirm"):
            started = await start_analysis(
                store,
                agent,
                settings,
                conversation,
                decision_id=check.get("decision_id"),
                scenario=check.get("scenario"),
                trigger_mode="auto",
            )
            analysis = started.get("analysis")

    return {"message": message, "analysis": analysis}


async def start_analysis(
    store: Store,
    agent: AgentClient,
    settings: Settings,
    conversation: dict[str, Any],
    *,
    decision_id: str | None = None,
    scenario: str | None = None,
    trigger_mode: str = "auto",
    auto_confirm: bool = True,
) -> dict[str, Any]:
    inline = await inline_for_conversation(store, settings, conversation)
    result = await agent.start_run(
        inline,
        decision_id=decision_id,
        scenario=scenario,
        trigger_mode=trigger_mode,
        auto_confirm=auto_confirm,
        external_ref={
            "source": "demo_platform",
            "conversation_id": conversation["id"],
            "customer_name": conversation.get("customer_name") or "",
        },
    )
    # 平台侧点击"开始分析"本身就是人工确认：agent 返回待确认时代为确认，
    # 避免操作员在两个界面各点一次。
    if result.get("status") == "awaiting_confirm":
        confirmed = await agent.confirm_run(result["run_id"])
        result = {**result, "status": confirmed.get("status") or "running"}

    # agent 去重：同诉求近期分析过时会返回既有运行（status 可能已 succeeded）
    existing = await store.find_analysis_by_run(conversation["id"], result["run_id"])
    if existing is not None:
        return {"analysis": existing, "agent": result, "reused": True}

    analysis = await store.create_analysis(
        conversation_id=conversation["id"],
        run_id=result["run_id"],
        decision_id=decision_id,
        scenario=result.get("scenario"),
        status=result.get("status") or "queued",
    )
    return {"analysis": analysis, "agent": result}


async def refresh_analysis(
    store: Store, agent: AgentClient, analysis: dict[str, Any]
) -> dict[str, Any]:
    """以 agent 的运行为准同步本地分析记录。"""
    try:
        run = await agent.get_run(analysis["run_id"])
    except AgentError as exc:
        return {**analysis_out(analysis), "sync_error": str(exc)}

    await store.update_analysis(
        analysis["id"],
        status=run.get("status"),
        risk_level=run.get("risk_level"),
        confidence=run.get("confidence"),
        verdict=run.get("verdict"),
        cost=run.get("cost"),
        last_error=run.get("error") or "",
    )
    merged = await store.get_analysis(analysis["id"]) or analysis
    out = analysis_out(merged)
    out["progress"] = run.get("progress") or {}
    out["error"] = run.get("error")
    return out


def analysis_out(row: dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    for field in ("verdict", "cost_json"):
        raw = data.get(field)
        if isinstance(raw, str):
            try:
                data["verdict" if field == "verdict" else "cost"] = json.loads(raw)
            except ValueError:
                data["verdict" if field == "verdict" else "cost"] = {} if field != "verdict" else None
    return data


# ---------------------------------------------------------------- 上传


async def store_image(
    store: Store,
    settings: Settings,
    *,
    conversation_id: str,
    data: bytes,
) -> dict[str, Any]:
    import hashlib
    import io

    from PIL import Image

    if not data:
        raise ValueError("空文件")
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.verify()
        with Image.open(io.BytesIO(data)) as img:
            width, height = img.size
            fmt = (img.format or "PNG").upper()
    except Exception as exc:  # noqa: BLE001 - 上传入口统一报错
        raise ValueError("不是有效的图片文件") from exc

    mime = Image.MIME.get(fmt, "image/png")
    sha = hashlib.sha256(data).hexdigest()
    ext = file_ext(mime)
    path = settings.upload_dir / f"{sha}{ext}"
    if not path.exists():
        path.write_bytes(data)

    existing = await store.find_conv_attachment(conversation_id, sha)
    if existing is not None:
        return existing

    return await store.add_attachment(
        conversation_id=conversation_id,
        sha256=sha,
        mime=mime,
        path=str(path),
        width=width,
        height=height,
        size_bytes=len(data),
    )
