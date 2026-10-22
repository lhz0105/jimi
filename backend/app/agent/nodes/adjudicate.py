"""adjudicate：最终裁决（结构化输出 + evidence_refs 校验 + 一次纠正重试）。"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.llm_calls import call_llm_json
from app.core.text import truncate
from app.observability.decorators import observed_node
from app.observability.events import EventType

logger = logging.getLogger(__name__)

VALID_CONCLUSIONS = ("fake_claim", "suspicious", "inconclusive", "likely_genuine")
VALID_RISK = ("critical", "high", "medium", "low", "none")

INSUFFICIENT_CONFIDENCE = 0.55
SIGHTENGINE_CONSTRAINT_FALLBACK = 0.95


def _enforce_sightengine_floor(
    verdict: dict[str, Any], evidence: list[dict[str, Any]]
) -> bool:
    """Sightengine ≥0.95 是硬约束：不得判真实/证据不足，至少疑似欺诈。"""
    high_score = False
    for item in evidence:
        if item.get("tool") != "sightengine_detect":
            continue
        raw = item.get("raw_ref") or {}
        threshold = float(raw.get("constraint_threshold") or SIGHTENGINE_CONSTRAINT_FALLBACK)
        if float(raw.get("score") or 0.0) >= threshold:
            high_score = True
            break
    if not high_score or verdict.get("conclusion") not in ("likely_genuine", "inconclusive"):
        return False

    verdict["conclusion"] = "suspicious"
    if verdict.get("risk_level") in ("none", "low"):
        verdict["risk_level"] = "medium"
    try:
        verdict["confidence"] = min(float(verdict.get("confidence") or 0.0), 0.75)
    except (TypeError, ValueError):
        verdict["confidence"] = 0.5
    verdict["summary"] = (
        str(verdict.get("summary") or "").rstrip()
        + " 【硬约束】Sightengine 给出 ≥0.95 的极高 AI 生成分数，不能判真实或证据不足；"
        "即使识图未能定位具体篡改位置，也至少判疑似欺诈。"
    )
    actions = verdict.get("recommended_actions") or []
    if isinstance(actions, list) and not any(
        isinstance(action, dict) and action.get("action") == "manual_review"
        for action in actions
    ):
        actions.append(
            {
                "action": "manual_review",
                "priority": 1,
                "note": "Sightengine 极高分数且未能排除 AI 生成，需人工复核",
            }
        )
    verdict["recommended_actions"] = actions
    return True


def _evidence_payload(evidence: list[dict[str, Any]]) -> str:
    lines = []
    for ev in evidence:
        lines.append(
            f"- [{ev['evidence_id']}] 类别={ev['category']} 方向={ev['direction']} 权重={ev['weight']}\n"
            f"  发现: {truncate(ev['finding'], 220)}\n"
            f"  来源: {ev['source'].get('type')}:{ev['source'].get('detail') or ev['source'].get('ref')}"
        )
    return "\n".join(lines) or "（无证据）"


def _normalize(data: dict[str, Any], valid_refs: set[str]) -> dict[str, Any]:
    conclusion = str(data.get("conclusion") or "inconclusive")
    if conclusion not in VALID_CONCLUSIONS:
        conclusion = "inconclusive"
    risk = str(data.get("risk_level") or "medium")
    if risk not in VALID_RISK:
        risk = "medium"
    try:
        confidence = float(data.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    refs = [str(r) for r in (data.get("evidence_refs") or []) if str(r) in valid_refs]
    actions = data.get("recommended_actions") or []
    if not isinstance(actions, list):
        actions = []
    return {
        "conclusion": conclusion,
        "risk_level": risk,
        "confidence": confidence,
        "summary": str(data.get("summary") or "（无结论摘要）"),
        "evidence_refs": refs,
        "key_counterpoints": [str(x) for x in (data.get("key_counterpoints") or [])][:5],
        "recommended_actions": actions[:5],
    }


@observed_node("adjudicate")
async def adjudicate(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    evidence = state.get("evidence") or []
    valid_refs = {e["evidence_id"] for e in evidence}

    payload = (
        f"【场景】{state.get('scenario')}\n"
        f"【案件摘要】\n{truncate((state.get('case') or {}).get('digest_text') or '', 1200)}\n\n"
        f"【完整证据链】\n{_evidence_payload(evidence)}\n\n"
        f"【未决问题】\n" + ("\n".join(f"- {q}" for q in (state.get("open_questions") or [])) or "（无）") + "\n\n"
        f"证据编号合集（evidence_refs 只能从这里选）: {sorted(valid_refs)}"
    )

    warnings: list[str] = []
    data, raw = await call_llm_json(runtime, node="adjudicate", prompt_name="adjudicate", payload=payload)

    if data is None:
        runtime.emitter.emit(
            EventType.WARNING,
            {"code": "ADJUDICATE_FALLBACK", "message": truncate(raw, 200)},
            node="adjudicate",
            level="warn",
        )
        fallback = {
            "conclusion": "inconclusive",
            "risk_level": "medium",
            "confidence": 0.2,
            "summary": "裁决未完成，基于现有证据无法给出可靠结论，建议人工复核。",
            "evidence_refs": sorted(valid_refs)[:5],
            "key_counterpoints": [],
            "recommended_actions": [
                {"action": "manual_review", "priority": 1, "note": "裁决失败，转人工"}
            ],
        }
        verdict = fallback
        warnings.append("裁决调用失败，使用保守兜底结论")
    else:
        verdict = _normalize(data, valid_refs)
        if data.get("evidence_refs") and not verdict["evidence_refs"]:
            # 引用全部无效 → 纠正重试一次
            retry_payload = (
                payload
                + f"\n\n【上次输出的引用无效】你给出的引用为 {data.get('evidence_refs')}，"
                "均不在允许集合中。请重新输出 JSON，evidence_refs 必须使用上方给出的事实编号。"
            )
            retry_data, _retry_raw = await call_llm_json(
                runtime, node="adjudicate", prompt_name="adjudicate", payload=retry_payload
            )
            if retry_data is not None:
                verdict = _normalize(retry_data, valid_refs)
            if not verdict["evidence_refs"]:
                warnings.append("裁决输出未包含有效证据引用，置信度已保守化")
                verdict["confidence"] = min(verdict["confidence"], 0.4)

    if _enforce_sightengine_floor(verdict, evidence):
        warnings.append("Sightengine 极高分数触发裁决下限：至少 suspicious")

    open_questions = [str(q) for q in (state.get("open_questions") or [])]
    needs_more = (
        verdict["conclusion"] == "inconclusive"
        and verdict["confidence"] < INSUFFICIENT_CONFIDENCE
        and bool(open_questions)
    )
    verdict["needs_more_evidence"] = needs_more

    runtime.verdict = verdict
    runtime.emitter.emit(
        EventType.VERDICT,
        {
            "conclusion": verdict["conclusion"],
            "risk_level": verdict["risk_level"],
            "confidence": verdict["confidence"],
            "summary": truncate(verdict["summary"], 400),
            "evidence_refs": verdict["evidence_refs"],
        },
        node="adjudicate",
    )

    return {"verdict": verdict, "warnings": warnings}
