"""ai_image_detection：所有图片先过第三方 AI 生成检测（Sightengine）。

检测分数来自不可见水印/模型硬编码信息，只能说明图片可能经过 AI 生成或编辑，
既不指出篡改位置，也不能单独认定欺诈。结果写入 image_findings，供 vision_analysis
带着分数让识图模型定位篡改区域，再结合客户诉求判断二者关系。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent import budget as budget_mod
from app.agent.evidence import EvidenceBuilder
from app.observability.decorators import observed_node
from app.services.sightengine import detect_ai_generated, sightengine_ready


def _evidence_for_detection(
    builder: EvidenceBuilder, sha: str, data: dict[str, Any]
) -> dict[str, Any]:
    score = float(data.get("score") or 0.0)
    consider = float(data.get("consider_threshold") or 0.90)
    constraint = float(data.get("constraint_threshold") or 0.95)
    source_ref = f"sha256:{sha[:12]}"
    source = {"type": "image", "ref": source_ref, "detail": "第三方 AI 生成检测（Sightengine）"}
    raw_ref = {
        "score": score,
        "consider_threshold": consider,
        "constraint_threshold": constraint,
    }

    if score < consider:
        return builder.add(
            category="aigc_artifact",
            source=source,
            tool="sightengine_detect",
            finding=(
                f"Sightengine 概率 {score:.2f} 低于 AI 生成考量阈值 {consider:.2f}；"
                "按规则不纳入“是否为 AI 生成”的考量，仅记录，不据此升级风险或阻止真实结论。"
            ),
            direction="neutral",
            weight=0.1,
            raw_ref=raw_ref,
        )

    finding = (
        f"Sightengine 检测到 AI 生成概率 {score:.2f}（考量阈值 {consider:.2f}）。"
        "该信号来自不可见水印/模型硬编码信息，只能说明图片可能经过 AI 生成或编辑，"
        "不指明篡改位置，不能单独作为欺诈依据；需由识图模型定位篡改区域并核对客户诉求。"
    )
    if score < constraint:
        finding += (
            f" 当前未达到裁决约束阈值 {constraint:.2f}：仅作为疑点，"
            "结合识图定位判断，不强制至少疑似欺诈。"
        )
        weight = 0.25
    else:
        finding += (
            f" 已达到裁决约束阈值 {constraint:.2f}：定位前不得直接认定欺诈，"
            "但最终结论不得为真实，至少为疑似欺诈。"
        )
        weight = 0.35
    return builder.add(
        category="aigc_artifact",
        source=source,
        tool="sightengine_detect",
        finding=finding,
        direction="unknown",
        weight=weight,
        raw_ref={**raw_ref, "requires_localization": True},
    )


@observed_node("ai_image_detection")
async def ai_image_detection(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    if not runtime.images or runtime.settings.llm_mode != "real":
        return {}
    if not sightengine_ready(runtime):
        return {
            "warnings": [
                "Sightengine 未启用或缺少凭据，跳过 AI 生成预检；识图分析仍继续"
            ]
        }

    builder = EvidenceBuilder(state)
    findings: dict[str, Any] = dict(state.get("image_findings") or {})
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []

    for image in runtime.images:
        sha = image["sha256"]
        if not Path(image["path"]).exists():
            warnings.append(f"图片文件缺失，跳过 AI 生成预检: {sha[:12]}")
            continue

        check = await detect_ai_generated(runtime, sha256=sha)
        if check.get("status") != "ok":
            warnings.append(
                f"Sightengine 预检未完成（{sha[:12]}）：{check.get('message')}"
            )
            continue

        payload = check.get("data") or {}
        findings[sha] = {**(findings.get(sha) or {}), "sightengine": payload}
        if not check.get("cache_hit"):
            budget_mod.record_tool(
                runtime.budget, "sightengine_detect", emitter=runtime.emitter
            )
        evidence.append(_evidence_for_detection(builder, sha, payload))

    return {"image_findings": findings, "evidence": evidence, "warnings": warnings}
