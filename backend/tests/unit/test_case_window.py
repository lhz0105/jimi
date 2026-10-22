"""触发窗口测试：图与文分开发送时，两个方向都要能触发。

场景（用户反馈）：
  A. 文本先到（"必须退款"），图片随后或稍后才发；
  B. 图片先到（客户直接甩图），退款意图写在之前的文本里。
窗口 = 最近 N 条消息；窗口内文本判意图，窗口内图片作证据。
"""

from __future__ import annotations

from app.services import demo_seed, demo_service
from app.services.case_window import load_window


async def _new_conversation(app_state, *, name: str = "测试") -> dict:
    return await demo_service.create_conversation(
        app_state, customer_name=name, channel="demo", mode="manual"
    )


async def test_window_gathers_text_and_image_within_5_messages(app_state) -> None:
    """文本在第 2 条、图片在第 4 条 —— 都在 5 条窗口内 → 触发高危。"""
    conv = await _new_conversation(app_state)
    await demo_service.post_message(
        app_state, conv["id"], role="customer", text="收到货了", attachment_ids=[]
    )
    await demo_service.post_message(
        app_state, conv["id"], role="customer", text="杯子碎了，必须退款！", attachment_ids=[]
    )
    await demo_service.post_message(app_state, conv["id"], role="agent", text="抱歉，我看下", attachment_ids=[])
    att, _ = await demo_service.store_image(
        app_state, conv["id"], demo_seed.make_damaged_product_image()
    )
    result = await demo_service.post_message(
        app_state, conv["id"], role="customer", text="照片在这", attachment_ids=[att["id"]]
    )

    analysis = result["analysis"]
    assert analysis["need_analysis"] is True
    assert analysis["window_size"] <= 5  # 窗口上限 5；本会话共 4 条
    assert analysis["image_count"] >= 1
    assert any(m["id"] == "refund_with_image" for m in analysis["matched_rules"])


async def test_image_first_then_text_intent_in_history(app_state) -> None:
    """图片先发（无文本），退款意图在历史文本里 —— 窗口回看仍能触发。"""
    conv = await _new_conversation(app_state)
    await demo_service.post_message(
        app_state, conv["id"], role="customer", text="东西不对，我要退货", attachment_ids=[]
    )
    att, _ = await demo_service.store_image(
        app_state, conv["id"], demo_seed.make_damaged_product_image()
    )
    result = await demo_service.post_message(
        app_state, conv["id"], role="customer", text="", attachment_ids=[att["id"]]
    )

    analysis = result["analysis"]
    assert analysis["need_analysis"] is True
    assert analysis["image_count"] >= 1
    # 图片消息本身无文本，靠窗口内历史文本触发
    rule_ids = {m["id"] for m in analysis["matched_rules"]}
    assert "refund_with_image" in rule_ids


async def test_image_first_with_semantic_history(app_state) -> None:
    """图片先发 + 历史文本无关键词但语义命中 → 语义规则兜底触发。"""
    from app.rules.semantic import SemanticMatcher
    from tests.unit.test_semantic import ScriptedEmbedder

    app_state.rules.set_semantic_matcher(  # type: ignore[union-attr]
        SemanticMatcher(
            ScriptedEmbedder({"要求退款": [1.0, 0.0, 0.0], "这个钱我不要了": [0.95, 0.05, 0.0]})
        )
    )
    conv = await _new_conversation(app_state)
    await demo_service.post_message(
        app_state, conv["id"], role="customer", text="这个钱我不要了", attachment_ids=[]
    )
    att, _ = await demo_service.store_image(
        app_state, conv["id"], demo_seed.make_damaged_product_image()
    )
    result = await demo_service.post_message(
        app_state, conv["id"], role="customer", text="", attachment_ids=[att["id"]]
    )

    analysis = result["analysis"]
    assert analysis["need_analysis"] is True
    assert analysis["semantic_status"] == "matched"
    assert "refund_intent" in analysis["semantic_hits"]
    rule_ids = {m["id"] for m in analysis["matched_rules"]}
    assert "refund_semantic_with_image" in rule_ids


async def test_image_outside_window_not_used(app_state) -> None:
    """图片超出窗口（更早的消息）→ 不计入本次证据（has_image=false 分支）。"""
    conv = await _new_conversation(app_state)
    att, _ = await demo_service.store_image(
        app_state, conv["id"], demo_seed.make_damaged_product_image()
    )
    await demo_service.post_message(
        app_state, conv["id"], role="customer", text="照片给你", attachment_ids=[att["id"]]
    )
    # 再发 5 条无关消息，把图片挤出 5 条窗口
    for i in range(5):
        await demo_service.post_message(
            app_state, conv["id"], role="agent", text=f"跟进第 {i + 1} 条", attachment_ids=[]
        )
    result = await demo_service.post_message(
        app_state, conv["id"], role="customer", text="东西又坏了，怎么回事", attachment_ids=[]
    )

    analysis = result["analysis"]
    assert analysis["image_count"] == 0  # 窗口内无图
    rule_ids = {m["id"] for m in analysis["matched_rules"]}
    assert rule_ids & {"damage_text_only", "damage_semantic_text_only"}
    assert "refund_with_image" not in rule_ids


async def test_window_snapshot_fields_for_run(app_state) -> None:
    """窗口信息写入 snapshot，供 prepare_case 取同一批图片。"""
    conv = await _new_conversation(app_state)
    att, _ = await demo_service.store_image(
        app_state, conv["id"], demo_seed.make_damaged_product_image()
    )
    await demo_service.post_message(
        app_state, conv["id"], role="customer", text="杯子碎了，退款", attachment_ids=[att["id"]]
    )
    _decision, window = await demo_service.check_conversation(app_state, conv["id"])
    fields = window.snapshot_fields()

    assert fields["image_attachment_ids"] == [att["id"]]
    assert fields["window_size"] >= 1
    assert fields["window_newest_seq"] >= fields["window_oldest_seq"]


async def test_load_window_limits_size(app_state) -> None:
    conv = await _new_conversation(app_state)
    for i in range(8):
        await demo_service.post_message(
            app_state, conv["id"], role="customer", text=f"消息 {i}", attachment_ids=[]
        )
    window = await load_window(app_state.db, conv["id"], window=5)
    assert len(window.messages) == 5
    assert window.messages[-1]["content"] == "消息 7"
    assert window.messages[0]["content"] == "消息 3"
