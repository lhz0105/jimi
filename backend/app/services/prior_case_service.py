"""先前案例独立索引：Chroma 集合 + BM25，与 doctrine 知识库隔离。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.config import Settings
from app.db.database import Database
from app.db.repositories import prior_cases as prior_cases_repo
from app.rag.chunker import chunk_document
from app.rag.embedder import Embedder
from app.rag.retriever import HybridRetriever
from app.rag.store import VectorStore

logger = logging.getLogger(__name__)

_META_KEYS = ("case_id", "doc_id", "doc_title", "scenario", "human_verdict")


class PriorCaseService:
    def __init__(
        self, settings: Settings, db: Database, embedder: Embedder | None = None
    ) -> None:
        self._settings = settings
        self._db = db
        self._embedder = embedder
        self._store: VectorStore | None = None
        self._retriever: HybridRetriever | None = None
        self._chunks: list[dict[str, Any]] = []
        self._ready = False

    async def initialize(self) -> None:
        try:
            if self._embedder is None:
                self._embedder = await asyncio.to_thread(Embedder, self._settings)
            self._store = await asyncio.to_thread(
                VectorStore, self._settings, self._settings.prior_case_collection
            )
            self._retriever = HybridRetriever(
                self._settings, self._embedder, self._store
            )
            await self.reindex(rebuild=True)
            self._ready = True
            logger.info(
                "prior case index ready: mode=%s cases=%d chunks=%d",
                self.rag_mode,
                len({c.get("case_id") for c in self._chunks}),
                len(self._chunks),
            )
        except Exception:
            logger.exception("prior case index initialize failed")

    @property
    def ready(self) -> bool:
        return self._ready and self._retriever is not None

    @property
    def rag_mode(self) -> str:
        if self._retriever is None:
            return "uninitialized"
        return self._retriever.rag_mode

    def statistics(self) -> dict[str, Any]:
        if self._retriever is None:
            return {"mode": "uninitialized", "cases": 0, "chunks": 0}
        return {
            **self._retriever.statistics(),
            "cases": len({c.get("case_id") for c in self._chunks}),
        }

    def chunk_meta(self, chunk_id: str) -> dict[str, Any] | None:
        if self._retriever is None:
            return None
        return self._retriever.chunk_meta(chunk_id)

    async def search(
        self, query: str, *, top_k: int | None = None, scenario: str | None = None
    ) -> list[dict[str, Any]]:
        if not self.ready:
            return []
        assert self._retriever is not None
        limit = max((top_k or self._settings.prior_case_top_k) * 3, 10)
        raw = await asyncio.to_thread(
            self._retriever.search_detailed,
            query,
            top_k=limit,
            scenario=scenario,
        )
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw:
            meta = self._retriever.chunk_meta(item.get("chunk_id")) or {}
            case_id = str(meta.get("case_id") or item.get("doc_id") or "")
            if not case_id or case_id in seen:
                continue
            seen.add(case_id)
            case = await prior_cases_repo.get(self._db, case_id)
            if case is None:
                # 案例已删除但旧索引尚未清理时，不返回幽灵命中
                continue
            reliability = float(case.get("reliability") or 0.5)
            hit = dict(item)
            hit["case_id"] = case_id
            hit["human_verdict"] = meta.get("human_verdict") or (case or {}).get(
                "human_verdict"
            )
            hit["reliability"] = reliability
            hit["score_adjusted"] = round(
                float(hit.get("score_rrf") or 0) * (0.7 + 0.6 * reliability), 6
            )
            unique.append(hit)
        unique.sort(key=lambda item: -float(item["score_adjusted"]))
        return unique[: (top_k or self._settings.prior_case_top_k)]

    def _case_chunks(self, case: dict[str, Any]) -> list[dict[str, Any]]:
        _, chunks = chunk_document(
            case["markdown"],
            chunk_size=self._settings.chunk_size,
            overlap=self._settings.chunk_overlap,
        )
        out: list[dict[str, Any]] = []
        for chunk in chunks:
            out.append(
                {
                    "id": f"{case['id']}:c{chunk['ordinal']}",
                    "doc_id": case["id"],
                    "doc_title": case["title"],
                    "scenario": case.get("scenario") or "",
                    "heading_path": chunk["heading_path"],
                    "text": chunk["text"],
                    "case_id": case["id"],
                    "human_verdict": case.get("human_verdict") or "",
                }
            )
        return out

    async def reindex(self, *, rebuild: bool = True) -> dict[str, Any]:
        cases = await prior_cases_repo.all_cases(self._db)
        chunks = [chunk for case in cases for chunk in self._case_chunks(case)]
        self._chunks = chunks
        if self._retriever is not None:
            self._retriever.rebuild(chunks)
        if rebuild and self._store is not None:
            try:
                await asyncio.to_thread(self._store.clear)
            except Exception as exc:  # pragma: no cover
                logger.warning("prior case store clear failed: %s", exc)
        await self._upsert_chunks(chunks)
        return self.statistics()

    async def index_case(self, case: dict[str, Any]) -> None:
        if self._retriever is None:
            raise RuntimeError("先前案例索引未初始化")
        old_ids = [c["id"] for c in self._chunks if c.get("case_id") == case["id"]]
        if old_ids and self._store is not None:
            await asyncio.to_thread(self._store.delete_ids, old_ids)
        self._chunks = [c for c in self._chunks if c.get("case_id") != case["id"]]
        new_chunks = self._case_chunks(case)
        self._chunks.extend(new_chunks)
        self._retriever.rebuild(self._chunks)
        await self._upsert_chunks(new_chunks)

    async def delete_case(self, case_id: str) -> int:
        """从 Chroma 与内存 BM25 中移除案例，返回清理的索引块数。"""
        old_ids = [c["id"] for c in self._chunks if c.get("case_id") == case_id]
        if old_ids and self._store is not None:
            await asyncio.to_thread(self._store.delete_ids, old_ids)
        self._chunks = [c for c in self._chunks if c.get("case_id") != case_id]
        if self._retriever is not None:
            self._retriever.rebuild(self._chunks)
        return len(old_ids)

    async def _upsert_chunks(self, chunks: list[dict[str, Any]]) -> None:
        if not chunks or self._store is None or self._embedder is None:
            return
        if not self._embedder.available or not self._store.available:
            return
        texts = [c["text"] for c in chunks]
        try:
            embeddings = await asyncio.to_thread(self._embedder.embed_documents, texts)
            metadatas = [
                {key: c.get(key, "") for key in _META_KEYS} for c in chunks
            ]
            await asyncio.to_thread(
                self._store.upsert,
                ids=[c["id"] for c in chunks],
                embeddings=embeddings,
                documents=texts,
                metadatas=metadatas,
            )
        except Exception as exc:  # pragma: no cover - dense 失败仍保留 BM25
            logger.warning("prior case dense upsert failed: %s", exc)
