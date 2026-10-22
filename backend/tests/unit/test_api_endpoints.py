"""API 级测试（TestClient，fake LLM）：鉴权/接口形状/错误信封/演示平台/管理面板。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings

pytestmark = pytest.mark.usefixtures("_api_env")


@pytest.fixture
def _api_env(tmp_path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "app.db",
        upload_dir=tmp_path / "data" / "uploads",
        workspace_dir=tmp_path / "data" / "workspace",
        report_dir=tmp_path / "data" / "reports",
        chroma_dir=tmp_path / "data" / "chroma",
        embedding_cache_dir=tmp_path / "data" / "models",
        kb_dir=tmp_path / "data" / "kb",
        kb_seed_dir=tmp_path / "kb_seed_absent",
        kb_enabled=False,
        prior_case_enabled=False,
        llm_mode="fake",
        demo_seed_on_start=False,
        event_flush_interval_ms=10,
    )
    import app.main as main_module

    monkeypatch.setattr(main_module, "get_settings", lambda: settings)


@pytest.fixture
def client(_api_env):
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/api/admin/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["runner_ready"] is True


def test_check_inline_requires_payload(client: TestClient) -> None:
    response = client.post("/api/v1/analyze/check", json={})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "APP_ERROR"


def test_check_inline_refund_with_image(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze/check",
        json={
            "inline": {
                "messages": [{"role": "customer", "text": "收到的货是碎的，必须退款！"}],
                "images": [{"url": "https://example.com/broken.jpg"}],
                "channel": "demo",
            }
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["need_analysis"] is True
    assert body["scenario"] == "product_damage_claim"
    assert body["decision_id"].startswith("dec_")
    assert body["matched_rules"][0]["id"] == "refund_with_image"
    assert body["message"].startswith("建议开始分析")


def test_check_value_error_envelope(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyze/check", json={"inline": {"messages": "not-a-list"}}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_demo_conversation_flow(client: TestClient) -> None:
    created = client.post(
        "/api/demo/conversations",
        json={"customer_name": "张三", "channel": "demo", "mode": "manual"},
    )
    assert created.status_code == 200
    conv_id = created.json()["id"]

    # 一键灌入演示剧本（含占位图片，不触发分析）
    seeded = client.post(
        f"/api/demo/conversations/{conv_id}/seed",
        params={"scenario": "product_damage_claim"},
    )
    assert seeded.status_code == 200
    seed_body = seeded.json()
    assert seed_body["messages_created"] >= 3
    assert seed_body["attachments_created"] >= 1
    assert seed_body["hint"]["need_analysis"] is True

    detail = client.get(f"/api/demo/conversations/{conv_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert len(body["messages"]) >= 3
    assert len(body["attachments"]) >= 1
    assert body["attachments"][0]["url"].startswith("/files/")

    # 图片静态服务
    url = body["attachments"][0]["url"]
    image = client.get(url)
    assert image.status_code == 200
    assert image.headers["content-type"].startswith("image/")


def test_upload_and_message_triggers_check(client: TestClient) -> None:
    conv_id = client.post(
        "/api/demo/conversations", json={"customer_name": "李四", "mode": "manual"}
    ).json()["id"]

    from app.services.demo_seed import make_damaged_product_image

    data = make_damaged_product_image()
    upload = client.post(
        f"/api/demo/conversations/{conv_id}/upload",
        files={"file": ("broken.png", data, "image/png")},
    )
    assert upload.status_code == 200
    att = upload.json()
    assert att["mime"] == "image/png"
    assert len(att["sha256"]) == 64

    # 重复上传：去重
    again = client.post(
        f"/api/demo/conversations/{conv_id}/upload",
        files={"file": ("broken2.png", data, "image/png")},
    )
    assert again.json()["deduplicated"] is True

    message = client.post(
        f"/api/demo/conversations/{conv_id}/messages",
        json={"role": "customer", "text": "杯子碎了，必须退款！", "attachment_ids": [att["attachment_id"]]},
    )
    assert message.status_code == 200
    body = message.json()
    assert body["analysis"]["need_analysis"] is True
    assert body["analysis"]["run_id"] is None  # manual 模式不自动启动


def test_runs_roleback_when_no_scenario(client: TestClient) -> None:
    conv_id = client.post(
        "/api/demo/conversations", json={"customer_name": "王五", "mode": "manual"}
    ).json()["id"]
    # 无规则命中且未显式指定 scenario → 400
    response = client.post(
        "/api/v1/analyze/runs", json={"conversation_id": conv_id, "trigger_mode": "manual"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "APP_ERROR"


def test_full_run_via_api_and_admin_observability(client: TestClient) -> None:
    conv_id = client.post(
        "/api/demo/conversations", json={"customer_name": "赵六", "mode": "manual"}
    ).json()["id"]
    client.post(
        f"/api/demo/conversations/{conv_id}/seed", params={"scenario": "product_damage_claim"}
    )

    started = client.post(
        f"/api/demo/conversations/{conv_id}/trigger-analysis",
        json={"trigger_mode": "manual", "auto_confirm": True},
    )
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    # 轮询直至终态
    import time

    status = None
    for _ in range(200):
        body = client.get(f"/api/v1/analyze/runs/{run_id}").json()
        status = body["status"]
        if status in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.05)
    assert status == "succeeded", body

    report = client.get(f"/api/v1/analyze/runs/{run_id}/report")
    assert report.status_code == 200
    payload = report.json()
    assert payload["summary"]["conclusion"]
    assert payload["evidence_chain"]
    assert payload["cost"]["llm_calls"] > 0

    markdown = client.get(
        f"/api/v1/analyze/runs/{run_id}/report", params={"format": "markdown"}
    )
    assert markdown.status_code == 200
    assert "# 分析报告" in markdown.text

    # 管理面板：事件历史 / 工具调用 / 运行详情 / 统计
    events = client.get(f"/api/admin/runs/{run_id}/events", params={"limit": 500}).json()
    types = {e["type"] for e in events["items"]}
    assert {"run_start", "evidence", "verdict", "report", "run_end"} <= types

    tool_calls = client.get(f"/api/admin/runs/{run_id}/tool-calls").json()
    assert tool_calls["items"]

    detail = client.get(f"/api/admin/runs/{run_id}").json()
    assert detail["run"]["status"] == "succeeded"
    assert detail["event_counts"]["evidence"] >= 1

    stats = client.get("/api/admin/stats").json()
    assert stats["totals"]["runs"] >= 1
    assert stats["totals"]["est_cost"] >= 0

    listing = client.get("/api/admin/runs").json()
    assert any(item["run_id"] == run_id for item in listing["items"])


def test_rules_and_config_endpoints(client: TestClient) -> None:
    rules = client.get("/api/admin/rules")
    assert rules.status_code == 200
    assert "refund_with_image" in rules.json()["yaml"]

    reloaded = client.post("/api/admin/rules/reload")
    assert reloaded.status_code == 200
    assert reloaded.json()["rules"] >= 4

    snapshot = client.get("/api/admin/config").json()
    assert snapshot["llm_mode"] == "fake"
    assert "***" in snapshot["llm_main"]["api_key"] or snapshot["llm_main"]["api_key"] == ""


def test_cancel_is_idempotent_via_api(client: TestClient) -> None:
    conv_id = client.post(
        "/api/demo/conversations", json={"customer_name": "钱七", "mode": "manual"}
    ).json()["id"]
    client.post(
        f"/api/demo/conversations/{conv_id}/seed", params={"scenario": "product_damage_claim"}
    )
    run_id = client.post(
        f"/api/demo/conversations/{conv_id}/trigger-analysis",
        json={"trigger_mode": "manual", "auto_confirm": True},
    ).json()["run_id"]

    first = client.post(f"/api/v1/analyze/runs/{run_id}/cancel")
    assert first.status_code == 200
    second = client.post(f"/api/v1/analyze/runs/{run_id}/cancel")
    assert second.status_code == 200
    assert second.json()["status"] in ("cancelled", "succeeded")


def test_unknown_run_404(client: TestClient) -> None:
    response = client.get("/api/v1/analyze/runs/run_notexist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
