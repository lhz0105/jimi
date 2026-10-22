"""混合检索：向量 + BM25 → RRF 融合 → 阈值过滤。

对外唯一出口 search()；rag_hit 事件的数据即来源于此。
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.rag.bm25 import Bm25Index
from app.rag.embedder import Embedder
from app.rag.store import VectorStore

logger = logging.getLogger(__name__)


class HybridRetriever:
    def __init__(self, settings: Settings, embedder: Embedder, store: VectorStore) -> None:
        self._settings = settings
        self._embedder = embedder
        self._store = store
        self._bm25 = Bm25Index()
        self._chunk_meta: dict[str, dict[str, Any]] = {}

    # ---- 索引维护 ----

    def rebuild(self, chunks: list[dict[str, Any]]) -> None:
        self._chunk_meta = {c["id"]: c for c in chunks}
        self._bm25.build(chunks)

    @property
    def dense_available(self) -> bool:
        return self._embedder.available and self._store.available

    @property
    def rag_mode(self) -> str:
        return "hybrid" if self.dense_available else "bm25_only"

    @property
    def chunk_count(self) -> int:
        return len(self._chunk_meta)

    def chunk_meta(self, chunk_id: str) -> dict[str, Any] | None:
        return self._chunk_meta.get(chunk_id)

    # ---- 检索 ----

    def statistics(self) -> dict[str, Any]:
        return {
            "mode": self.rag_mode,
            "chunks": len(self._chunk_meta),
            "dense_chunks": self._store.count() if self._store.available else 0,
            "bm25_chunks": self._bm25.size,
        }

    def search_detailed(
        self,
        query: str,
        *,
        top_k: int | None = None,
        scenario: str | None = None,
    ) -> list[dict[str, Any]]:
        """返回带双路分数与融合分的命中列表。"""
        s = self._settings
        top_k = top_k or s.rag_top_k
        candidates = s.rag_candidates

        dense_scores: dict[str, float] = {}
        dense_error: str | None = None
        if self.dense_available:
            try:
                vector = self._embedder.embed_query(query)
                dense_scores = dict(self._store.query(vector, n_results=candidates))
            except Exception as exc:
                dense_error = str(exc)
                logger.warning("dense retrieval failed, falling back to bm25: %s", exc)

        sparse_scores = dict(self._bm25.search(query, n=candidates))

        dense_rank = sorted(dense_scores, key=lambda cid: -dense_scores[cid])
        sparse_rank = sorted(sparse_scores, key=lambda cid: -sparse_scores[cid])

        rrf: dict[str, float] = {}
        for rank, chunk_id in enumerate(dense_rank, start=1):
            rrf[chunk_id] = rrf.get(chunk_id, 0.0) + s.rag_w_dense / (s.rag_rrf_k + rank)
        for rank, chunk_id in enumerate(sparse_rank, start=1):
            rrf[chunk_id] = rrf.get(chunk_id, 0.0) + s.rag_w_bm25 / (s.rag_rrf_k + rank)

        results: list[dict[str, Any]] = []
        for chunk_id, score in sorted(rrf.items(), key=lambda kv: -kv[1]):
            meta = self._chunk_meta.get(chunk_id)
            if meta is None:
                continue
            if scenario and not _scenario_match(meta.get("scenario"), scenario):
                continue
            dense_score = dense_scores.get(chunk_id)
            sparse_rank_pos = (
                sparse_rank.index(chunk_id) + 1 if chunk_id in sparse_rank else None
            )
            # 阈值过滤：dense 低于阈值且 BM25 未进前 5 → 丢弃
            if (
                dense_score is not None
                and dense_score < s.rag_min_dense_score
                and (sparse_rank_pos is None or sparse_rank_pos > 5)
            ):
                continue
            results.append(
                {
                    "chunk_id": chunk_id,
                    "doc_id": meta.get("doc_id"),
                    "doc_title": meta.get("doc_title"),
                    "scenario": meta.get("scenario"),
                    "heading_path": meta.get("heading_path"),
                    "text": meta.get("text"),
                    "score_dense": round(dense_score, 4) if dense_score is not None else None,
                    "score_bm25": round(sparse_scores.get(chunk_id, 0.0), 4),
                    "score_rrf": round(score, 6),
                }
            )
            if len(results) >= top_k:
                break

        if dense_error and not results:
            logger.info("hybrid search empty with dense error: %s", dense_error)
        return results


def _scenario_match(chunk_scenario: str | None, scenario: str) -> bool:
    if not chunk_scenario or chunk_scenario in ("all", "generic"):
        return True
    return chunk_scenario == scenario
