"""本地向量模型封装（fastembed / ONNX，CPU 推理，免 torch）。

加载失败时优雅降级（available()=False），RAG 自动切 BM25-only，服务不挂。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


class Embedder:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._model: Any = None
        self._error: str | None = None
        self._load()

    @property
    def local_model_dir(self) -> Path:
        """本地模型目录（scripts/fetch_model_files.py 的落点；存在则优先离线加载）。"""
        return self._settings.embedding_cache_dir / self._settings.embedding_model.split("/")[-1]

    def _load(self) -> None:
        if self._settings.hf_endpoint:
            os.environ.setdefault("HF_ENDPOINT", self._settings.hf_endpoint)
            # hf-mirror 等镜像不支持 HuggingFace Xet(CAS) 后端（会 401），走经典 resolve 路径
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        try:
            from fastembed import TextEmbedding

            kwargs: dict[str, Any] = {
                "model_name": self._settings.embedding_model,
                "cache_dir": str(self._settings.embedding_cache_dir),
            }
            local_dir = self.local_model_dir
            if (local_dir / "model_optimized.onnx").exists():
                kwargs["specific_model_path"] = str(local_dir)
                logger.info("using local model files: %s", local_dir)

            self._model = TextEmbedding(**kwargs)
            # 预热，尽早暴露模型下载/加载问题
            list(self._model.embed(["预热"]))
            logger.info("embedder ready: %s", self._settings.embedding_model)
        except Exception as exc:
            self._error = str(exc)
            self._model = None
            logger.warning("embedder unavailable, RAG will degrade to BM25-only: %s", exc)

    @property
    def available(self) -> bool:
        return self._model is not None

    @property
    def error(self) -> str | None:
        return self._error

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            raise RuntimeError(f"embedder unavailable: {self._error}")
        return [list(map(float, vec)) for vec in self._model.embed(texts)]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        """批量查询向量（BGE 查询前缀由模型自带 query_embed 处理）。"""
        if self._model is None:
            raise RuntimeError(f"embedder unavailable: {self._error}")
        if not texts:
            return []
        query_fn = getattr(self._model, "query_embed", None)
        if callable(query_fn):
            return [list(map(float, vec)) for vec in query_fn(texts)]
        embeds = self._model.embed([self._settings.rag_query_prefix + t for t in texts])
        return [list(map(float, vec)) for vec in embeds]

    def embed_query(self, text: str) -> list[float]:
        if self._model is None:
            raise RuntimeError(f"embedder unavailable: {self._error}")
        query_fn = getattr(self._model, "query_embed", None)
        if callable(query_fn):
            return list(map(float, next(iter(query_fn([text])))))
        # 退化路径：手动加 BGE 中文检索前缀
        embeds = list(self._model.embed([self._settings.rag_query_prefix + text]))
        return list(map(float, embeds[0]))
