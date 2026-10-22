"""先前案例 Beta 反馈加权与人工意图推断。"""

from __future__ import annotations

import pytest

from app.core.ids import new_id
from app.db.repositories import prior_cases as prior_cases_repo
from app.db.repositories import reports as reports_repo
from app.db.repositories import reviews as reviews_repo
from app.db.repositories import runs as runs_repo
from app.deps import AppState
from app.services.prior_case_service import PriorCaseService
from app.services.review_service import ReviewService


async def _make_case(db) -> dict:  # type: ignore[no-untyped-def]
    old_run = new_id("run")
    await runs_repo.create(
        db,
        run_id=old_run,
        conversation_id=None,
        scenario="product_damage_claim",
        trigger_mode="manual",
        status="succeeded",
        rules_decision={},
        input_snapshot={"text_digest": "旧案例"},
    )
    old_review = await reviews_repo.create(
        db,
        run_id=old_run,
        verdict="fraud",
        reason="旧案例判决",
        reviewer="测试员",
    )
    return await prior_cases_repo.create(
        db,
        review_id=old_review["id"],
        run_id=old_run,
        title="测试先例",
        scenario="product_damage_claim",
        human_verdict="fraud",
        markdown="# 测试先例\n\n## 案件定义\n测试\n## 案件细节\n测试\n## 判决原因\n测试\n",
    )


@pytest.mark.asyncio
async def test_beta_updates_and_idempotency(db) -> None:  # type: ignore[no-untyped-def]
    case = await _make_case(db)
    assert case["reliability"] == 0.5

    fb = await prior_cases_repo.add_feedback(
        db,
        case_id=case["id"],
        run_id="run_new",
        review_id="rev_new",
        signal="adopted",
        confidence=0.9,
        rationale="人工依赖该先例",
        evidence_ids=["ev_0001"],
        alpha_delta=1.0,
    )
    assert fb is not None
    updated = await prior_cases_repo.get(db, case["id"])
    assert updated is not None
    assert updated["alpha"] == 3.0
    assert updated["beta"] == 2.0
    assert updated["reliability"] == 0.6
    assert updated["adopted_count"] == 1

    duplicate = await prior_cases_repo.add_feedback(
        db,
        case_id=case["id"],
        run_id="run_new",
        review_id="rev_new",
        signal="overturned",
        confidence=0.9,
        rationale="重复推断",
        evidence_ids=["ev_0001"],
        beta_delta=1.0,
    )
    assert duplicate is not None
    assert duplicate["signal"] == "adopted"
    unchanged = await prior_cases_repo.get(db, case["id"])
    assert unchanged is not None
    assert unchanged["alpha"] == 3.0
    assert unchanged["beta"] == 2.0

    await prior_cases_repo.add_feedback(
        db,
        case_id=case["id"],
        run_id="run_3",
        review_id="rev_3",
        signal="overturned",
        confidence=0.8,
        rationale="人工认为先例判错",
        evidence_ids=["ev_0002"],
        beta_delta=1.0,
    )
    final = await prior_cases_repo.get(db, case["id"])
    assert final is not None
    assert final["alpha"] == 3.0
    assert final["beta"] == 3.0
    assert final["reliability"] == 0.5
    history = await prior_cases_repo.list_feedback(db, case["id"])
    assert len(history) == 2
    assert history[0]["weight_before"] == 0.5
    assert history[0]["weight_after"] == 0.6


@pytest.mark.asyncio
async def test_delete_prior_case_cleans_feedback_and_resets_review(db) -> None:  # type: ignore[no-untyped-def]
    case = await _make_case(db)
    await reviews_repo.update(
        db, case["review_id"], status="generated", generated_at=123
    )
    await prior_cases_repo.add_feedback(
        db,
        case_id=case["id"],
        run_id="run_new",
        review_id="rev_feedback",
        signal="adopted",
        confidence=0.9,
        rationale="删除前反馈",
        evidence_ids=["ev_0001"],
        alpha_delta=1.0,
    )

    deleted = await prior_cases_repo.delete(db, case["id"])
    assert deleted is not None
    assert deleted["id"] == case["id"]
    assert deleted["review_reset"] is True
    assert await prior_cases_repo.get(db, case["id"]) is None
    assert await prior_cases_repo.list_feedback(db, case["id"]) == []

    review = await reviews_repo.get(db, case["review_id"])
    assert review is not None
    assert review["status"] == "in_dialogue"
    assert review["generated_at"] is None
    assert await prior_cases_repo.delete(db, case["id"]) is None


@pytest.mark.asyncio
async def test_prior_case_service_delete_case_cleans_memory_index(settings, db) -> None:  # type: ignore[no-untyped-def]
    service = PriorCaseService(settings, db)
    service._chunks = [
        {"id": "case_x:c0", "case_id": "case_x"},
        {"id": "case_y:c0", "case_id": "case_y"},
    ]
    removed = await service.delete_case("case_x")
    assert removed == 1
    assert [item["id"] for item in service._chunks] == ["case_y:c0"]


@pytest.mark.asyncio
async def test_review_infers_cited_case_feedback(settings, db, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    old_case = await _make_case(db)
    run_id = new_id("run")
    await runs_repo.create(
        db,
        run_id=run_id,
        conversation_id=None,
        scenario="product_damage_claim",
        trigger_mode="manual",
        status="succeeded",
        rules_decision={},
        input_snapshot={"text_digest": "客户要求退款"},
    )
    verdict = {
        "conclusion": "suspicious",
        "risk_level": "medium",
        "confidence": 0.6,
        "summary": "测试",
        "evidence_refs": ["ev_0001", "ev_0002"],
    }
    await runs_repo.set_verdict(db, run_id, verdict, risk_level="medium", confidence=0.6)
    await runs_repo.set_review_required(db, run_id, True)
    await reports_repo.upsert(
        db,
        run_id=run_id,
        report={
            "evidence_chain": [
                {
                    "evidence_id": "ev_0001",
                    "tool": "prior_case_recall",
                    "source": {"type": "prior_case", "ref": old_case["id"]},
                    "raw_ref": {"case_id": old_case["id"]},
                    "finding": "先例说该图是 AI 生成",
                },
                {
                    "evidence_id": "ev_0002",
                    "tool": "prior_case_recall",
                    "source": {"type": "prior_case", "ref": "other"},
                    "raw_ref": {"case_id": "other"},
                    "finding": "未被引用的先例",
                },
            ]
        },
        markdown="# 报告",
    )
    review = await reviews_repo.create(
        db,
        run_id=run_id,
        verdict="fraud",
        reason="采纳先例的图片复用判断",
        reviewer="测试员",
    )
    await reviews_repo.add_message(
        db, review_id=review["id"], role="human", content="人工判决：欺诈"
    )
    service = ReviewService(AppState(settings=settings, db=db))

    async def fake_invoke(prompt_name: str, payload: str, usage: dict):
        usage.update({"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
        return (
            {
                "feedback": [
                    {
                        "case_id": old_case["id"],
                        "outcome": "adopted",
                        "confidence": 0.9,
                        "rationale": "人工依赖该先例的复用判断",
                    }
                ]
            },
            "{}",
        )

    monkeypatch.setattr(service, "_invoke_json", fake_invoke)
    run = await runs_repo.get(db, run_id)
    assert run is not None
    cited = await service._cited_prior_cases(run)
    assert len(cited) == 1
    feedback = await service._apply_prior_case_feedback(run, review, cited)
    assert len(feedback) == 1
    assert feedback[0]["signal"] == "adopted"
    assert feedback[0]["weight_before"] == 0.5
    assert feedback[0]["weight_after"] == 0.6
    updated = await prior_cases_repo.get(db, old_case["id"])
    assert updated is not None
    assert updated["alpha"] == 3.0
