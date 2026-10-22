"""Sightengine 预检与“篡改—诉求相关性”联合证据测试。"""

from __future__ import annotations

from pathlib import Path

from app.agent.evidence import EvidenceBuilder
from app.agent.nodes.adjudicate import _enforce_sightengine_floor
from app.agent.nodes.ai_image_detection import _evidence_for_detection
from app.agent.nodes.vision_analysis import _evidence_for_sightengine_relevance
from app.agent.prompts import load_prompt
from app.config import Settings
from app.services.sightengine import _with_thresholds

SHA = "a" * 64


def _detection(score: float) -> dict:
    builder = EvidenceBuilder({})
    return _evidence_for_detection(
        builder,
        SHA,
        {
            "score": score,
            "consider_threshold": 0.90,
            "constraint_threshold": 0.95,
        },
    )


def _relevance(score: float, vision: dict, scenario: str = "product_damage_claim") -> dict:
    builder = EvidenceBuilder({})
    return _evidence_for_sightengine_relevance(
        builder,
        SHA,
        {
            "score": score,
            "consider_threshold": 0.90,
            "constraint_threshold": 0.95,
        },
        vision,
        scenario,
    )


def test_extreme_score_is_signal_not_fraud_conclusion() -> None:
    item = _detection(0.97)
    assert item["direction"] == "unknown"
    assert item["weight"] == 0.35
    assert "不能单独作为欺诈依据" in item["finding"]
    assert "定位前不得直接认定欺诈" in item["finding"]
    assert "最终结论不得为真实" in item["finding"]


def test_below_consider_threshold_is_neutral() -> None:
    item = _detection(0.12)
    assert item["direction"] == "neutral"
    assert item["weight"] == 0.1
    assert "低于 AI 生成考量阈值" in item["finding"]


def test_between_thresholds_is_candidate_without_hard_constraint() -> None:
    item = _detection(0.92)
    assert item["direction"] == "unknown"
    assert item["weight"] == 0.25
    assert "未达到裁决约束阈值" in item["finding"]
    assert "不强制至少疑似欺诈" in item["finding"]


def test_related_tamper_supports_fake() -> None:
    item = _relevance(
        0.97,
        {
            "product_region_verdict": "suspected_ai",
            "tamper_relation_to_claim": "related",
            "tamper_location_summary": "杯身裂纹与破损边缘存在合成边界",
            "claim_relevance_reason": "篡改正落在客户主张的破损部位",
        },
    )
    assert item["direction"] == "supports_fake"
    assert item["weight"] == 0.9
    assert "直接相关" in item["finding"]


def test_extreme_score_unrelated_tamper_cannot_be_genuine() -> None:
    item = _relevance(
        0.97,
        {
            "product_region_verdict": "genuine",
            "tamper_relation_to_claim": "unrelated",
            "tamper_location_summary": "仅人脸磨皮与背景替换",
            "claim_relevance_reason": "商品主体与破损形态未被改动",
        },
    )
    assert item["direction"] == "unknown"
    assert item["weight"] == 0.55
    assert "不能据此认定诉求真实" in item["finding"]
    assert "至少为 suspicious" in item["finding"]


def test_between_thresholds_unrelated_tamper_can_support_genuine() -> None:
    item = _relevance(
        0.92,
        {
            "product_region_verdict": "genuine",
            "tamper_relation_to_claim": "unrelated",
            "tamper_location_summary": "仅人脸磨皮与背景替换",
            "claim_relevance_reason": "商品主体与破损形态未被改动",
        },
    )
    assert item["direction"] == "supports_genuine"
    assert item["weight"] == 0.45
    assert "未达到约束阈值" in item["finding"]
    assert "不计入欺诈风险" in item["finding"]


def test_unrelated_but_claim_region_uncertain_is_unknown() -> None:
    item = _relevance(
        0.97,
        {
            "product_region_verdict": "uncertain",
            "tamper_relation_to_claim": "unrelated",
            "tamper_location_summary": "人脸区域",
        },
    )
    assert item["direction"] == "unknown"
    assert "建议人工复核" in item["finding"]


def test_uncertain_high_score_never_direct_fake() -> None:
    item = _relevance(
        0.99,
        {
            "product_region_verdict": "genuine",
            "tamper_relation_to_claim": "uncertain",
            "tamper_location_summary": "",
        },
    )
    assert item["direction"] == "unknown"
    assert item["weight"] <= 0.55
    assert "不能判真实" in item["finding"]
    assert "至少判疑似欺诈" in item["finding"]


def test_parse_error_is_treated_as_uncertain() -> None:
    item = _relevance(0.99, {"parse_error": True, "raw": "..."})
    assert item["direction"] == "unknown"
    assert "人工复核" in item["finding"]


def test_between_thresholds_uncertain_has_no_hard_floor() -> None:
    item = _relevance(
        0.92,
        {
            "product_region_verdict": "genuine",
            "tamper_relation_to_claim": "uncertain",
            "tamper_location_summary": "",
        },
    )
    assert item["direction"] == "unknown"
    assert item["weight"] == 0.35
    assert "不强制至少疑似欺诈" in item["finding"]


def test_medical_background_ai_at_extreme_score_cannot_be_genuine() -> None:
    item = _relevance(
        0.96,
        {
            "tamper_suspected": False,
            "irrelevant_region_aigc": True,
            "tamper_relation_to_claim": "unrelated",
            "tamper_location_summary": "背景与拍摄环境",
        },
        scenario="medical_cert_claim",
    )
    assert item["direction"] == "unknown"
    assert "不能据此认定诉求真实" in item["finding"]


def test_medical_background_ai_between_thresholds_not_evidence_of_forgery() -> None:
    item = _relevance(
        0.92,
        {
            "tamper_suspected": False,
            "irrelevant_region_aigc": True,
            "tamper_relation_to_claim": "unrelated",
            "tamper_location_summary": "背景与拍摄环境",
        },
        scenario="medical_cert_claim",
    )
    assert item["direction"] == "supports_genuine"
    assert "不计入欺诈风险" in item["finding"]


def test_adjudicate_prompt_forbids_direct_high_score_conviction() -> None:
    prompt = load_prompt("adjudicate")
    assert "不能单独作为欺诈结论" in prompt
    assert "禁止仅凭 Sightengine 分数直接输出 fake_claim" in prompt
    assert "直接认定为 AI 生成" not in prompt
    assert "tamper_relation_to_claim" in prompt


def test_adjudicate_prompt_requires_suspicious_on_extreme_score() -> None:
    prompt = load_prompt("adjudicate")
    assert "不得为 likely_genuine，也不得为 inconclusive" in prompt
    assert "至少为 suspicious" in prompt
    assert "无法定位具体篡改位置" in prompt


def test_floor_overrides_likely_genuine_on_extreme_score() -> None:
    verdict = {
        "conclusion": "likely_genuine",
        "risk_level": "low",
        "confidence": 0.9,
        "summary": "商品区域看起来真实。",
        "recommended_actions": [],
    }
    evidence = [{"tool": "sightengine_detect", "raw_ref": {"score": 0.99}}]
    assert _enforce_sightengine_floor(verdict, evidence) is True
    assert verdict["conclusion"] == "suspicious"
    assert verdict["risk_level"] == "medium"
    assert verdict["confidence"] == 0.75
    assert "硬约束" in verdict["summary"]
    assert any(a.get("action") == "manual_review" for a in verdict["recommended_actions"])


def test_floor_ignores_non_extreme_or_non_genuine_verdicts() -> None:
    medium = {
        "conclusion": "likely_genuine",
        "risk_level": "low",
        "confidence": 0.8,
        "summary": "",
        "recommended_actions": [],
    }
    assert (
        _enforce_sightengine_floor(
            medium, [{"tool": "sightengine_detect", "raw_ref": {"score": 0.92}}]
        )
        is False
    )
    assert medium["conclusion"] == "likely_genuine"

    fraud = {
        "conclusion": "fake_claim",
        "risk_level": "high",
        "confidence": 0.8,
        "summary": "",
        "recommended_actions": [],
    }
    assert (
        _enforce_sightengine_floor(
            fraud, [{"tool": "sightengine_detect", "raw_ref": {"score": 0.99}}]
        )
        is False
    )
    assert fraud["conclusion"] == "fake_claim"


def test_prompt_files_exist_for_all_vision_scenarios() -> None:
    prompts = Path(__file__).resolve().parents[2] / "app" / "agent" / "prompts"
    for name in ("vision_product_damage.md", "vision_medical_doc.md", "vision_seeding.md"):
        text = (prompts / name).read_text(encoding="utf-8")
        assert "tamper_relation_to_claim" in text
        assert "tamper_location_summary" in text


def test_cached_payload_uses_current_thresholds() -> None:
    settings = Settings(
        sightengine_ai_threshold=0.90,
        sightengine_constraint_threshold=0.95,
    )
    data = _with_thresholds({"score": 0.92, "threshold": 0.50}, settings)
    assert data["consider_threshold"] == 0.90
    assert data["constraint_threshold"] == 0.95
    assert data["is_ai_generated"] is True
    assert data["is_high_confidence"] is False
