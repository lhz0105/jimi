"""人工复核状态机、流式输出、案例生成与先前案例切块。"""

from __future__ import annotations

import pytest

from app.core.errors import AppError, ConflictError
from app.core.ids import new_id
from app.db.repositories import runs as runs_repo
from app.deps import AppState
from app.services.prior_case_service import PriorCaseService
from app.services.review_policy import requires_review
from app.services.review_service import ReviewService

_META_SENTINEL = "---META---"

_CASE_MD = """# AI 破损图索赔先例

- **场景**：产品破损索赔
- **系统结论**：fake_claim / critical
- **人工判决**：欺诈
- **复核人**：测试员

## 案件定义
商品破损索赔中，图片被第三方检测判为 AI 生成的案件。

## 案件细节
客户称运输挤烂，提交玻璃罐破损图；识图判真实，Sightengine 判 0.99。

## 判决原因
第三方检测基于不可见水印，且客户拒绝提供原图。

## 关键证据
- Sightengine 0.99
- 客户拒绝提供原图

## 适用边界
适用于高置信度第三方 AI 检测且无直接反证的情况。

## 标签
破损、AIGC、高置信
"""


def test_review_policy() -> None:
    assert requires_review({"conclusion": "suspicious"})
    assert requires_review({"conclusion": "fake_claim"})
    assert requires_review(
        {"conclusion": "likely_genuine", "recommended_actions": [{"action": "manual_review"}]}
    )
    assert requires_review(
        {"conclusion": "likely_genuine", "recommended_actions": ["manual_review"]}
    )
    assert not requires_review(
        {"conclusion": "likely_genuine", "recommended_actions": ["accept_claim"]}
    )
    assert not requires_review(None)


async def _make_run(db, *, conclusion: str, required: bool) -> str:  # type: ignore[no-untyped-def]
    run_id = new_id("run")
    await runs_repo.create(
        db,
        run_id=run_id,
        conversation_id=None,
        scenario="product_damage_claim",
        trigger_mode="manual",
        status="succeeded",
        rules_decision={},
        input_snapshot={"text_digest": "客户：收到的商品碎了，要求退款"},
    )
    verdict = {
        "conclusion": conclusion,
        "risk_level": "medium",
        "confidence": 0.6,
        "summary": "测试结论",
        "evidence_refs": ["ev_0001"],
        "recommended_actions": [],
    }
    await runs_repo.set_verdict(
        db, run_id, verdict, risk_level="medium", confidence=0.6
    )
    await runs_repo.set_review_required(db, run_id, required)
    return run_id


@pytest.mark.asyncio
async def test_review_flow_streams_and_generates_case(settings, db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run_id = await _make_run(db, conclusion="suspicious", required=True)
    service = ReviewService(AppState(settings=settings, db=db))
    calls = {"interview": 0}

    async def fake_stream(prompt_name: str, payload: str, usage: dict):
        usage.update(
            {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        )
        if prompt_name == "review_interview":
            calls["interview"] += 1
            if calls["interview"] == 1:
                yield "1. 哪条证据最关键？\n"
                yield _META_SENTINEL
                yield '\n{"ready": false}'
            else:
                yield "已理解，可以生成案例。\n"
                yield _META_SENTINEL
                yield '\n{"ready": true}'
        else:
            yield _CASE_MD

    monkeypatch.setattr(service, "_stream_text", fake_stream)

    state = await service.start(
        run_id, verdict="fraud", reason="图片为 AI 生成", reviewer="测试员"
    )
    assert state["review"]["status"] == "in_dialogue"
    assert state["review"]["agent_turns"] == 1
    assert len(state["messages"]) == 2
    assert "哪条证据最关键" in state["messages"][-1]["content"]

    state = await service.add_message(run_id, "Sightengine 的 0.99 最关键")
    assert state["review"]["status"] == "generated"
    assert state["case"] is not None
    markdown = state["case"]["markdown"]
    assert "## 判决原因" in markdown
    assert "## 案件定义" in markdown
    assert "## 案件细节" in markdown
    assert "Sightengine 0.99" in markdown
    assert state["case"]["title"] == "AI 破损图索赔先例"
    assert state["review"]["agent_turns"] == 2
    assert state["review"]["llm_usage"]["est_cost"] > 0

    with pytest.raises(ConflictError):
        await service.start(run_id, verdict="fraud", reason="重复", reviewer="")


@pytest.mark.asyncio
async def test_review_stream_events(settings, db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    run_id = await _make_run(db, conclusion="suspicious", required=True)
    service = ReviewService(AppState(settings=settings, db=db))

    async def fake_stream(prompt_name: str, payload: str, usage: dict):
        usage.update({"input_tokens": 5, "output_tokens": 2, "total_tokens": 7})
        if prompt_name == "review_interview":
            yield "已理解，可以生成案例。\n"
            yield _META_SENTINEL
            yield '{"ready": true}'
        else:
            yield _CASE_MD

    monkeypatch.setattr(service, "_stream_text", fake_stream)
    events = [
        event
        async for event in service.stream_start(
            run_id, verdict="genuine", reason="图片与物流记录一致", reviewer="测试员"
        )
    ]
    kinds = [event["event"] for event in events]
    assert "status" in kinds
    assert "token" in kinds
    assert kinds[-1] == "state"
    assert any(
        event["event"] == "token" and event["data"].get("kind") == "case"
        for event in events
    )
    assert events[-1]["data"]["review"]["status"] == "generated"


@pytest.mark.asyncio
async def test_review_rejects_ineligible_run(settings, db) -> None:  # type: ignore[no-untyped-def]
    run_id = await _make_run(db, conclusion="likely_genuine", required=False)
    service = ReviewService(AppState(settings=settings, db=db))
    with pytest.raises(AppError):
        await service.start(run_id, verdict="genuine", reason="系统判真", reviewer="测试员")


def test_prior_case_chunks_keep_metadata(settings, db) -> None:  # type: ignore[no-untyped-def]
    service = PriorCaseService(settings, db)
    markdown = "# 先例\n\n## 案件定义\n这是一段足够长的案件定义，用于验证分块结果。\n\n## 判决原因\n人工认为该图片是 AI 生成的，需要重点关注。\n"
    chunks = service._case_chunks(
        {
            "id": "case_test",
            "title": "测试先例",
            "scenario": "product_damage_claim",
            "human_verdict": "fraud",
            "markdown": markdown,
        }
    )
    assert chunks
    assert all(c["case_id"] == "case_test" for c in chunks)
    assert all(c["human_verdict"] == "fraud" for c in chunks)
    assert chunks[0]["id"].startswith("case_test:c")
