"""LangGraph 图状态（CaseState）与 reducer。"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_evidence(existing: list[dict], new: list[dict]) -> list[dict]:
    """按 evidence_id 去重合并（保留先到者）。"""
    seen = {e["evidence_id"] for e in existing if "evidence_id" in e}
    merged = list(existing)
    for item in new or []:
        key = item.get("evidence_id")
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    return merged


def merge_dict(existing: dict, new: dict) -> dict:
    out = dict(existing or {})
    out.update(new or {})
    return out


class CaseState(TypedDict, total=False):
    # ---- 业务字段 ----
    run_id: str
    case: dict[str, Any]              # CaseBundle: digest/messages/images
    scenario: str
    rule_decision: dict[str, Any]
    plan: list[str]
    evidence: Annotated[list[dict], merge_evidence]
    image_findings: Annotated[dict, merge_dict]   # sha256 -> 视觉/本地检测结果
    rag_hits: list[dict]
    prior_cases: list[dict]
    steps: Annotated[list[dict], operator.add]
    verdict: dict[str, Any] | None
    report: dict[str, Any] | None
    budget: dict[str, Any]
    loop_count: int
    open_questions: list[str]
    warnings: Annotated[list[str], operator.add]
    errors: Annotated[list[dict], operator.add]

    # ---- 运行时注入（不参与持久化）----
    _emitter: Any
    _runtime: Any
    _cancel_event: Any
    _inputs: dict[str, Any]


EXECUTION_ORDER = [
    "prepare_case",
    "route_scenario",
    "local_forensics",
    "ai_image_detection",
    "rag_recall",
    "prior_case_recall",
    "vision_analysis",
    "investigate",
    "consistency",
    "adjudicate",
    "report",
    "finalize",
]

NODE_PROGRESS: dict[str, int] = {
    "prepare_case": 5,
    "route_scenario": 10,
    "local_forensics": 20,
    "ai_image_detection": 25,
    "rag_recall": 30,
    "prior_case_recall": 35,
    "vision_analysis": 45,
    "investigate": 65,
    "consistency": 75,
    "adjudicate": 85,
    "report": 95,
    "finalize": 100,
}
