"""vision_analysis：Sightengine 预检 → 逐图识图定位 → 按诉求相关性落证据。

核心业务规则：
- Sightengine 高分只说明图片可能被 AI 生成/编辑，不能单独定案；
- 识图模型必须定位篡改区域，并判断与客户诉求的关系：
  related（落在产品破损/单据关键字段/帖子关键场景）→ 支持欺诈；
  unrelated（只在人脸/背景等无关区域，诉求对象未改动）→ 不支持欺诈；
  uncertain（无法定位/无法判断）→ 不得直接认定欺诈，建议人工复核。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.agent import budget as budget_mod
from app.agent.evidence import EvidenceBuilder
from app.agent.imaging import analyze_image_cached
from app.observability.decorators import observed_node

_PROMPT_BY_SCENARIO = {
    "product_damage_claim": "vision_product_damage",
    "medical_cert_claim": "vision_medical_doc",
    "seeding_post": "vision_seeding",
    "generic": "vision_product_damage",
}

_CLAIM_SUBJECT = {
    "product_damage_claim": "客户诉求是商品破损/损坏，需要判断破损是否真实",
    "generic": "客户诉求是商品破损/损坏，需要判断破损是否真实",
    "medical_cert_claim": "客户以诊断单据作为健康损害索赔依据，需要判断单据关键字段是否被编辑",
    "seeding_post": "需要判断这条种草帖是否为真实分享，配图是否被 AI 生成/编辑成推广素材",
}


def _evidence_for_product_damage(builder: EvidenceBuilder, sha: str, data: dict) -> list[dict]:
    evidence: list[dict] = []
    source_ref = f"sha256:{sha[:12]}"
    verdict = data.get("product_region_verdict")
    regions = data.get("regions") or []
    product_regions = [r for r in regions if r.get("aigc_suspected")]
    region_text = "；".join(f"{r.get('name')}（{r.get('reason', '')[:80]}）" for r in product_regions[:4])

    if verdict == "suspected_ai":
        evidence.append(
            builder.add(
                category="aigc_artifact",
                source={"type": "image", "ref": source_ref, "detail": "商品相关区域"},
                tool="vision_analyze",
                finding=f"产品主体区域疑似 AIGC 生成/合成：{region_text or data.get('summary', '')}",
                direction="supports_fake",
                weight=0.85,
            )
        )
    elif verdict == "genuine":
        evidence.append(
            builder.add(
                category="aigc_artifact",
                source={"type": "image", "ref": source_ref, "detail": "商品相关区域"},
                tool="vision_analyze",
                finding=f"产品主体区域的破损形态未见 AIGC 生成痕迹（{data.get('summary', '')}）",
                direction="supports_genuine",
                weight=0.6,
            )
        )
    else:
        evidence.append(
            builder.add(
                category="aigc_artifact",
                source={"type": "image", "ref": source_ref, "detail": "商品相关区域"},
                tool="vision_analyze",
                finding=f"产品主体区域真实性无法确定（{data.get('summary', '')}）",
                direction="unknown",
                weight=0.3,
            )
        )

    if data.get("irrelevant_region_aigc"):
        evidence.append(
            builder.add(
                category="aigc_artifact",
                source={"type": "image", "ref": source_ref, "detail": "非商品区域"},
                tool="vision_analyze",
                finding=(
                    "图片中与商品无关的区域（如人像美颜/背景）存在 AIGC 处理，"
                    "按判定原则：与诉求无关区域的 AIGC 不计入风险升级"
                ),
                direction="neutral",
                weight=0.1,
                notes="低危判定原则：仅产品区 AIGC 才构成索赔证据",
            )
        )
    if data.get("tamper_suspected"):
        evidence.append(
            builder.add(
                category="image_manipulation",
                source={"type": "image", "ref": source_ref, "detail": "整体"},
                tool="vision_analyze",
                finding="图像存在拼接/篡改迹象（局部区域与整体噪点/清晰度不一致）",
                direction="supports_fake",
                weight=0.7,
            )
        )
    return evidence


def _evidence_for_medical(builder: EvidenceBuilder, sha: str, data: dict) -> list[dict]:
    evidence: list[dict] = []
    source_ref = f"sha256:{sha[:12]}"
    fields = data.get("fields") or {}
    field_text = "；".join(f"{k}:{v}" for k, v in fields.items() if v) or "未能抽取到有效字段"
    evidence.append(
        builder.add(
            category="document_field",
            source={"type": "image", "ref": source_ref, "detail": "诊断单据"},
            tool="vision_analyze",
            finding=f"单据字段抽取结果：{field_text}",
            direction="neutral",
            weight=0.4,
            raw_ref={"fields": fields},
        )
    )
    if data.get("tamper_suspected"):
        hints = "；".join(str(h) for h in (data.get("tamper_hints") or [])[:3])
        evidence.append(
            builder.add(
                category="image_manipulation",
                source={"type": "image", "ref": source_ref, "detail": "诊断单据"},
                tool="vision_analyze",
                finding=f"单据图像存在编辑/拼接迹象：{hints or '见视觉模型分析'}",
                direction="supports_fake",
                weight=0.75,
            )
        )
    if data.get("irrelevant_region_aigc"):
        evidence.append(
            builder.add(
                category="aigc_artifact",
                source={"type": "image", "ref": source_ref, "detail": "单据非关键区域"},
                tool="vision_analyze",
                finding=(
                    "单据图像中与诊断结论无关的区域（背景/拍摄环境等）存在 AIGC 处理，"
                    "按判定原则不计入索赔风险"
                ),
                direction="neutral",
                weight=0.1,
                notes="低危判定原则：仅单据关键字段/印章的篡改才构成索赔证据",
            )
        )
    return evidence


def _evidence_for_seeding(builder: EvidenceBuilder, sha: str, data: dict) -> list[dict]:
    evidence: list[dict] = []
    source_ref = f"sha256:{sha[:12]}"
    style = data.get("style")
    signals = "；".join(str(s) for s in (data.get("signals") or [])[:4])
    if style == "commercial":
        evidence.append(
            builder.add(
                category="marketing_pattern",
                source={"type": "image", "ref": source_ref, "detail": "帖子配图"},
                tool="vision_analyze",
                finding=f"配图呈现商拍/精修推广特征：{signals or data.get('summary', '')}",
                direction="supports_fake",
                weight=0.65,
            )
        )
    elif style == "casual":
        evidence.append(
            builder.add(
                category="marketing_pattern",
                source={"type": "image", "ref": source_ref, "detail": "帖子配图"},
                tool="vision_analyze",
                finding=f"配图呈现真实随手拍特征：{signals or data.get('summary', '')}",
                direction="supports_genuine",
                weight=0.55,
            )
        )
    else:
        evidence.append(
            builder.add(
                category="marketing_pattern",
                source={"type": "image", "ref": source_ref, "detail": "帖子配图"},
                tool="vision_analyze",
                finding=f"配图风格无法明确归类（{data.get('summary', '')}）",
                direction="unknown",
                weight=0.25,
            )
        )
    return evidence


def _sightengine_focus(scenario: str, detection: dict[str, Any]) -> str:
    """把 Sightengine 结果作为“定位线索”注入识图提示，而不是直接结论。"""
    score = float(detection.get("score") or 0.0)
    consider = float(detection.get("consider_threshold") or 0.90)
    constraint = float(detection.get("constraint_threshold") or 0.95)
    if score < consider:
        return ""
    subject = _CLAIM_SUBJECT.get(scenario, _CLAIM_SUBJECT["generic"])
    if score >= constraint:
        threshold_note = (
            f"，已达到裁决约束阈值 {constraint:.2f}"
            "（最终不得判真实，至少疑似欺诈）"
        )
    else:
        threshold_note = (
            f"，达到 AI 生成考量阈值 {consider:.2f}，但未达到约束阈值 {constraint:.2f}"
            "（不强制至少疑似欺诈，仍需结合定位判断）"
        )
    return (
        f"第三方 AI 生成检测（Sightengine）提示：该图 AI 生成概率为 {score:.2f}"
        f"{threshold_note}。该检测来自不可见水印/模型硬编码信息，"
        "只能说明图片可能经过 AI 生成或编辑，不能指出篡改位置，也不能单独证明客户诉求为假。"
        f"{subject}。请仔细甄别可见的 AI 合成/篡改痕迹，定位到具体区域，"
        "并判断篡改区域与客户诉求的关系（related/unrelated/uncertain）。"
        "若篡改只发生在与诉求无关的区域（如人脸美颜、背景替换），而诉求对象本身未被改动，"
        "必须明确指出，不能因为检测分高就认定欺诈。若看不到可见痕迹但检测分很高，"
        "请将关系标为 uncertain 并说明，不要臆造位置。"
    )


def _claim_region_authentic(scenario: str, vision: dict[str, Any]) -> bool:
    if scenario in ("product_damage_claim", "generic"):
        return vision.get("product_region_verdict") == "genuine"
    if scenario == "medical_cert_claim":
        return vision.get("tamper_suspected") is False
    if scenario == "seeding_post":
        return vision.get("style") == "casual"
    return False


def _evidence_for_sightengine_relevance(
    builder: EvidenceBuilder,
    sha: str,
    detection: dict[str, Any],
    vision: dict[str, Any],
    scenario: str,
) -> dict[str, Any] | None:
    """联合证据：Sightengine 分数 + 识图定位 + 诉求相关性。"""
    score = float(detection.get("score") or 0.0)
    consider = float(detection.get("consider_threshold") or 0.90)
    constraint_threshold = float(detection.get("constraint_threshold") or 0.95)
    if score < consider:
        return None

    constraint = score >= constraint_threshold
    relation = str(vision.get("tamper_relation_to_claim") or "uncertain")
    if relation not in ("related", "unrelated", "uncertain") or vision.get("parse_error"):
        relation = "uncertain"
    location = str(vision.get("tamper_location_summary") or "").strip()
    reason = str(vision.get("claim_relevance_reason") or "").strip()
    location_text = location or "识图未给出明确位置"
    reason_text = f" 依据：{reason}" if reason else ""
    source = {
        "type": "image",
        "ref": f"sha256:{sha[:12]}",
        "detail": "Sightengine 检测 + 识图定位",
    }
    raw_ref = {
        "score": score,
        "consider_threshold": consider,
        "constraint_threshold": constraint_threshold,
        "relation": relation,
        "tamper_location": location,
    }

    if relation == "related":
        return builder.add(
            category="aigc_artifact",
            source=source,
            tool="vision_analyze",
            finding=(
                f"Sightengine AI 生成概率 {score:.2f}；识图定位到与客户诉求直接相关的篡改"
                f"（{location_text}）。{reason_text}该篡改落在支撑索赔的关键区域，支持欺诈认定。"
            ),
            direction="supports_fake",
            weight=0.9 if constraint else 0.75,
            raw_ref=raw_ref,
        )

    if relation == "unrelated":
        if constraint:
            return builder.add(
                category="aigc_artifact",
                source=source,
                tool="vision_analyze",
                finding=(
                    f"Sightengine AI 生成概率 {score:.2f}（达到约束阈值 {constraint_threshold:.2f}）。"
                    f"识图定位到的可见篡改与诉求无关（{location_text}），诉求相关区域未见异常；"
                    "但极高分数无法排除整图 AI 生成/深度编辑，不能据此认定诉求真实。"
                    "按规则不得判 likely_genuine，至少为 suspicious，"
                    "建议人工复核或索取原始素材。"
                    f"{reason_text}"
                ),
                direction="unknown",
                weight=0.55,
                raw_ref=raw_ref,
            )
        if _claim_region_authentic(scenario, vision):
            return builder.add(
                category="aigc_artifact",
                source=source,
                tool="vision_analyze",
                finding=(
                    f"Sightengine AI 生成概率 {score:.2f}（未达到约束阈值 {constraint_threshold:.2f}）；"
                    f"但识图定位显示篡改集中在与诉求无关的区域（{location_text}），"
                    f"诉求相关区域未见 AI 篡改。{reason_text}"
                    "按判定原则，该 AI 信号不计入欺诈风险，支持诉求相关内容的真实性。"
                ),
                direction="supports_genuine",
                weight=0.45,
                raw_ref=raw_ref,
            )
        return builder.add(
            category="aigc_artifact",
            source=source,
            tool="vision_analyze",
            finding=(
                f"Sightengine AI 生成概率 {score:.2f}；识图认为篡改与诉求无关"
                f"（{location_text}），但诉求相关区域的真实性未能明确确认。{reason_text}"
                "不得仅凭该分数认定欺诈，建议人工复核。"
            ),
            direction="unknown",
            weight=0.35,
            raw_ref=raw_ref,
        )

    if constraint:
        return builder.add(
            category="aigc_artifact",
            source=source,
            tool="vision_analyze",
            finding=(
                f"Sightengine AI 生成概率 {score:.2f}（达到约束阈值 {constraint_threshold:.2f}）；"
                f"识图未能确认篡改位置或与诉求的关系（{location_text}）。"
                "极高分数说明图片很可能为 AI 生成，但识图无法定位具体位置，"
                "故不能判真实（likely_genuine）或证据不足（inconclusive），至少判疑似欺诈（suspicious）；"
                "建议人工复核或索取原始素材。"
                f"{reason_text}"
            ),
            direction="unknown",
            weight=0.55,
            raw_ref=raw_ref,
        )
    return builder.add(
        category="aigc_artifact",
        source=source,
        tool="vision_analyze",
        finding=(
            f"Sightengine AI 生成概率 {score:.2f}（未达到约束阈值 {constraint_threshold:.2f}）；"
            f"识图未能确认篡改位置或与诉求的关系（{location_text}）。{reason_text}"
            "不强制至少疑似欺诈，但不得仅凭该分数认定欺诈；建议人工复核或索取原始素材。"
        ),
        direction="unknown",
        weight=0.35,
        raw_ref=raw_ref,
    )


@observed_node("vision_analysis")
async def vision_analysis(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    scenario = state.get("scenario") or "generic"
    prompt_name = _PROMPT_BY_SCENARIO.get(scenario, "vision_product_damage")

    if runtime.llm_vision is None:
        return {"warnings": ["识图模型未配置，跳过视觉分析"]}

    from app.agent.prompts import load_prompt

    prompt_text = load_prompt(prompt_name)
    builder = EvidenceBuilder(state)
    findings: dict[str, Any] = dict(state.get("image_findings") or {})
    detections = dict(findings)
    evidence: list[dict[str, Any]] = []
    warnings: list[str] = []

    for image in runtime.images:
        sha = image["sha256"]
        if not Path(image["path"]).exists():
            warnings.append(f"图片文件缺失，跳过视觉分析: {sha[:12]}")
            continue
        detection = (detections.get(sha) or {}).get("sightengine") or {}
        focus = _sightengine_focus(scenario, detection) if detection else ""
        try:
            result = await analyze_image_cached(
                runtime, sha256=sha, prompt_text=prompt_text, focus=focus
            )
        except Exception as exc:
            warnings.append(f"识图调用失败（{sha[:12]}）：{exc}")
            continue
        if result.get("status") != "ok":
            warnings.append(f"识图失败（{sha[:12]}）：{result.get('message')}")
            continue

        if not result.get("cache_hit"):
            budget_mod.record_tool(runtime.budget, "vision_analyze", emitter=runtime.emitter)

        data = result.get("data") or {}
        findings[sha] = {
            **(findings.get(sha) or {}),
            "vision": data,
            "vision_cache_hit": result.get("cache_hit"),
        }

        if scenario == "medical_cert_claim":
            evidence.extend(_evidence_for_medical(builder, sha, data))
        elif scenario == "seeding_post":
            evidence.extend(_evidence_for_seeding(builder, sha, data))
        else:
            evidence.extend(_evidence_for_product_damage(builder, sha, data))

        if detection:
            combined = _evidence_for_sightengine_relevance(
                builder, sha, detection, data, scenario
            )
            if combined is not None:
                evidence.append(combined)

    return {"image_findings": findings, "evidence": evidence, "warnings": warnings}
