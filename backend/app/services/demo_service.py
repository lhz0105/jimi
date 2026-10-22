"""演示客服平台业务逻辑：会话 / 消息 / 图片上传 / 触发判断 / 一键剧本。"""

from __future__ import annotations

import logging
import mimetypes
from typing import Any

from app.core.errors import AppError, NotFoundError
from app.db.repositories import (
    attachments as attachments_repo,
)
from app.db.repositories import (
    conversations as conversations_repo,
)
from app.db.repositories import (
    messages as messages_repo,
)
from app.db.repositories import (
    runs as runs_repo,
)
from app.deps import AppState
from app.rules.models import Decision
from app.services import demo_seed
from app.services.case_window import CaseWindow, load_window
from app.services.trigger_service import TriggerOutcome, guard_and_start

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- 会话

async def create_conversation(
    state: AppState, *, customer_name: str = "", channel: str = "demo", mode: str = "manual"
) -> dict[str, Any]:
    return await conversations_repo.create(
        state.db, customer_name=customer_name, channel=channel, mode=mode
    )


async def conversation_detail(state: AppState, conv_id: str) -> dict[str, Any]:
    conv = await conversations_repo.get(state.db, conv_id)
    if conv is None:
        raise NotFoundError(f"会话不存在: {conv_id}")
    messages = await messages_repo.list_by_conversation(state.db, conv_id)
    attachments = await attachments_repo.list_by_conversation(state.db, conv_id)
    runs = await runs_repo.list_by_conversation(state.db, conv_id)
    return {
        "conversation": conv,
        "messages": messages,
        "attachments": [_attachment_out(state, a) for a in attachments],
        "runs": [
            {
                "run_id": r["id"],
                "status": r["status"],
                "scenario": r["scenario"],
                "trigger_mode": r["trigger_mode"],
                "risk_level": r["risk_level"],
                "confidence": r["confidence"],
                "created_at": r["created_at"],
            }
            for r in runs
        ],
    }


# ---------------------------------------------------------------- 图片

def _attachment_out(state: AppState, att: dict[str, Any]) -> dict[str, Any]:
    name = f"image{suffix_for_mime(att.get('mime'))}"
    return {
        **att,
        "url": f"/files/{att['sha256']}/{name}",
    }


def suffix_for_mime(mime: str | None) -> str:
    ext = mimetypes.guess_extension(mime or "") or ".img"
    return ".jpg" if ext == ".jpe" else ext


async def store_image(
    state: AppState, conv_id: str, data: bytes, *, message_id: str | None = None
) -> tuple[dict[str, Any], bool]:
    """落盘（按 sha256 去重）+ 附件记录。返回 (attachment, deduplicated)。"""
    from app.core.files import sha256_bytes, sniff_image

    if not data:
        raise AppError("空文件", detail={"hint": "上传内容为空"})
    try:
        mime, width, height = sniff_image(data)
    except Exception as exc:
        raise AppError("不是有效的图片文件") from exc

    sha = sha256_bytes(data)
    sub = state.settings.upload_dir / sha[:2]
    sub.mkdir(parents=True, exist_ok=True)
    path = sub / f"{sha}{suffix_for_mime(mime)}"
    if not path.exists():
        path.write_bytes(data)

    existing = await attachments_repo.find_by_conv_sha(state.db, conv_id, sha)
    if existing is not None:
        return existing, True

    att = await attachments_repo.add(
        state.db,
        conversation_id=conv_id,
        sha256=sha,
        mime=mime,
        path=str(path),
        width=width,
        height=height,
        size_bytes=len(data),
        message_id=message_id,
    )
    return att, False


# ---------------------------------------------------------------- 消息与触发判断

async def check_conversation(
    state: AppState, conv_id: str, *, window: int | None = None
) -> tuple[Decision, CaseWindow]:
    """窗口化触发判断：最近 N 条消息的文本（关键词 + 语义）+ 该窗口内的图片。

    两步式（对应"图与文分开发送"）：
      1) 先看文本窗口是否表达诉求（退款/破损/医疗/种草…）；
      2) 再在同一个窗口里找图片作为证据（图片本身不产生意图，靠窗口文本提供上下文）。
    """
    conv = await conversations_repo.get(state.db, conv_id)
    if conv is None:
        raise NotFoundError(f"会话不存在: {conv_id}")
    size = window or state.settings.trigger_window_messages
    case_window = await load_window(state.db, conv_id, window=size)
    decision = state.rules.decide(  # type: ignore[union-attr]
        text=case_window.text,
        image_count=case_window.image_count,
        channel=conv["channel"],
        semantic_text=case_window.customer_text,
    )
    return decision, case_window


def decision_to_hint(
    state: AppState,
    decision: Decision,
    case_window: CaseWindow,
    *,
    run_id: str | None,
    trigger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fingerprint = {**case_window.snapshot_fields(), "text_digest": case_window.text[-200:]}
    decision_id = ""
    if state.extra.get("decision_cache") is not None:
        decision_id = state.extra["decision_cache"].put(decision, fingerprint)
    prompt_text = ""
    if decision.need_analysis and decision.require_confirm and run_id is None:
        prompt_text = f"检测到疑似「{decision.scenario}」场景，是否开始分析？"
    return {
        "need_analysis": decision.need_analysis,
        "scenario": decision.scenario,
        "risk_hint": decision.risk_hint,
        "require_confirm": decision.require_confirm,
        "matched_rules": [m.model_dump() for m in decision.matched_rules],
        "reason": decision.reason,
        "decision_id": decision_id,
        "run_id": run_id,
        "prompt_text": prompt_text,
        # 窗口与语义观测
        "window_size": len(case_window.messages),
        "image_count": case_window.image_count,
        "semantic_status": decision.semantic_status,
        "semantic_hits": decision.semantic_hits,
        "semantic_levels": decision.semantic_levels,
        # 触发去重观测：新建 / 复用现有运行 / 跳过
        "trigger": trigger,
    }


async def maybe_start_run(
    state: AppState,
    *,
    conv_id: str,
    decision: Decision,
    case_window: CaseWindow,
    trigger_mode: str,
    auto_confirm: bool,
    force: bool = False,
) -> TriggerOutcome | None:
    """去重后按自动链建 run（可复用进行中的运行、或跳过重复诉求）。"""
    if state.runner is None or not decision.need_analysis or not decision.scenario:
        return None
    return await guard_and_start(
        state,
        conversation_id=conv_id,
        decision=decision,
        window=case_window,
        trigger_mode=trigger_mode,
        auto_confirm=auto_confirm,
        force=force,
        input_snapshot=case_window.snapshot_fields(),
    )


async def post_message(
    state: AppState, conv_id: str, *, role: str, text: str, attachment_ids: list[str]
) -> dict[str, Any]:
    conv = await conversations_repo.get(state.db, conv_id)
    if conv is None:
        raise NotFoundError(f"会话不存在: {conv_id}")

    message = await messages_repo.add(
        state.db, conversation_id=conv_id, role=role, content=text
    )
    if attachment_ids:
        await attachments_repo.bind_message(state.db, attachment_ids, message["id"])

    analysis = None
    if role == "customer":
        decision, case_window = await check_conversation(state, conv_id)
        run_id: str | None = None
        trigger: dict[str, Any] | None = None
        # 自动执行链：会话开启 auto 模式时自动建 run（require_confirm → 等待前端确认）；
        # 去重：同一证据指纹不重复建 run，进行中的运行直接复用
        if conv["mode"] == "auto" and decision.need_analysis:
            outcome = await maybe_start_run(
                state,
                conv_id=conv_id,
                decision=decision,
                case_window=case_window,
                trigger_mode="auto",
                auto_confirm=not decision.require_confirm,
            )
            if outcome is not None:
                run_id = outcome.run_id
                trigger = outcome.to_hint()
        analysis = decision_to_hint(
            state, decision, case_window, run_id=run_id, trigger=trigger
        )
    return {"message": message, "analysis": analysis}


# ---------------------------------------------------------------- 一键剧本

async def seed_into_conversation(state: AppState, conv_id: str, scenario: str) -> dict[str, Any]:
    conv = await conversations_repo.get(state.db, conv_id)
    if conv is None:
        raise NotFoundError(f"会话不存在: {conv_id}")
    try:
        script = demo_seed.get_scenario(scenario)
    except KeyError as exc:
        raise AppError(f"未知演示剧本: {scenario}") from exc

    messages_created = 0
    attachments_created = 0
    for role, text, image_factory in script["messages"]:
        msg = await messages_repo.add(
            state.db, conversation_id=conv_id, role=role, content=text
        )
        messages_created += 1
        if image_factory is not None:
            data = image_factory()
            _att, dedup = await store_image(state, conv_id, data, message_id=msg["id"])
            if not dedup:
                attachments_created += 1

    # 剧本灌入不触发分析（避免启动即产生 LLM 成本），仅返回规则判断提示
    decision, case_window = await check_conversation(state, conv_id)
    hint = decision_to_hint(state, decision, case_window, run_id=None)
    return {
        "conversation_id": conv_id,
        "scenario": scenario,
        "messages_created": messages_created,
        "attachments_created": attachments_created,
        "hint": hint,
    }


async def seed_new_conversation(state: AppState, scenario: str) -> dict[str, Any]:
    try:
        script = demo_seed.get_scenario(scenario)
    except KeyError as exc:
        raise AppError(f"未知演示剧本: {scenario}") from exc
    conv = await create_conversation(
        state,
        customer_name=script["customer_name"],
        channel=script["channel"],
        mode="manual",
    )
    result = await seed_into_conversation(state, conv["id"], scenario)
    result["conversation_id"] = conv["id"]
    return result


async def seed_all_on_startup(state: AppState) -> list[str]:
    created: list[str] = []
    for scenario in demo_seed.SCENARIO_NAMES:
        existing = await state.db.fetchval(
            "SELECT COUNT(*) FROM conversations WHERE meta LIKE ?",
            (f'%"seed":"{scenario}"%',),
        )
        if existing:
            continue
        result = await seed_new_conversation(state, scenario)
        await state.db.execute(
            "UPDATE conversations SET meta = ? WHERE id = ?",
            (f'{{"seed":"{scenario}"}}', result["conversation_id"]),
        )
        created.append(result["conversation_id"])
    return created
