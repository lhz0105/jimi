"""混合检索 RRF 融合与阈值过滤测试（不依赖真实向量模型）。"""

from __future__ import annotations

from app.config import Settings
from app.rag.retriever import HybridRetriever


class _FakeEmbedder:
    def __init__(self, vectors: dict[str, list[float]], available: bool = True) -> None:
        self._vectors = vectors
        self.available = available

    def embed_query(self, text: str) -> list[float]:
        return self._vectors.get("__query__", [1.0, 0.0])

    def embed_documents(self, texts):
        raise NotImplementedError


class _FakeStore:
    def __init__(self, results: list[tuple[str, float]], available: bool = True) -> None:
        self._results = results
        self.available = available

    def query(self, embedding, n_results: int = 20):
        return self._results[:n_results]

    def count(self) -> int:
        return len(self._results)


def _settings() -> Settings:
    return Settings(
        rag_top_k=3,
        rag_candidates=10,
        rag_rrf_k=60,
        rag_w_dense=1.0,
        rag_w_bm25=0.8,
        rag_min_dense_score=0.35,
    )


def _chunks() -> list[dict]:
    return [
        {"id": "c1", "doc_id": "d1", "doc_title": "A", "scenario": "generic", "heading_path": "", "text": "破损索赔判定标准"},
        {"id": "c2", "doc_id": "d1", "doc_title": "A", "scenario": "generic", "heading_path": "", "text": "医疗单据检查"},
        {"id": "c3", "doc_id": "d2", "doc_title": "B", "scenario": "seeding_post", "heading_path": "", "text": "商单特征"},
    ]


def test_rrf_ranks_agreeing_results_first() -> None:
    settings = _settings()
    retriever = HybridRetriever(settings, _FakeEmbedder({}), _FakeStore([("c1", 0.9), ("c2", 0.4)]))
    retriever.rebuild(_chunks())
    # c1 在 dense 第 1，且在 BM25 也会因"破损索赔"命中 → 融合分最高
    results = retriever.search_detailed("破损索赔判定标准")
    assert results
    assert results[0]["chunk_id"] == "c1"
    assert results[0]["score_dense"] == 0.9
    assert results[0]["score_rrf"] > 0


def test_low_dense_score_filtered_without_bm25_support() -> None:
    settings = _settings()
    # c2 dense 分低于阈值且 BM25 无命中（查询词不匹配）→ 应被过滤
    retriever = HybridRetriever(settings, _FakeEmbedder({}), _FakeStore([("c2", 0.10)]))
    retriever.rebuild(_chunks())
    results = retriever.search_detailed("完全无关的检索词xyz")
    assert all(r["chunk_id"] != "c2" for r in results)


def test_scenario_filter() -> None:
    settings = _settings()
    retriever = HybridRetriever(
        settings, _FakeEmbedder({}), _FakeStore([("c3", 0.9), ("c1", 0.9)])
    )
    retriever.rebuild(_chunks())
    results = retriever.search_detailed("商单特征", scenario="seeding_post")
    assert all(r["scenario"] in ("seeding_post", "generic") for r in results)


def test_bm25_only_mode_without_dense() -> None:
    settings = _settings()
    retriever = HybridRetriever(
        settings, _FakeEmbedder({}, available=False), _FakeStore([], available=False)
    )
    retriever.rebuild(_chunks())
    assert retriever.rag_mode == "bm25_only"
    results = retriever.search_detailed("破损索赔判定标准")
    assert results and results[0]["chunk_id"] == "c1"
    assert results[0]["score_dense"] is None


def test_top_k_limit() -> None:
    settings = _settings()
    retriever = HybridRetriever(
        settings, _FakeEmbedder({}), _FakeStore([("c1", 0.9), ("c2", 0.8), ("c3", 0.7)])
    )
    retriever.rebuild(_chunks())
    results = retriever.search_detailed("破损 索赔 医疗 单据 商单 特征")
    assert len(results) <= settings.rag_top_k
