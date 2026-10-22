"""单次 LLM 调用的统一封装：预算检查 + 回调事件 + usage 计费 + JSON 解析。"""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent import budget as budget_mod
from app.agent.prompts import load_prompt
from app.llm.fake import extract_json
from app.observability.callbacks import EmitterCallbackHandler

logger = logging.getLogger(__name__)


def message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content)


async def call_llm_json(
    runtime: Any,
    *,
    node: str,
    prompt_name: str,
    payload: str,
) -> tuple[dict[str, Any] | None, str]:
    """单次 LLM 调用（prompt_name 作为系统提示词），返回 (解析出的 JSON | None, 原始文本)。"""
    if runtime.llm_main is None:
        return None, "主模型未配置"

    reason = budget_mod.llm_allowed(runtime.budget)
    if reason:
        runtime.emitter.emit(
            "budget_warning",
            {"metric": "llm", "message": reason},
            node=node,
            level="warn",
        )
        return None, f"预算受限：{reason}"

    handler = EmitterCallbackHandler(
        runtime.emitter,
        model_name=runtime.settings.llm_main_model,
        usage_sink=lambda usage, model: budget_mod.record_llm(
            runtime.budget,
            node=node,
            usage=usage,
            prices=runtime.prices,
            role="main",
            emitter=runtime.emitter,
        ),
    )

    messages: list[Any] = [
        SystemMessage(content=load_prompt(prompt_name)),
        HumanMessage(content=payload),
    ]

    try:
        response = await runtime.llm_main.ainvoke(messages, config={"callbacks": [handler]})
    except Exception as exc:
        logger.exception("llm call failed in node %s", node)
        return None, f"LLM 调用失败：{exc}"

    text = message_text(response)
    return extract_json(text), text
