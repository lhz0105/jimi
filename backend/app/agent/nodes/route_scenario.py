"""route_scenario：复核场景并生成调查计划。纯规则，无 LLM 调用。"""

from __future__ import annotations

from typing import Any

from app.observability.decorators import observed_node

PLANS: dict[str, list[str]] = {
    "product_damage_claim": [
        "核对图片产品主体区域是否 AIGC/篡改（分区判定）",
        "核对客户陈述与图片内容、诉求强度是否矛盾",
        "检索知识库中的同类欺诈模式",
        "检查图片是否与其他索赔案件复用",
    ],
    "medical_cert_claim": [
        "核对诊断单抽取字段与客户陈述是否一致",
        "核实医学常识矛盾（症状-病程-归因）",
        "检查单据/照片是否与其他索赔复用",
        "检索知识库中的医疗索赔欺诈模式",
    ],
    "seeding_post": [
        "评估图片风格（真实随手拍 vs 商拍精修）",
        "评估文案话术模板化程度与商业信号",
        "评估评论区水军特征",
        "核对图文一致性",
    ],
    "generic": [
        "梳理客户诉求与已提交证据",
        "检索知识库中的相关判定标准",
        "核对陈述与证据的一致性",
    ],
}


@observed_node("route_scenario")
async def route_scenario(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    decision = state.get("rule_decision") or {}
    scenario = state.get("scenario") or decision.get("scenario") or "generic"
    if scenario not in PLANS:
        scenario = "generic"
    runtime.case["scenario"] = scenario
    return {"scenario": scenario, "plan": list(PLANS[scenario])}
