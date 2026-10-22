"""语义触发通道测试：子句切分、最大相似度、阈值过滤、降级。

用可预测的 ScriptedEmbedder（按文本精确映射向量）验证机制本身；
中文语料的真实阈值标定依赖本地 BGE 模型，见 rules.yaml 注释与运行期实测。
"""

from __future__ import annotations

from pathlib import Path

from app.rules.loader import RulesService, semantic_level
from app.rules.semantic import SemanticMatcher, split_clauses

RULES_PATH = Path(__file__).resolve().parents[2] / "app" / "rules" / "rules.yaml"


class ScriptedEmbedder:
    """按文本精确映射向量；未登记文本生成确定性的近正交向量（模拟真实嵌入）。

    登记向量以"短向量 + 补零"给出，便于书写；维度统一为 _DIMS。
    """

    available = True
    _DIMS = 32

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors

    @staticmethod
    def _hash_vec(text: str) -> list[float]:
        import hashlib

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vec = [digest[i] / 255.0 - 0.5 for i in range(ScriptedEmbedder._DIMS)]
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]

    def _vec(self, text: str) -> list[float]:
        raw = self._vectors.get(text)
        if raw is None:
            return self._hash_vec(text)
        padded = list(raw) + [0.0] * (self._DIMS - len(raw))
        return padded[: self._DIMS]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class UnavailableEmbedder:
    available = False

    def embed_documents(self, texts):  # pragma: no cover - 不应被调用
        raise AssertionError("unavailable embedder must not be used")

    def embed_queries(self, texts):  # pragma: no cover
        raise AssertionError("unavailable embedder must not be used")


def _service(embedder) -> RulesService:
    service = RulesService(RULES_PATH)
    service.load()
    service.set_semantic_matcher(SemanticMatcher(embedder))
    return service


# ---------------------------------- 机制 ----------------------------------


def test_split_clauses_filters_noise_and_dedupes() -> None:
    clauses = split_clauses("你好。必须退款！！必须退款；顺便问问。")
    assert clauses == ["你好", "必须退款", "顺便问问"]


def test_split_clauses_limit_keeps_longest() -> None:
    text = "短。" + "很长的一句话内容。" + "中等的句子。" + "也很长的一句话内容哦。"
    clauses = split_clauses(text, max_clauses=2)
    assert len(clauses) == 2
    assert all(len(c) >= 6 for c in clauses)


def test_matcher_returns_max_similarity_per_group() -> None:
    matcher = SemanticMatcher(
        ScriptedEmbedder(
            {"要求退款": [1.0, 0.0, 0.0], "必须退款": [0.98, 0.02, 0.0], "无关锚点": [0.0, 1.0, 0.0]}
        )
    )
    scores = matcher.match(
        "东西破了。必须退款！",
        {"refund_intent": ["要求退款"], "other": ["无关锚点"]},
    )
    assert scores["refund_intent"] > 0.999
    assert scores["other"] < 0.2  # 未登记文本之间近正交


def test_semantic_level_labels_are_independent_of_case_risk() -> None:
    assert semantic_level(0.81, 0.70) == "完全命中"
    assert semantic_level(0.75, 0.70) == "疑似"
    assert semantic_level(0.71, 0.70) == "普通"


def test_matcher_unavailable_returns_empty() -> None:
    matcher = SemanticMatcher(UnavailableEmbedder())  # type: ignore[arg-type]
    assert matcher.available is False
    assert matcher.match("必须退款", {"refund_intent": ["要求退款"]}) == {}


# -------------------------------- 规则引擎接入 --------------------------------


def test_semantic_channel_triggers_without_keywords() -> None:
    """纯语义命中（文本不含"退款"二字）也能触发 —— 用户诉求③的核心场景。"""
    service = _service(
        ScriptedEmbedder(
            {
                "要求退款": [1.0, 0.0, 0.0],
                "这个钱我不要了": [0.9, 0.1, 0.0],  # 与锚点高度相似但无关键词
            }
        )
    )
    decision = service.decide(text="这个钱我不要了，你们看着办", image_count=1)
    assert decision.semantic_status == "matched"
    assert "refund_intent" in decision.semantic_hits
    assert decision.semantic_levels["refund_intent"] == "完全命中"
    assert decision.need_analysis is True
    assert decision.scenario == "product_damage_claim"
    assert any("any_semantic" in hit for m in decision.matched_rules for hit in m.hits)


def test_damage_semantic_with_image_rule() -> None:
    """语义命中商品损坏 + 有图 → 应触发（此前只有"无图"分支，有图会漏触发）。"""
    service = _service(
        ScriptedEmbedder(
            {
                "收到的商品已经破损": [1.0, 0.0, 0.0],
                "照片就是碎的": [0.95, 0.05, 0.0],
            }
        )
    )
    decision = service.decide(text="照片就是碎的", image_count=1)
    assert decision.need_analysis is True
    assert decision.scenario == "product_damage_claim"
    ids = {m.id for m in decision.matched_rules}
    assert "damage_semantic_with_image" in ids


def test_group_threshold_blocks_low_score() -> None:
    """分组阈值：低于该组阈值不命中（此处 product_damage 组阈值 0.66）。"""
    # 与锚点相似度约 0.6（低于 refund 组 0.70 与 product_damage 组 0.66）
    service = _service(
        ScriptedEmbedder(
            {
                "要求退款": [1.0, 0.0, 0.0],
                "收到的商品已经破损": [1.0, 0.0, 0.0],
                "东西好像有点问题呢": [0.6, 0.8, 0.0],
            }
        )
    )
    decision = service.decide(text="东西好像有点问题呢", image_count=1)
    assert decision.semantic_status == "no_match"
    assert decision.semantic_hits == {}
    assert decision.need_analysis is False


def test_semantic_unavailable_degrades_to_keywords() -> None:
    service = _service(UnavailableEmbedder())
    assert service.semantic_mode == "unavailable"
    decision = service.decide(text="杯子碎了必须退款", image_count=1)
    assert decision.need_analysis is True  # 关键词通道仍生效
    assert decision.semantic_status == "unavailable"
    assert decision.semantic_hits == {}


def test_keyword_rule_wins_by_priority() -> None:
    """关键词命中（100）优先于语义命中（98），但两类都记录在 matched_rules。"""
    service = _service(ScriptedEmbedder({"要求退款": [1.0, 0.0, 0.0], "必须退款": [1.0, 0.0, 0.0]}))
    decision = service.decide(text="东西碎成这样，必须退款", image_count=1)
    assert decision.matched_rules[0].id == "refund_with_image"
    ids = {m.id for m in decision.matched_rules}
    assert "refund_semantic_with_image" in ids
