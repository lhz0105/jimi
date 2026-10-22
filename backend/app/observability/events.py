"""SSE 可观测事件协议（唯一真源）：事件类型、信封与工厂函数。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

PROTOCOL_VERSION = 1


class EventType(StrEnum):
    RUN_QUEUED = "run_queued"
    RUN_AWAITING_CONFIRM = "run_awaiting_confirm"
    RUN_CONFIRMED = "run_confirmed"
    RUN_START = "run_start"
    NODE_START = "node_start"
    NODE_END = "node_end"
    THOUGHT = "thought"
    LLM_CALL = "llm_call"
    LLM_RESULT = "llm_result"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_ERROR = "tool_error"
    RAG_HIT = "rag_hit"
    EVIDENCE = "evidence"
    VERDICT = "verdict"
    REPORT = "report"
    BUDGET_WARNING = "budget_warning"
    WARNING = "warning"
    ERROR = "error"
    RUN_END = "run_end"


class EventEnvelope(BaseModel):
    v: int = PROTOCOL_VERSION
    run_id: str
    seq: int
    ts: int
    type: str
    node: str | None = None
    level: Literal["info", "warn", "error"] = "info"
    payload: dict[str, Any] = Field(default_factory=dict)


TERMINAL_EVENT = EventType.RUN_END

# 大字段一律只放预览/引用，完整对象留 DB
PREVIEW_LIMIT = 300
