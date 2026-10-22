"""全链路测试（fake LLM）：三场景端到端 / 缓存命中 / 确认链 / 取消。"""

from __future__ import annotations

import asyncio

from app.db.repositories import events as events_repo
from app.db.repositories import reports as reports_repo
from app.services import demo_seed, demo_service
from tests.conftest import wait_for_run


async def _prepare_conversation(app_state, *, scenario: str, text: str) -> tuple[dict, dict]:
    conv = await demo_service.create_conversation(
        app_state, customer_name="测试客户", channel="demo", mode="manual"
    )
    image_factory = {
        "product_damage_claim": demo_seed.make_damaged_product_image,
        "medical_cert_claim": demo_seed.make_medical_doc_image,
        "seeding_post": demo_seed.make_seeding_post_image,
    }[scenario]
    att, _ = await demo_service.store_image(app_state, conv["id"], image_factory())
    message = await demo_service.post_message(
        app_state, conv["id"], role="customer", text=text, attachment_ids=[att["id"]]
    )
    return conv, message


async def _run(app_state, conv_id: str, scenario: str, analysis: dict) -> dict:
    run = await app_state.runner.start_run(
        conversation_id=conv_id,
        scenario=scenario,
        trigger_mode="manual",
        auto_confirm=True,
        rules_decision=analysis,
        input_snapshot={"test": True},
    )
    return await wait_for_run(app_state.db, run["id"])


async def test_product_damage_pipeline_end_to_end(app_state) -> None:
    conv, message = await _prepare_conversation(
        app_state, scenario="product_damage_claim", text="杯子碎成这样，必须退款！"
    )
    assert message["analysis"]["need_analysis"] is True

    final = await _run(app_state, conv["id"], "product_damage_claim", message["analysis"])
    assert final["status"] == "succeeded", final.get("error")

    report = await reports_repo.get_by_run(app_state.db, final["id"])
    assert report is not None
    payload = report["json"]
    assert payload["summary"]["conclusion"]
    assert len(payload["evidence_chain"]) >= 3
    assert payload["cost"]["llm_calls"] > 0
    assert payload["cost"]["vision_calls"] >= 1

    # 低危判定原则：无关区域 AIGC 的 neutral 证据存在且注明不计入风险
    neutral = [
        e for e in payload["evidence_chain"]
        if e["direction"] == "neutral" and "无关" in e["finding"]
    ]
    assert neutral, "缺少'无关区域 AIGC 不计入风险'的判定证据"

    events = await events_repo.list_after(app_state.db, final["id"], limit=1000)
    types = [e["type"] for e in events]
    assert types[0] == "run_queued"
    # prepare_case 的 node_start 先于其内部发出的 run_start
    assert types[1] == "node_start"
    assert "run_start" in types[:5]
    assert types[-1] == "run_end"
    for expected in ("node_start", "node_end", "thought", "llm_call", "llm_result", "tool_call", "tool_result", "evidence", "verdict", "report"):
        assert expected in types, f"缺少事件类型 {expected}"
    # Sightengine 预检必须先于识图定位
    node_starts = [e["node"] for e in events if e["type"] == "node_start"]
    assert node_starts.index("ai_image_detection") < node_starts.index("vision_analysis")
    # seq 单调
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))


async def test_medical_pipeline_consistency(app_state) -> None:
    conv, message = await _prepare_conversation(
        app_state,
        scenario="medical_cert_claim",
        text="用了你们面霜烂脸了，医院诊断是激素依赖性皮炎，必须赔偿",
    )
    final = await _run(app_state, conv["id"], "medical_cert_claim", message["analysis"])
    assert final["status"] == "succeeded", final.get("error")

    report = await reports_repo.get_by_run(app_state.db, final["id"])
    categories = {e["category"] for e in report["json"]["evidence_chain"]}
    assert "document_field" in categories
    assert "statement_contradiction" in categories  # fake 模型返回一处明确矛盾


async def test_seeding_pipeline(app_state) -> None:
    conv = await demo_service.create_conversation(
        app_state, customer_name="帖子", channel="seed_post", mode="manual"
    )
    att, _ = await demo_service.store_image(app_state, conv["id"], demo_seed.make_seeding_post_image())
    message = await demo_service.post_message(
        app_state,
        conv["id"],
        role="customer",
        text="姐妹们这款面霜绝了，无限回购，链接在评论区",
        attachment_ids=[att["id"]],
    )
    assert message["analysis"]["scenario"] == "seeding_post"

    final = await _run(app_state, conv["id"], "seeding_post", message["analysis"])
    assert final["status"] == "succeeded", final.get("error")
    report = await reports_repo.get_by_run(app_state.db, final["id"])
    categories = {e["category"] for e in report["json"]["evidence_chain"]}
    assert "marketing_pattern" in categories


async def test_vision_cache_hit_on_second_run(app_state) -> None:
    """同图同提示词第二次运行不得重复调用识图（成本压缩核心）。"""
    conv, message = await _prepare_conversation(
        app_state, scenario="product_damage_claim", text="杯子碎了，退款"
    )
    first = await _run(app_state, conv["id"], "product_damage_claim", message["analysis"])
    second = await _run(app_state, conv["id"], "product_damage_claim", message["analysis"])

    first_report = await reports_repo.get_by_run(app_state.db, first["id"])
    second_report = await reports_repo.get_by_run(app_state.db, second["id"])
    assert first_report["json"]["cost"]["vision_calls"] >= 1
    assert second_report["json"]["cost"]["vision_calls"] == 0, "第二次运行识图缓存未命中"


async def test_confirm_chain(app_state) -> None:
    conv, message = await _prepare_conversation(
        app_state, scenario="product_damage_claim", text="碎了，退款"
    )
    run = await app_state.runner.start_run(
        conversation_id=conv["id"],
        scenario="product_damage_claim",
        trigger_mode="auto",
        auto_confirm=False,  # 自动链：落 awaiting_confirm
        rules_decision=message["analysis"],
        input_snapshot={},
    )
    assert run["status"] == "awaiting_confirm"

    confirmed = await app_state.runner.confirm_run(run["id"], decided_by="test")
    assert confirmed["status"] in ("awaiting_confirm", "running", "succeeded")

    final = await wait_for_run(app_state.db, run["id"])
    assert final["status"] == "succeeded"

    events = await events_repo.list_after(app_state.db, run["id"], limit=1000)
    types = [e["type"] for e in events]
    assert "run_awaiting_confirm" in types
    assert "run_confirmed" in types


async def test_cancel_awaiting_run(app_state) -> None:
    conv, message = await _prepare_conversation(
        app_state, scenario="product_damage_claim", text="碎了，退款"
    )
    run = await app_state.runner.start_run(
        conversation_id=conv["id"],
        scenario="product_damage_claim",
        trigger_mode="auto",
        auto_confirm=False,
        rules_decision=message["analysis"],
        input_snapshot={},
    )
    cancelled = await app_state.runner.cancel_run(run["id"])
    assert cancelled["status"] == "cancelled"

    # 幂等：再次取消不报错
    again = await app_state.runner.cancel_run(run["id"])
    assert again["status"] == "cancelled"

    events = await events_repo.list_after(app_state.db, run["id"], limit=100)
    assert any(e["type"] == "run_end" and e["payload"]["status"] == "cancelled" for e in events)


async def test_idempotency_key(app_state) -> None:
    conv, message = await _prepare_conversation(
        app_state, scenario="product_damage_claim", text="碎了，退款"
    )
    first = await app_state.runner.start_run(
        conversation_id=conv["id"],
        scenario="product_damage_claim",
        trigger_mode="manual",
        auto_confirm=True,
        rules_decision=message["analysis"],
        input_snapshot={},
        idempotency_key="idem-001",
    )
    await wait_for_run(app_state.db, first["id"])
    second = await app_state.runner.start_run(
        conversation_id=conv["id"],
        scenario="product_damage_claim",
        trigger_mode="manual",
        auto_confirm=True,
        rules_decision=message["analysis"],
        input_snapshot={},
        idempotency_key="idem-001",
    )
    assert second["id"] == first["id"]


async def test_callback_push_on_success(app_state) -> None:
    """完成时向 callback_url 回推报告摘要（真实 HTTP 回环，验证回推格式与容错）。"""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    received: list[dict] = []

    class _Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", 0))
            received.append(json.loads(self.rfile.read(length).decode("utf-8")))
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *args) -> None:  # 静默
            pass

    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conv, message = await _prepare_conversation(
            app_state, scenario="product_damage_claim", text="杯子碎了，退款"
        )
        run = await app_state.runner.start_run(
            conversation_id=conv["id"],
            scenario="product_damage_claim",
            trigger_mode="manual",
            auto_confirm=True,
            rules_decision=message["analysis"],
            input_snapshot={},
            callback_url=f"http://127.0.0.1:{server.server_port}/hook",
        )
        final = await wait_for_run(app_state.db, run["id"])
        assert final["status"] == "succeeded"

        for _ in range(50):  # 回推在 finalize 内同步完成，留少量等待余量
            if received:
                break
            await asyncio.sleep(0.05)
        assert received, "未收到 callback 回推"
        payload = received[0]
        assert payload["run_id"] == final["id"]
        assert payload["status"] == "succeeded"
        assert payload["conclusion"]
        assert "cost" in payload
    finally:
        server.shutdown()
