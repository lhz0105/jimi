"""investigate：场景化 ReAct 调查子代理（create_agent + 工具集）。

成本控制：预算前置检查、recursion_limit 限制轮数、工具结果截断（registry）、
只传 digest + 证据摘要 + 待解决问题（不全量会话）。
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent import budget as budget_mod
from app.agent.evidence import EvidenceBuilder
from app.agent.llm_calls import message_text
from app.agent.prompts import load_prompt
from app.agent.tools.registry import build_tools
from app.core.text import truncate
from app.llm.fake import extract_json
from app.observability.callbacks import EmitterCallbackHandler
from app.observability.decorators import observed_node

logger = logging.getLogger(__name__)

_SYS_PROMPT = {
    "product_damage_claim": "investigate_product_damage",
    "medical_cert_claim": "investigate_medical",
    "seeding_post": "investigate_seeding",
    "generic": "investigate_product_damage",
}

RECURSION_LIMIT = 12


def _evidence_digest(evidence: list[dict[str, Any]], limit: int = 20) -> str:
    if not evidence:
        return "（暂无）"
    lines = []
    for ev in evidence[-limit:]:
        lines.append(
            f"- [{ev['evidence_id']}] ({ev['category']}/{ev['direction']}, 权重{ev['weight']}) {truncate(ev['finding'], 160)}"
        )
    return "\n".join(lines)


def _build_payload(state: dict[str, Any]) -> str:
    case = state.get("case") or {}
    scenario = state.get("scenario")
    images = case.get("images") or []
    image_lines = []
    for img in images:
        findings = (state.get("image_findings") or {}).get(img["sha256"]) or {}
        vision = findings.get("vision") or {}
        detection = findings.get("sightengine") or {}
        summary = vision.get("summary") or vision.get("style") or "（未分析）"
        relation = vision.get("tamper_relation_to_claim")
        if relation:
            summary = f"{summary}；篡改与诉求关系: {relation}"
        if detection:
            summary = f"{summary}；Sightengine AI 生成概率 {float(detection.get('score') or 0):.2f}"
        image_lines.append(f"- sha256={img['sha256'][:12]}… 视觉结论: {truncate(str(summary), 180)}")
    open_questions = state.get("open_questions") or []
    plan = state.get("plan") or []
    return (
        f"【场景】{scenario}\n"
        f"【调查计划】\n" + "\n".join(f"- {p}" for p in plan) + "\n"
        f"【案件摘要】\n{truncate(case.get('digest_text') or '', 1200)}\n"
        f"【图片清单】\n" + ("\n".join(image_lines) or "（无图片）") + "\n"
        f"【已有证据链】\n{_evidence_digest(state.get('evidence') or [])}\n"
        f"【待解决问题】\n" + ("\n".join(f"- {q}" for q in open_questions) or "（无）") + "\n\n"
        "请开始调查；证据足够时输出约定的 JSON（new_evidence/open_questions/notes）。"
    )


@observed_node("investigate")
async def investigate(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    if runtime.llm_main is None:
        return {"warnings": ["主模型未配置，跳过调查阶段"]}

    scenario = state.get("scenario") or "generic"
    loop_count = int(state.get("loop_count") or 0)

    reason = budget_mod.llm_allowed(runtime.budget)
    if reason:
        return {
            "warnings": [f"预算受限，跳过第 {loop_count + 1} 轮调查：{reason}"],
            "loop_count": loop_count + 1,
        }

    from langchain.agents import create_agent
    from langchain_core.messages import HumanMessage

    handler = EmitterCallbackHandler(
        runtime.emitter,
        model_name=runtime.settings.llm_main_model,
        usage_sink=lambda usage, model: budget_mod.record_llm(
            runtime.budget,
            node="investigate",
            usage=usage,
            prices=runtime.prices,
            role="main",
            emitter=runtime.emitter,
        ),
    )

    tools = build_tools(runtime, scenario)
    system_prompt = load_prompt(_SYS_PROMPT.get(scenario, "investigate_product_damage"))
    try:
        agent = create_agent(model=runtime.llm_main, tools=tools, system_prompt=system_prompt)
    except TypeError:  # 兼容不同版本的参数名
        agent = create_agent(model=runtime.llm_main, tools=tools, prompt=system_prompt)
    payload = _build_payload(state)

    warnings: list[str] = []
    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=payload)]},
            config={"recursion_limit": RECURSION_LIMIT, "callbacks": [handler]},
        )
        final_text = message_text(result["messages"][-1])
    except Exception as exc:
        logger.exception("investigate agent failed")
        warnings.append(f"调查子代理执行异常：{exc}")
        final_text = ""

    parsed = extract_json(final_text) or {}
    builder = EvidenceBuilder(state)
    evidence: list[dict[str, Any]] = []
    for item in parsed.get("new_evidence") or []:
        finding = str(item.get("finding") or "").strip()
        if not finding:
            continue
        try:
            weight = float(item.get("weight") or 0.4)
        except (TypeError, ValueError):
            weight = 0.4
        evidence.append(
            builder.add(
                category=str(item.get("category") or "customer_behavior"),
                source={
                    "type": "investigation",
                    "ref": f"investigate-loop-{loop_count}",
                    "detail": str(item.get("source_detail") or ""),
                },
                tool="investigate_agent",
                finding=finding,
                direction=str(item.get("direction") or "unknown"),
                weight=weight,
            )
        )

    steps = [
        {
            "node": "investigate",
            "loop": loop_count,
            "summary": truncate(str(parsed.get("notes") or final_text or "（无输出）"), 300),
            "evidence_added": len(evidence),
        }
    ]
    open_questions = [str(q) for q in (parsed.get("open_questions") or []) if str(q).strip()]

    return {
        "evidence": evidence,
        "steps": steps,
        "loop_count": loop_count + 1,
        "open_questions": open_questions,
        "warnings": warnings,
    }
