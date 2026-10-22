"""成本闸门：token/调用次数/费用上限，超限即收口。

budget 以纯 dict 存在图状态里（JSON 可序列化）。
"""

from __future__ import annotations

from typing import Any

from app.config import Settings
from app.llm.pricing import PriceTable, estimate_cost
from app.observability.events import EventType

WARN_RATIO = 0.8


def new_budget(settings: Settings) -> dict[str, Any]:
    return {
        "llm_calls": 0,
        "prompt_tokens": 0,
        "cache_read_tokens": 0,
        "completion_tokens": 0,
        "tool_calls": 0,
        "vision_calls": 0,
        "tavily_calls": 0,
        "est_cost": 0.0,
        "per_tool": {},
        "by_node": {},
        "limits": {
            "max_llm_calls": settings.budget_max_llm_calls,
            "max_tool_calls": settings.budget_max_tool_calls,
            "max_vision_calls": settings.budget_max_vision_calls,
            "max_tavily_calls": settings.budget_max_tavily_calls,
            "max_prompt_tokens": settings.budget_max_prompt_tokens,
            "max_run_cost": settings.budget_max_run_cost,
        },
    }


def _bump_node(budget: dict[str, Any], node: str | None, usage: dict, cost: float) -> None:
    entry = budget["by_node"].setdefault(
        node or "unknown", {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}
    )
    entry["llm_calls"] += 1
    entry["prompt_tokens"] += usage.get("prompt_tokens") or 0
    entry["completion_tokens"] += usage.get("completion_tokens") or 0
    entry["cost"] = round(entry["cost"] + cost, 6)


def record_llm(
    budget: dict[str, Any],
    *,
    node: str | None,
    usage: dict[str, Any],
    prices: PriceTable,
    role: str = "main",
    emitter: Any = None,
) -> None:
    budget["llm_calls"] += 1
    budget["prompt_tokens"] += usage.get("prompt_tokens") or 0
    budget["cache_read_tokens"] += usage.get("cache_read_tokens") or 0
    budget["completion_tokens"] += usage.get("completion_tokens") or 0
    cost = estimate_cost(usage, prices, role=role)
    budget["est_cost"] = round(budget["est_cost"] + cost, 6)
    _bump_node(budget, node, usage, cost)
    _warn_if_close(budget, emitter)


def record_tool(budget: dict[str, Any], tool: str, *, emitter: Any = None) -> None:
    budget["tool_calls"] += 1
    budget["per_tool"][tool] = budget["per_tool"].get(tool, 0) + 1
    if tool == "vision_analyze":
        budget["vision_calls"] += 1
    elif tool == "web_search":
        budget["tavily_calls"] += 1
    _warn_if_close(budget, emitter)


def _warn_if_close(budget: dict[str, Any], emitter: Any) -> None:
    if emitter is None:
        return
    limits = budget["limits"]
    checks = (
        ("llm_calls", limits["max_llm_calls"]),
        ("tool_calls", limits["max_tool_calls"]),
        ("vision_calls", limits["max_vision_calls"]),
        ("tavily_calls", limits["max_tavily_calls"]),
        ("prompt_tokens", limits["max_prompt_tokens"]),
        ("est_cost", limits["max_run_cost"]),
    )
    for metric, limit in checks:
        if not limit:
            continue
        used = budget.get(metric, 0)
        if used >= limit * WARN_RATIO:
            emitter.emit(
                EventType.BUDGET_WARNING,
                {"metric": metric, "used": used, "limit": limit},
                level="warn",
            )


def llm_allowed(budget: dict[str, Any]) -> str | None:
    """返回超限原因（None 表示允许）。"""
    limits = budget["limits"]
    if budget["llm_calls"] >= limits["max_llm_calls"]:
        return f"LLM 调用次数达上限 {limits['max_llm_calls']}"
    if budget["prompt_tokens"] >= limits["max_prompt_tokens"]:
        return f"Prompt token 达上限 {limits['max_prompt_tokens']}"
    if budget["est_cost"] >= limits["max_run_cost"]:
        return f"估算成本达上限 {limits['max_run_cost']}"
    return None


def tool_allowed(budget: dict[str, Any], tool: str) -> str | None:
    limits = budget["limits"]
    if budget["tool_calls"] >= limits["max_tool_calls"]:
        return f"工具调用总数达上限 {limits['max_tool_calls']}"
    if tool == "vision_analyze" and budget["vision_calls"] >= limits["max_vision_calls"]:
        return f"识图调用次数达上限 {limits['max_vision_calls']}"
    if tool == "web_search" and budget["tavily_calls"] >= limits["max_tavily_calls"]:
        return f"联网搜索次数达上限 {limits['max_tavily_calls']}"
    return None


def cost_summary(budget: dict[str, Any]) -> dict[str, Any]:
    return {
        "llm_calls": budget.get("llm_calls", 0),
        "prompt_tokens": budget.get("prompt_tokens", 0),
        "cache_read_tokens": budget.get("cache_read_tokens", 0),
        "completion_tokens": budget.get("completion_tokens", 0),
        "tool_calls": budget.get("tool_calls", 0),
        "vision_calls": budget.get("vision_calls", 0),
        "tavily_calls": budget.get("tavily_calls", 0),
        "est_cost": round(budget.get("est_cost", 0.0), 6),
        "per_tool": dict(budget.get("per_tool", {})),
        "by_node": dict(budget.get("by_node", {})),
    }
