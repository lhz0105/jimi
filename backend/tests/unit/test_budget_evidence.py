"""预算闸门与证据 reducer 测试。"""

from __future__ import annotations

from app.agent import budget as budget_mod
from app.agent.evidence import EvidenceBuilder, make_evidence
from app.agent.state import merge_evidence
from app.config import Settings
from app.llm.pricing import load_prices


def _settings() -> Settings:
    return Settings(
        budget_max_llm_calls=3,
        budget_max_tool_calls=2,
        budget_max_vision_calls=1,
        budget_max_tavily_calls=1,
        budget_max_run_cost=10.0,
        budget_max_prompt_tokens=10000,
        pricing_main_input_per_1k=0.001,
        pricing_main_output_per_1k=0.002,
    )


def test_record_llm_accumulates_and_costs() -> None:
    settings = _settings()
    budget = budget_mod.new_budget(settings)
    prices = load_prices(settings)
    budget_mod.record_llm(
        budget, node="investigate", usage={"prompt_tokens": 1000, "completion_tokens": 500}, prices=prices
    )
    assert budget["llm_calls"] == 1
    assert budget["prompt_tokens"] == 1000
    assert budget["by_node"]["investigate"]["llm_calls"] == 1
    assert budget["est_cost"] == 0.002  # 1000/1000*0.001 + 500/1000*0.002


def test_llm_call_limit_blocks() -> None:
    settings = _settings()
    budget = budget_mod.new_budget(settings)
    prices = load_prices(settings)
    for _ in range(3):
        budget_mod.record_llm(budget, node="n", usage={}, prices=prices)
    assert budget_mod.llm_allowed(budget) is not None


def test_tool_limits_per_kind() -> None:
    settings = _settings()
    budget = budget_mod.new_budget(settings)
    budget_mod.record_tool(budget, "vision_analyze")
    assert budget_mod.tool_allowed(budget, "vision_analyze") is not None  # 识图上限 1
    budget_mod.record_tool(budget, "lookup_kb")
    assert budget_mod.tool_allowed(budget, "lookup_kb") is not None  # 总数上限 2


def test_cost_summary_shape() -> None:
    settings = _settings()
    budget = budget_mod.new_budget(settings)
    summary = budget_mod.cost_summary(budget)
    for key in ("llm_calls", "prompt_tokens", "tool_calls", "est_cost", "per_tool", "by_node"):
        assert key in summary


def test_evidence_builder_ids_and_dedupe() -> None:
    state: dict = {"_emitter": None, "evidence": []}
    builder = EvidenceBuilder(state)
    first = builder.add(
        category="metadata", source={"type": "image", "ref": "sha256:abc"}, tool="exif_check",
        finding="无 EXIF", direction="unknown", weight=0.2,
    )
    second = builder.add(
        category="aigc_artifact", source={"type": "image", "ref": "sha256:abc"}, tool="vision_analyze",
        finding="产品区疑似生成", direction="supports_fake", weight=0.85,
    )
    assert first["evidence_id"] == "ev_0001"
    assert second["evidence_id"] == "ev_0002"

    merged = merge_evidence([first], [first, second])
    assert [e["evidence_id"] for e in merged] == ["ev_0001", "ev_0002"]


def test_make_evidence_sanitizes() -> None:
    item = make_evidence(
        evidence_id="ev_0001",
        category="not_a_category",
        source={},
        tool="t",
        finding="f",
        direction="bogus",
        weight=2.5,
    )
    assert item["category"] == "customer_behavior"
    assert item["direction"] == "unknown"
    assert item["weight"] == 1.0
