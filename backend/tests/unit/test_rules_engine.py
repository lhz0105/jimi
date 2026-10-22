"""规则引擎测试：关键词/图片/渠道/负规则/优先级短路。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.rules.loader import RulesService


@pytest.fixture(scope="module")
def rules() -> RulesService:
    service = RulesService(Path(__file__).resolve().parents[2] / "app" / "rules" / "rules.yaml")
    service.load()
    return service


def test_refund_with_image_high_risk(rules: RulesService) -> None:
    decision = rules.decide(text="收到的货是碎的，必须退款！", image_count=1)
    assert decision.need_analysis is True
    assert decision.scenario == "product_damage_claim"
    assert decision.risk_hint == "high"
    assert decision.require_confirm is True
    assert any(m.id == "refund_with_image" for m in decision.matched_rules)


def test_medical_keywords(rules: RulesService) -> None:
    decision = rules.decide(text="用了你们的面霜我脸过敏烂脸了，医院诊断都开了", image_count=1)
    assert decision.need_analysis is True
    assert decision.scenario == "medical_cert_claim"


def test_logistics_only_negative_rule(rules: RulesService) -> None:
    decision = rules.decide(text="我的快递什么时候到？物流一直不更新", image_count=0)
    assert decision.need_analysis is False
    assert any(m.id == "logistics_only" for m in decision.matched_rules)


def test_logistics_with_refund_falls_through(rules: RulesService) -> None:
    """负规则含退款诉求时不成立，继续命中退款规则。"""
    decision = rules.decide(text="快递到了但东西碎了，我要退款", image_count=1)
    assert decision.need_analysis is True
    assert decision.scenario == "product_damage_claim"


def test_damage_text_only_medium(rules: RulesService) -> None:
    decision = rules.decide(text="杯子碎了，怎么处理？", image_count=0)
    assert decision.need_analysis is True
    assert decision.risk_hint == "medium"


def test_seeding_channel(rules: RulesService) -> None:
    decision = rules.decide(text="这个面霜真的绝了", image_count=1, channel="seed_post")
    assert decision.scenario == "seeding_post"
    assert decision.require_confirm is False


def test_seeding_keywords(rules: RulesService) -> None:
    decision = rules.decide(text="姐妹们我种草这家店了，亲测好用", image_count=1, channel="demo")
    assert decision.scenario == "seeding_post"


def test_no_match_defaults_to_no_analysis(rules: RulesService) -> None:
    decision = rules.decide(text="你好，请问有优惠券吗", image_count=0)
    assert decision.need_analysis is False
    assert decision.matched_rules == []


def test_synonym_normalization(rules: RulesService) -> None:
    """同义词（退钱→退款）应参与匹配。"""
    decision = rules.decide(text="东西坏了，退我钱", image_count=1)
    assert decision.need_analysis is True
    assert decision.scenario == "product_damage_claim"


def test_damage_synonym_covers_de_sui(rules: RulesService) -> None:
    """"是碎的" 也应归一到破损（演示剧本里的原始表述）。"""
    decision = rules.decide(text="今天拆开发现里面那瓶精华是碎的。", image_count=0)
    assert decision.need_analysis is True
    assert decision.scenario == "product_damage_claim"
    assert any(m.id == "damage_text_only" for m in decision.matched_rules)


def test_priority_ordering(rules: RulesService) -> None:
    """medical(110) 应优先于 refund_with_image(100)。"""
    decision = rules.decide(text="用坏了烂脸了，必须退款", image_count=1)
    assert decision.scenario == "medical_cert_claim"
    assert decision.matched_rules[0].id == "medical_doc_claim"


def test_full_match_list_recorded(rules: RulesService) -> None:
    decision = rules.decide(text="面霜过敏烂脸，要求退款赔偿", image_count=2)
    ids = {m.id for m in decision.matched_rules}
    assert "medical_doc_claim" in ids
    assert "refund_with_image" in ids  # 全部命中记录保留，首位为决策依据
