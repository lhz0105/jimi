"""知识库服务：初始化（后台）、检索、文档 CRUD、重索引。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from app.config import Settings
from app.core.errors import AppError, NotFoundError
from app.db.database import Database
from app.rag.embedder import Embedder
from app.rag.ingest import ensure_kb_seed, ingest_all
from app.rag.retriever import HybridRetriever
from app.rag.store import VectorStore

logger = logging.getLogger(__name__)


class KbService:
    def __init__(self, settings: Settings, db: Database) -> None:
        self._settings = settings
        self._db = db
        self._embedder: Embedder | None = None
        self._store: VectorStore | None = None
        self._retriever: HybridRetriever | None = None
        self._ready = asyncio.Event()
        self._stats: dict[str, Any] = {}
        self._init_error: str | None = None

    # ---- 生命周期 ----

    async def initialize(self) -> None:
        try:
            await asyncio.to_thread(ensure_kb_seed, self._settings)
            # 向量模型加载/下载为阻塞操作，放线程避免冻结事件循环
            self._embedder = await asyncio.to_thread(Embedder, self._settings)
            self._store = await asyncio.to_thread(VectorStore, self._settings)
            self._retriever = HybridRetriever(self._settings, self._embedder, self._store)
            stats = await ingest_all(
                self._settings, self._db, self._retriever, self._embedder, self._store
            )
            self._stats = stats
            logger.info(
                "kb ready: mode=%s version=%s chunks=%s",
                self.rag_mode,
                self.kb_version,
                self._retriever.chunk_count,
            )
        except Exception as exc:
            self._init_error = str(exc)
            logger.exception("kb initialize failed")
        finally:
            self._ready.set()

    @property
    def ready(self) -> bool:
        return self._ready.is_set() and self._retriever is not None

    @property
    def embedder(self) -> Embedder | None:
        """供触发判断的语义通道复用同一个本地向量模型（避免重复加载）。"""
        return self._embedder

    @property
    def rag_mode(self) -> str:
        if self._retriever is None:
            return "uninitialized"
        return self._retriever.rag_mode

    @property
    def kb_version(self) -> str:
        return str(self._stats.get("kb_version") or ("kb_uninitialized" if self.ready else "kb_loading"))

    # ---- 检索 ----

    async def search(
        self, query: str, *, top_k: int | None = None, scenario: str | None = None
    ) -> list[dict[str, Any]]:
        if not self.ready:
            return []
        assert self._retriever is not None
        return await asyncio.to_thread(
            self._retriever.search_detailed, query, top_k=top_k, scenario=scenario
        )

    def statistics(self) -> dict[str, Any]:
        if self._retriever is None:
            return {"mode": "uninitialized", "chunks": 0}
        return self._retriever.statistics()

    # ---- 文档管理（管理面板） ----

    async def list_documents(self) -> list[dict[str, Any]]:
        rows = await self._db.fetchall(
            "SELECT * FROM kb_documents ORDER BY path"
        )
        return [dict(r) for r in rows]

    def _resolve_doc_path(self, rel_path: str) -> Path:
        kb_dir = self._settings.kb_dir.resolve()
        rel = rel_path.replace("\\", "/").lstrip("/")
        if ".." in rel.split("/"):
            raise AppError(f"非法文档路径: {rel_path}")
        target = (kb_dir / rel).resolve()
        if kb_dir not in target.parents and target != kb_dir:
            raise AppError(f"路径越界: {rel_path}")
        if target.suffix.lower() not in (".md", ".txt"):
            raise AppError("仅支持 .md / .txt 文档")
        return target

    async def add_document(self, rel_path: str, content: str) -> dict[str, Any]:
        target = self._resolve_doc_path(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return await self.reindex(rebuild=False)

    async def delete_document(self, doc_id: str) -> dict[str, Any]:
        row = await self._db.fetchone("SELECT * FROM kb_documents WHERE id = ?", (doc_id,))
        if row is None:
            raise NotFoundError(f"文档不存在: {doc_id}")
        path = self._resolve_doc_path(row["path"])
        if path.exists():
            path.unlink()
        return await self.reindex(rebuild=False)

    async def reindex(self, *, rebuild: bool = False) -> dict[str, Any]:
        if self._embedder is None or self._store is None or self._retriever is None:
            raise AppError("知识库尚未初始化")
        stats = await ingest_all(
            self._settings, self._db, self._retriever, self._embedder, self._store, rebuild=rebuild
        )
        self._stats = stats
        return stats
