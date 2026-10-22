"""LangGraph 图装配：节点、条件路由、investigate 回边。

分支只影响提示词与工具集（节点内部按 scenario 选择），不复制整图。
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, StateGraph

from app.agent import budget as budget_mod
from app.agent.nodes.adjudicate import adjudicate
from app.agent.nodes.ai_image_detection import ai_image_detection
from app.agent.nodes.consistency import consistency
from app.agent.nodes.finalize import finalize
from app.agent.nodes.investigate import investigate
from app.agent.nodes.local_forensics import local_forensics
from app.agent.nodes.prepare_case import prepare_case
from app.agent.nodes.prior_case_recall import prior_case_recall
from app.agent.nodes.rag_recall import rag_recall
from app.agent.nodes.report import report
from app.agent.nodes.route_scenario import route_scenario
from app.agent.nodes.vision_analysis import vision_analysis
from app.agent.state import CaseState

logger = logging.getLogger(__name__)

RECURSION_LIMIT = 50


def route_after_adjudicate(state: dict[str, Any]) -> str:
    """证据不足且预算/轮数允许 → 回 investigate；否则出报告。"""
    verdict = state.get("verdict") or {}
    if not verdict.get("needs_more_evidence"):
        return "report"

    runtime = state.get("_runtime")
    max_loops = runtime.settings.max_investigate_loops if runtime is not None else 2
    if int(state.get("loop_count") or 0) >= max_loops:
        return "report"
    if runtime is not None and budget_mod.llm_allowed(runtime.budget):
        return "report"
    return "investigate"


def build_graph() -> Any:
    graph = StateGraph(CaseState)

    graph.add_node("prepare_case", prepare_case)
    graph.add_node("route_scenario", route_scenario)
    graph.add_node("local_forensics", local_forensics)
    graph.add_node("ai_image_detection", ai_image_detection)
    graph.add_node("rag_recall", rag_recall)
    graph.add_node("prior_case_recall", prior_case_recall)
    graph.add_node("vision_analysis", vision_analysis)
    graph.add_node("investigate", investigate)
    graph.add_node("consistency", consistency)
    graph.add_node("adjudicate", adjudicate)
    graph.add_node("report", report)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("prepare_case")
    graph.add_edge("prepare_case", "route_scenario")
    graph.add_edge("route_scenario", "local_forensics")
    graph.add_edge("local_forensics", "ai_image_detection")
    graph.add_edge("ai_image_detection", "rag_recall")
    graph.add_edge("rag_recall", "prior_case_recall")
    graph.add_edge("prior_case_recall", "vision_analysis")
    graph.add_edge("vision_analysis", "investigate")
    graph.add_edge("investigate", "consistency")
    graph.add_edge("consistency", "adjudicate")
    graph.add_conditional_edges(
        "adjudicate",
        route_after_adjudicate,
        {"investigate": "investigate", "report": "report"},
    )
    graph.add_edge("report", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()
