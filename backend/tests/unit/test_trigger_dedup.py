"""触发去重测试：同一诉求在持续消息下不重复建运行。

覆盖：重复消息 / 补图 / 客户续聊 / 客服消息 / 进行中运行复用 / 手动强制 /
失败重试 / 冷却期到期 / 语义分数波动不影响指纹。
"""

from __future__ import annotations

from app.core.clock import now_ms
from app.db.repositories import runs as runs_repo
from app.db.repositories import trigger_state as trigger_state_repo
from app.rules.models import Decision, MatchedRule
from app.services import demo_seed, demo_service
from app.services.case_window import load_window
from app.services.trigger_service import compute_signature, guard_and_start
from tests.conftest import wait_for_run


async def _auto_conversation(app_state, *, name: str = "去重") -> dict:
    return await demo_service.create_conversation(
        app_state, customer_name=name, channel="demo", mode="auto"
    )


async def _post(app_state, conv_id: str, text: str, att_ids: list[str] | None = None) -> dict:
    result = await demo_service.post_message(
        app_state, conv_id, role="customer", text=text, attachment_ids=att_ids or []
    )
    return result["analysis"]


async def _post_and_finish(
    app_state, conv_id: str, text: str, att_ids: list[str] | None = None
) -> dict:
    """发消息 → 确认（自动链默认停在待确认）→ 等待运行结束，返回 analysis。"""
    analysis = await _post(app_state, conv_id, text, att_ids)
    if analysis.get("run_id"):
        run = await runs_repo.get(app_state.db, analysis["run_id"])
        if run is not None and run["status"] == "awaiting_confirm":
            await app_state.runner.confirm_run(analysis["run_id"])
    if analysis.get("run_id"):
        await wait_for_run(app_state.db, analysis["run_id"])
    return analysis


async def _run_count(app_state, conv_id: str) -> int:
    rows = await app_state.db.fetchall(
        "SELECT COUNT(*) AS n FROM analysis_runs WHERE conversation_id = ?", (conv_id,)
    )
    return int(rows[0]["n"])


async def test_repeated_message_does_not_create_second_run(app_state) -> None:
    conv = await _auto_conversation(app_state)
    first = await _post_and_finish(app_state, conv["id"], "杯子碎了，必须退款")
    assert first["trigger"]["action"] == "start"
    first_run = first["run_id"]

    second = await _post(app_state, conv["id"], "杯子碎了，必须退款")
    assert second["trigger"]["action"] == "skip"
    assert second["trigger"]["reason"] == "same_signature"
    assert second["run_id"] == first_run  # 返回既有运行供前端跳转
    assert await _run_count(app_state, conv["id"]) == 1


async def test_customer_followup_skipped_within_ttl(app_state) -> None:
    conv = await _auto_conversation(app_state)
    first = await _post_and_finish(app_state, conv["id"], "杯子碎了，必须退款")

    followup = await _post(app_state, conv["id"], "在吗？什么时候处理")
    assert followup["trigger"]["action"] == "skip"
    assert await _run_count(app_state, conv["id"]) == 1


async def test_agent_message_never_triggers(app_state) -> None:
    conv = await _auto_conversation(app_state)
    first = await _post_and_finish(app_state, conv["id"], "杯子碎了，必须退款")

    result = await demo_service.post_message(
        app_state, conv["id"], role="agent", text="抱歉，我们马上处理", attachment_ids=[]
    )
    assert result["analysis"] is None
    assert await _run_count(app_state, conv["id"]) == 1


async def test_new_image_creates_supplementary_run(app_state) -> None:
    """先文字（无图）→ 分析；补图后证据变化 → 允许补充分析。"""
    conv = await _auto_conversation(app_state)
    first = await _post_and_finish(app_state, conv["id"], "杯子碎了，必须退款")
    assert first["risk_hint"] == "medium"

    att, _ = await demo_service.store_image(
        app_state, conv["id"], demo_seed.make_damaged_product_image()
    )
    second = await _post(app_state, conv["id"], "照片给你", [att["id"]])

    assert second["trigger"]["action"] == "start"
    assert second["trigger"]["signature"] != first["trigger"]["signature"]
    assert second["risk_hint"] == "high"
    assert await _run_count(app_state, conv["id"]) == 2


async def test_active_run_is_reused(app_state) -> None:
    """规则要求确认 → 首个运行停在 awaiting_confirm，后续消息复用而不是新建。"""
    conv = await _auto_conversation(app_state)
    first = await _post(app_state, conv["id"], "杯子碎了，必须退款")
    assert first["trigger"]["action"] == "start"

    run = await runs_repo.get(app_state.db, first["run_id"])
    assert run is not None and run["status"] == "awaiting_confirm"

    second = await _post(app_state, conv["id"], "在吗")
    assert second["trigger"]["action"] == "reuse"
    assert second["run_id"] == first["run_id"]
    assert await _run_count(app_state, conv["id"]) == 1


async def test_manual_force_bypasses_signature_dedup(app_state) -> None:
    conv = await _auto_conversation(app_state)
    first = await _post_and_finish(app_state, conv["id"], "杯子碎了，必须退款")

    decision, window = await demo_service.check_conversation(app_state, conv["id"])
    decision.need_analysis = True
    decision.scenario = "product_damage_claim"
    outcome = await guard_and_start(
        app_state,
        conversation_id=conv["id"],
        decision=decision,
        window=window,
        trigger_mode="manual",
        auto_confirm=True,
        force=True,
    )
    assert outcome.action == "start"
    assert await _run_count(app_state, conv["id"]) == 2


async def test_failed_run_allows_retry(app_state) -> None:
    # 用 manual 会话：发消息不自动建 run，便于构造"失败历史"
    conv = await demo_service.create_conversation(
        app_state, customer_name="失败重试", channel="demo", mode="manual"
    )
    await _post(app_state, conv["id"], "杯子碎了，必须退款")
    decision, window = await demo_service.check_conversation(app_state, conv["id"])
    assert decision.need_analysis is True
    signature = compute_signature(decision, window)

    # 制造一条"失败"的历史运行 + 对应指纹
    failed = await runs_repo.create(
        app_state.db,
        run_id="run_failedtest",
        conversation_id=conv["id"],
        scenario="product_damage_claim",
        trigger_mode="auto",
        status="failed",
        rules_decision=decision.model_dump(),
        input_snapshot={},
    )
    await trigger_state_repo.upsert(
        app_state.db,
        conversation_id=conv["id"],
        run_id=failed["id"],
        signature=signature,
        last_message_seq=0,
    )

    outcome = await guard_and_start(
        app_state,
        conversation_id=conv["id"],
        decision=decision,
        window=await load_window(app_state.db, conv["id"], window=5),
        trigger_mode="auto",
        auto_confirm=True,
    )
    assert outcome.action == "start"


async def test_ttl_expiry_allows_retrigger(app_state) -> None:
    conv = await _auto_conversation(app_state)
    first = await _post_and_finish(app_state, conv["id"], "杯子碎了，必须退款")

    # 把冷却期起点拨回到 TTL 之前（默认 30 分钟）
    await app_state.db.execute(
        "UPDATE conversation_trigger_state SET last_triggered_at = ? WHERE conversation_id = ?",
        (now_ms() - 31 * 60_000, conv["id"]),
    )
    again = await _post(app_state, conv["id"], "你们到底退不退")
    assert again["trigger"]["action"] == "start"
    assert await _run_count(app_state, conv["id"]) == 2


def test_signature_ignores_semantic_score_fluctuation() -> None:
    """同一命中但相似度微变（0.907→0.912）→ 指纹不变，不会重复触发。"""

    class _Window:
        attachments: list[dict] = []

    def decision(score: float) -> Decision:
        return Decision(
            need_analysis=True,
            scenario="product_damage_claim",
            require_confirm=True,
            matched_rules=[
                MatchedRule(
                    id="refund_semantic_with_image",
                    priority=98,
                    scenario="product_damage_claim",
                    hits=[f"any_semantic:refund_intent({score:.3f})", "has_image:true"],
                )
            ],
            rules_version="test",
        )

    sig_a = compute_signature(decision(0.9072), _Window())  # type: ignore[arg-type]
    sig_b = compute_signature(decision(0.9121), _Window())  # type: ignore[arg-type]
    assert sig_a == sig_b


def test_signature_changes_with_images() -> None:
    class _Window:
        def __init__(self, shas: list[str]) -> None:
            self.attachments = [{"sha256": s} for s in shas]

    decision = Decision(
        need_analysis=True,
        scenario="product_damage_claim",
        matched_rules=[MatchedRule(id="refund_with_image", priority=100, hits=["has_image:true"])],
    )
    assert compute_signature(decision, _Window([])) != compute_signature(decision, _Window(["a"]))
    assert compute_signature(decision, _Window(["a"])) == compute_signature(decision, _Window(["a"]))
