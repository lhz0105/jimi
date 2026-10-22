"""consistency：陈述/单据/图文一致性核对（medical 与 seeding 场景；单次 LLM 调用）。"""

from __future__ import annotations

import json
from typing import Any

from app.agent.evidence import EvidenceBuilder
from app.agent.llm_calls import call_llm_json
from app.core.text import truncate
from app.observability.decorators import observed_node

_PROMPT = {
    "medical_cert_claim": "consistency_medical",
    "seeding_post": "consistency_seeding",
}

_SEVERITY_WEIGHT = {"clear": 0.8, "minor": 0.5, "uncertain": 0.3}


def _image_findings_digest(state: dict[str, Any]) -> str:
    lines: list[str] = []
    for sha, findings in (state.get("image_findings") or {}).items():
        vision = (findings or {}).get("vision") or {}
        if vision.get("fields"):
            lines.append(f"- 图片 {sha[:12]}… 抽取字段: " + json.dumps(vision["fields"], ensure_ascii=False))
        if vision.get("summary"):
            lines.append(f"- 图片 {sha[:12]}… 视觉摘要: {truncate(str(vision['summary']), 200)}")
    return "\n".join(lines) or "（无）"


@observed_node("consistency")
async def consistency(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    scenario = state.get("scenario")
    if scenario not in _PROMPT:
        return {}

    case = state.get("case") or {}
    payload = (
        f"【客户原文/帖子文案】\n{truncate(case.get('digest_text') or '', 2000)}\n\n"
        f"【图片分析结果】\n{_image_findings_digest(state)}\n\n"
        f"【已有证据链摘要】\n"
        + "\n".join(
            f"- [{e['evidence_id']}] {truncate(e['finding'], 150)}" for e in (state.get("evidence") or [])[-15:]
        )
    )

    data, raw = await call_llm_json(
        runtime, node="consistency", prompt_name=_PROMPT[scenario], payload=payload
    )
    if data is None:
        return {"warnings": [f"一致性核对未完成：{truncate(raw, 200)}"]}

    builder = EvidenceBuilder(state)
    evidence: list[dict[str, Any]] = []

    if scenario == "medical_cert_claim":
        for item in data.get("contradictions") or []:
            severity = str(item.get("severity") or "uncertain")
            weight = _SEVERITY_WEIGHT.get(severity, 0.3)
            evidence.append(
                builder.add(
                    category="statement_contradiction",
                    source={
                        "type": "consistency_check",
                        "ref": str(item.get("field") or "未知字段"),
                        "detail": f"客户称：{item.get('customer_says')} / 单据：{item.get('document_says')}",
                    },
                    tool="consistency_check",
                    finding=str(item.get("finding") or "陈述与单据存在出入"),
                    direction="supports_fake" if severity == "clear" else "unknown",
                    weight=weight,
                )
            )
    else:  # seeding_post
        for item in data.get("inconsistencies") or []:
            severity = str(item.get("severity") or "uncertain")
            evidence.append(
                builder.add(
                    category="marketing_pattern",
                    source={
                        "type": "consistency_check",
                        "ref": str(item.get("aspect") or "一致性"),
                        "detail": truncate(str(item.get("detail") or ""), 200),
                    },
                    tool="consistency_check",
                    finding=f"内容不一致（{item.get('aspect')}）：{item.get('detail')}",
                    direction="supports_fake" if severity == "clear" else "unknown",
                    weight=_SEVERITY_WEIGHT.get(severity, 0.3),
                )
            )
        signals = data.get("commercial_signals") or []
        if signals:
            evidence.append(
                builder.add(
                    category="marketing_pattern",
                    source={"type": "consistency_check", "ref": "商业信号", "detail": "文案与评论区"},
                    tool="consistency_check",
                    finding="检测到商业推广信号：" + "；".join(str(s) for s in signals[:5]),
                    direction="supports_fake",
                    weight=0.6,
                )
            )

    return {
        "evidence": evidence,
        "steps": [
            {
                "node": "consistency",
                "summary": truncate(str(data.get("notes") or raw), 300),
            }
        ],
    }
