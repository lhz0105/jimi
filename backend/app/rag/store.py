"""Chroma 持久化向量库封装（自管 embedding，避免默认 embedding 函数触发额外下载）。"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)

# Chroma 1.x 对集合名有长度校验（3-512 字符），勿用短名
COLLECTION_NAME = "kb_chunks"


class VectorStore:
    def __init__(self, settings: Settings, collection_name: str = COLLECTION_NAME) -> None:
        self._settings = settings
        self._collection_name = collection_name
        self._client: Any = None
        self._collection: Any = None
        self._metric = "cosine"
        self.available = False
        try:
            import chromadb

            try:
                from chromadb.config import Settings as ChromaSettings

                self._client = chromadb.PersistentClient(
                    path=str(settings.chroma_dir),
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            except Exception:
                self._client = chromadb.PersistentClient(path=str(settings.chroma_dir))

            self._collection = self._client.get_or_create_collection(
                self._collection_name, metadata={"hnsw:space": "cosine"}
            )

            metadata = getattr(self._collection, "metadata", None) or {}
            self._metric = metadata.get("hnsw:space", "cosine")
            self.available = True
            logger.info("chroma ready: dir=%s metric=%s", settings.chroma_dir, self._metric)
        except Exception as exc:
            logger.warning("chroma unavailable, dense retrieval disabled: %s", exc)

    def _similarity(self, distance: float) -> float:
        if self._metric == "cosine":
            return 1.0 - float(distance)
        if self._metric == "l2":
            # 向量已归一化：L2² = 2 - 2cos
            return 1.0 - float(distance) ** 2 / 2.0
        if self._metric == "ip":
            return 1.0 - float(distance)
        return 1.0 - float(distance)

    def count(self) -> int:
        if not self.available:
            return 0
        try:
            return int(self._collection.count())
        except Exception:  # pragma: no cover
            return 0

    def upsert(
        self,
        *,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        if not self.available or not ids:
            return
        self._collection.upsert(
            ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas
        )

    def delete_ids(self, ids: list[str]) -> None:
        if not self.available or not ids:
            return
        try:
            self._collection.delete(ids=ids)
        except Exception:  # pragma: no cover
            logger.warning("chroma delete failed for %d ids", len(ids))

    def clear(self) -> None:
        if not self.available:
            return
        try:
            self._client.delete_collection(self._collection_name)
        except Exception:  # pragma: no cover
            pass
        self._collection = self._client.get_or_create_collection(
            self._collection_name, metadata={"hnsw:space": "cosine"}
        )

    def query(self, embedding: list[float], n_results: int = 20) -> list[tuple[str, float]]:
        if not self.available or self.count() == 0:
            return []
        result = self._collection.query(
            query_embeddings=[embedding],
            n_results=min(n_results, max(1, self.count())),
            include=["distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        return [
            (cid, self._similarity(dist))
            for cid, dist in zip(ids, distances)
        ]
