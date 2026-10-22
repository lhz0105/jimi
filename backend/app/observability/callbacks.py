"""LangChain 回调 → 事件（LLM 侧）。

工具事件由 agent/middleware 的 @wrap_tool_call 统一发射（结构化摘要），此处不重复发。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Protocol

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage

from app.core.clock import now_ms
from app.core.text import estimate_tokens, truncate
from app.observability.context import current_node
from app.observability.events import EventType

logger = logging.getLogger(__name__)

THOUGHT_LIMIT = 1200


class EmitterLike(Protocol):
    def emit(self, event_type: EventType | str, payload: dict | None = None, *, node: str | None = None, level: str = "info") -> dict: ...


def _message_summary(messages: list[list[BaseMessage]] | list[BaseMessage]) -> tuple[int, int]:
    """返回 (消息条数, 估算 prompt tokens)。"""
    flat: list[BaseMessage] = []
    for item in messages:
        if isinstance(item, list):
            flat.extend(item)
        else:
            flat.append(item)
    tokens = 0
    for msg in flat:
        content = msg.content
        if isinstance(content, str):
            tokens += estimate_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    tokens += estimate_tokens(str(part.get("text", "")))
                elif isinstance(part, dict) and part.get("type") == "image_url":
                    tokens += 700  # 图片按经验值计（视觉 token 估算）
    return len(flat), tokens


def _extract_usage(response: Any) -> dict[str, Any] | None:
    """兼容多种返回形态，从 LLMResult 中取 usage。"""
    try:
        gen = response.generations[0][0]
    except (AttributeError, IndexError):
        gen = None
    message = getattr(gen, "message", None)
    usage = getattr(message, "usage_metadata", None)
    if usage:
        details = usage.get("input_token_details") or {}
        return {
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "cache_read_tokens": details.get("cache_read") or 0,
        }
    llm_output = getattr(response, "llm_output", None) or {}
    token_usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    if token_usage:
        return {
            "prompt_tokens": token_usage.get("prompt_tokens") or token_usage.get("input_tokens"),
            "completion_tokens": token_usage.get("completion_tokens")
            or token_usage.get("output_tokens"),
            "total_tokens": token_usage.get("total_tokens"),
            "cache_read_tokens": token_usage.get("prompt_cache_hit_tokens")
            or token_usage.get("cache_read_tokens")
            or 0,
        }
    return None


def _looks_like_json(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("```"):
        return "json" in stripped[:20].lower()
    return stripped.startswith("{") or stripped.startswith("[")


def _structured_summary(text: str) -> str:
    """把结构化 JSON 压成人类可读的步骤摘要（不把原始 JSON 放进思考流）。"""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        data = json.loads(stripped)
    except (TypeError, ValueError):
        return "模型返回结构化结果"
    if not isinstance(data, dict):
        return "模型返回结构化结果"
    if data.get("conclusion"):
        return (
            f"结论：{data.get('conclusion')} · 风险：{data.get('risk_level')}"
            f" · 置信度：{data.get('confidence')}"
        )
    if isinstance(data.get("new_evidence"), list):
        return (
            f"新增证据 {len(data['new_evidence'])} 条"
            f" · 待确认 {len(data.get('open_questions') or [])} 项"
        )
    if isinstance(data.get("contradictions"), list):
        return (
            f"矛盾 {len(data['contradictions'])} 项"
            f" · 一致性评分 {data.get('consistency_score', '—')}"
        )
    if isinstance(data.get("inconsistencies"), list):
        return (
            f"不一致 {len(data['inconsistencies'])} 项"
            f" · 商业信号 {len(data.get('commercial_signals') or [])} 项"
        )
    if data.get("summary"):
        return truncate(str(data["summary"]), 300)
    return "模型返回结构化结果"


def _message_content(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip() if content else ""


def _extract_reasoning(message: Any) -> str | None:
    if message is None:
        return None
    extra = getattr(message, "additional_kwargs", None) or {}
    reasoning = extra.get("reasoning_content")
    if reasoning:
        return str(reasoning)
    # langchain 生态的部分实现放在 content blocks 里
    content = getattr(message, "content", None)
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") in ("reasoning", "thinking"):
                text = part.get("text") or part.get("reasoning")
                if text:
                    return str(text)
    return None


class EmitterCallbackHandler(BaseCallbackHandler):
    """把 LLM 调用过程翻译成可观测事件。"""

    def __init__(
        self,
        emitter: EmitterLike,
        *,
        model_name: str = "unknown",
        usage_sink: Callable[[dict[str, Any], str], None] | None = None,
    ) -> None:
        self._emitter = emitter
        self._model = model_name
        self._usage_sink = usage_sink
        self._starts: dict[str, int] = {}
        self._last_usage: dict[str, Any] | None = None

    # ---- LLM ----

    def on_chat_model_start(self, serialized: dict, messages: Any, **kwargs: Any) -> None:
        run_key = str(kwargs.get("run_id", ""))
        self._starts[run_key] = now_ms()
        count, est_tokens = _message_summary(messages)
        self._emitter.emit(
            EventType.LLM_CALL,
            {
                "model": self._model,
                "purpose": current_node.get(),
                "message_count": count,
                "est_prompt_tokens": est_tokens,
            },
        )

    def on_llm_start(self, serialized: dict, prompts: list[str], **kwargs: Any) -> None:
        run_key = str(kwargs.get("run_id", ""))
        self._starts[run_key] = now_ms()
        self._emitter.emit(
            EventType.LLM_CALL,
            {
                "model": self._model,
                "purpose": current_node.get(),
                "message_count": len(prompts),
                "est_prompt_tokens": sum(estimate_tokens(p) for p in prompts),
            },
        )

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        run_key = str(kwargs.get("run_id", ""))
        started = self._starts.pop(run_key, None)
        latency = now_ms() - started if started else None
        usage = _extract_usage(response) or {}
        self._last_usage = usage or None

        gen = None
        try:
            gen = response.generations[0][0]
        except (AttributeError, IndexError):
            pass
        message = getattr(gen, "message", None)
        gen_info = getattr(gen, "generation_info", None) or {}
        response_meta = getattr(message, "response_metadata", None) or {}
        finish_reason = gen_info.get("finish_reason") or response_meta.get("finish_reason")
        content = _message_content(message)

        self._emitter.emit(
            EventType.LLM_RESULT,
            {
                "model": self._model,
                "purpose": current_node.get(),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "latency_ms": latency,
                "finish_reason": finish_reason,
                "content_preview": truncate(content, 3000),
                "content_truncated": len(content) > 3000,
            },
        )

        reasoning = _extract_reasoning(message)
        if reasoning:
            self._emitter.emit(
                EventType.THOUGHT,
                {"kind": "reasoning", "text": truncate(reasoning, THOUGHT_LIMIT)},
            )
        elif content:
            # 结构化 JSON 在 llm_result 中按字段渲染；思考流只放摘要，避免原始 JSON
            summary = _structured_summary(content) if _looks_like_json(content) else content
            self._emitter.emit(
                EventType.THOUGHT,
                {
                    "kind": "step_summary",
                    "text": truncate(summary, THOUGHT_LIMIT),
                },
            )

        if self._usage_sink is not None:
            try:
                self._usage_sink(usage, self._model)
            except Exception:  # pragma: no cover
                logger.exception("usage sink failed")

    def on_llm_error(self, error: BaseException, **kwargs: Any) -> None:
        self._emitter.emit(
            EventType.ERROR,
            {"code": "LLM_ERROR", "message": str(error), "fatal": False},
            level="error",
        )
