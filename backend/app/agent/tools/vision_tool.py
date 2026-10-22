"""识图工具：结果持久缓存，同图同提示词跨运行复用（成本压缩核心）。

返回紧凑文本（供 ReAct 模型阅读）；完整结构化 JSON 由 vision_analysis 节点落证据链。
"""

from __future__ import annotations

from typing import Any

from app.agent import budget as budget_mod
from app.agent.imaging import analyze_image_cached

_SCENARIO_PROMPT = {
    "product_damage_claim": "vision_product_damage",
    "medical_cert_claim": "vision_medical_doc",
    "seeding_post": "vision_seeding",
}


def _compact(data: dict[str, Any]) -> str:
    if data.get("parse_error"):
        return f"模型输出无法解析为 JSON，原始片段：{(data.get('raw') or '')[:400]}"
    lines: list[str] = []
    if data.get("summary"):
        lines.append(f"摘要：{data['summary']}")
    for key, label in (
        ("product_region_verdict", "产品区域判定"),
        ("style", "图片风格"),
        ("tamper_suspected", "单据篡改迹象"),
        ("tamper_relation_to_claim", "篡改与诉求关系"),
        ("tamper_location_summary", "篡改位置"),
        ("claim_relevance_reason", "相关性判断"),
        ("irrelevant_region_aigc", "无关区域存在AIGC"),
        ("raw_confidence", "模型置信度"),
    ):
        if key in data and data[key] is not None:
            lines.append(f"{label}：{data[key]}")
    regions = data.get("regions") or []
    if regions:
        region_text = "；".join(
            f"{r.get('name', '区域')}(AIGC:{'是' if r.get('aigc_suspected') else '否'}"
            + (
                f"/诉求关系:{r.get('relation_to_claim')}"
                if r.get("aigc_suspected") and r.get("relation_to_claim")
                else ""
            )
            + ")"
            for r in regions[:6]
        )
        lines.append(f"分区结果：{region_text}")
    fields = data.get("fields") or {}
    if fields:
        field_text = "；".join(f"{k}:{v}" for k, v in list(fields.items())[:10] if v)
        if field_text:
            lines.append(f"抽取字段：{field_text}")
    if data.get("tamper_hints"):
        lines.append("篡改线索：" + "；".join(str(h) for h in data["tamper_hints"][:5]))
    if data.get("caveats"):
        lines.append("不确定因素：" + "；".join(str(c) for c in data["caveats"][:3]))
    return "\n".join(lines) or "（无有效信息）"


async def vision_analyze_impl(runtime: Any, sha256: str, focus: str = "") -> str:
    from app.agent.prompts import load_prompt

    prompt_name = _SCENARIO_PROMPT.get(
        runtime.case.get("scenario") or "", "vision_product_damage"
    )
    prompt_text = load_prompt(prompt_name)

    result = await analyze_image_cached(
        runtime, sha256=sha256, prompt_text=prompt_text, focus=focus
    )
    if result.get("status") != "ok":
        return result.get("message", "识图分析失败")

    data = result.get("data") or {}
    if data.get("parse_error"):
        raw = (data.get("raw") or "")[:300]
        return "识图模型本次未返回可解析内容（结果未缓存，可重试）。" + (
            f"\n原始片段：{raw}" if raw else ""
        )

    # 未命中缓存的真实调用需要预算放行（_guarded 已前置检查，此处二次保护）
    if not result.get("cache_hit"):
        reason = budget_mod.tool_allowed(runtime.budget, "vision_analyze")
        if reason:
            return f"[工具受限] {reason}"

    note = "（缓存命中，未产生新调用）" if result.get("cache_hit") else ""
    return f"图片分析结果{note}：\n{_compact(result.get('data') or {})}"
