"""语义触发匹配：客户文本 vs 锚点短语的余弦相似度（复用本地 BGE 向量模型）。

策略（针对中文客服短句）：
- 锚点短语按"文档"编码（BGE 无需前缀），客户文本按标点切成子句、按"查询"编码；
- 取 max(子句 × 锚点) 作为该锚点组的相似度——整段长文本与短锚点的相似度会被稀释，
  子句级匹配才能稳定区分"必须退款"（≈0.8）与"快递什么时候到"（≈0.3）；
- 锚点向量按短语文本缓存；向量模型不可用时返回空结果（上层自动降级为纯关键词）。
"""

from __future__ import annotations

import logging
import re
from typing import Protocol

logger = logging.getLogger(__name__)

_CLAUSE_SPLIT_RE = re.compile(r"[。！？；!?;\n…、]+|[,，]{1}")
_MIN_CLAUSE_CHARS = 2


class EmbedderLike(Protocol):
    available: bool

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_queries(self, texts: list[str]) -> list[list[float]]: ...


def split_clauses(text: str, *, max_clauses: int = 8) -> list[str]:
    """切分为子句（过滤过短片段），保留顺序、去重，最多 max_clauses 条。"""
    if not text:
        return []
    raw = _CLAUSE_SPLIT_RE.split(text)
    seen: set[str] = set()
    clauses: list[str] = []
    for piece in raw:
        clause = piece.strip()
        if len(clause) < _MIN_CLAUSE_CHARS or clause in seen:
            continue
        seen.add(clause)
        clauses.append(clause)
    # 优先保留较长的子句（信息量更大），再按原顺序还原
    if len(clauses) > max_clauses:
        keep = set(sorted(clauses, key=len, reverse=True)[:max_clauses])
        clauses = [c for c in clauses if c in keep]
    return clauses


def _cosine(a: list[float], b: list[float]) -> float:
    # 向量已由模型归一化，点积即余弦；仍做一次保护性归一化以兼容未归一化模型
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / ((na**0.5) * (nb**0.5))


class SemanticMatcher:
    def __init__(self, embedder: EmbedderLike, *, max_clauses: int = 8) -> None:
        self._embedder = embedder
        self._max_clauses = max_clauses
        self._anchor_cache: dict[str, list[float]] = {}

    @property
    def available(self) -> bool:
        return bool(getattr(self._embedder, "available", False))

    def _anchor_vector(self, phrase: str) -> list[float]:
        cached = self._anchor_cache.get(phrase)
        if cached is not None:
            return cached
        vector = self._embedder.embed_documents([phrase])[0]
        self._anchor_cache[phrase] = vector
        return vector

    def match(self, text: str, anchors: dict[str, list[str]]) -> dict[str, float]:
        """返回 {锚点组: 最高相似度}（0~1）；不可用或无文本时返回空。"""
        if not self.available or not text or not anchors:
            return {}
        clauses = split_clauses(text, max_clauses=self._max_clauses)
        if not clauses:
            return {}
        try:
            clause_vectors = self._embedder.embed_queries(clauses)
        except Exception as exc:  # pragma: no cover - 编码失败不影响主流程
            logger.warning("semantic query embedding failed: %s", exc)
            return {}

        scores: dict[str, float] = {}
        for key, phrases in anchors.items():
            best = 0.0
            for phrase in phrases:
                try:
                    anchor_vec = self._anchor_vector(phrase)
                except Exception as exc:  # pragma: no cover
                    logger.warning("anchor embedding failed (%s): %s", phrase, exc)
                    continue
                for clause_vec in clause_vectors:
                    best = max(best, _cosine(clause_vec, anchor_vec))
            scores[key] = round(best, 4)
        return scores
