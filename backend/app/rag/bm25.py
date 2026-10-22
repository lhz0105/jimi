"""BM25 关键词索引（jieba 分词 + rank_bm25，内存态）。"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def tokenize(text: str) -> list[str]:
    import jieba

    return [t.strip().lower() for t in jieba.lcut(text) if t.strip()]


class Bm25Index:
    def __init__(self) -> None:
        self._ids: list[str] = []
        self._bm25: Any = None

    def build(self, chunks: list[dict[str, Any]]) -> None:
        # BM25Plus：IDF 恒为正，避免小语料（中文 chunk 少、高频词多）下 Okapi 的负 IDF 被丢弃
        from rank_bm25 import BM25Plus

        self._ids = [c["id"] for c in chunks]
        corpus = [tokenize(c.get("text", "")) for c in chunks]
        self._bm25 = BM25Plus(corpus) if corpus else None
        logger.info("bm25 index built: %d chunks", len(self._ids))

    @property
    def size(self) -> int:
        return len(self._ids)

    def search(self, query: str, n: int = 20) -> list[tuple[str, float]]:
        if self._bm25 is None or not self._ids:
            return []
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            zip(self._ids, (float(s) for s in scores)), key=lambda x: -x[1]
        )
        return [(cid, score) for cid, score in ranked[:n] if score > 0]
