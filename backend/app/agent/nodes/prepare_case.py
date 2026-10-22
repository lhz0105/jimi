"""prepare_case：组装 CaseBundle、初始化预算与循环计数。无 LLM 调用。"""

from __future__ import annotations

from typing import Any

from app.agent.budget import new_budget
from app.agent.context import build_case_bundle
from app.observability.decorators import observed_node
from app.observability.events import EventType


@observed_node("prepare_case")
async def prepare_case(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    inputs = state.get("_inputs") or {}

    snapshot = inputs.get("snapshot") or {}
    case = await build_case_bundle(
        runtime,
        conversation_id=inputs.get("conversation_id"),
        inline=inputs.get("inline"),
        rule_decision=state.get("rule_decision"),
        # 触发窗口内选定的图片（图与文分开发送时由窗口对齐）；缺省则回退为全部附件
        image_attachment_ids=snapshot.get("image_attachment_ids"),
    )
    runtime.case = case
    runtime.case["scenario"] = state.get("scenario") or "generic"

    budget = state.get("budget") or new_budget(runtime.settings)

    images = case.get("images") or []
    runtime.emitter.emit(
        EventType.RUN_START,
        {
            "conversation_id": case.get("conversation_id"),
            "image_count": len(images),
            "image_sha256s": [img["sha256"][:12] for img in images],
            "message_count": len(case.get("messages") or []),
            "digest_chars": len(case.get("digest_text") or ""),
            "rules_decision": state.get("rule_decision") or {},
        },
    )

    # 回写输入快照（图片清单等），供管理面板与报告引用
    try:
        from app.db.repositories import runs as runs_repo

        snapshot = dict(inputs.get("snapshot") or {})
        snapshot.update(
            {
                "message_count": len(case.get("messages") or []),
                "image_count": len(images),
                "image_sha256s": [img["sha256"][:12] for img in images],
            }
        )
        await runs_repo.update_input_snapshot(runtime.db, runtime.run_id, snapshot)
    except Exception:  # pragma: no cover - 非关键路径
        pass

    return {
        "case": case,
        "budget": budget,
        "loop_count": 0,
        "evidence": [],
        "image_findings": {},
        "rag_hits": [],
        "steps": [],
        "warnings": [],
        "errors": [],
        "open_questions": [],
    }
