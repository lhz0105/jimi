"""知识库导入：扫描 kb 目录 → 分块 → SQLite + Chroma + BM25 重建。"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from app.config import Settings
from app.core.clock import now_ms
from app.core.files import sha256_bytes
from app.core.ids import new_id
from app.db.database import Database
from app.rag.chunker import chunk_document
from app.rag.embedder import Embedder
from app.rag.retriever import HybridRetriever
from app.rag.store import VectorStore

logger = logging.getLogger(__name__)

_DOC_GLOBS = ("**/*.md", "**/*.txt")


def ensure_kb_seed(settings: Settings) -> int:
    """首次启动把随仓库的示例知识库拷到可写目录（不覆盖用户已有文件）。"""
    copied = 0
    if not settings.kb_seed_dir.exists():
        return copied
    settings.kb_dir.mkdir(parents=True, exist_ok=True)
    for path in settings.kb_seed_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".md", ".txt"):
            continue
        rel = path.relative_to(settings.kb_seed_dir)
        target = settings.kb_dir / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1
    if copied:
        logger.info("kb seed copied: %d files -> %s", copied, settings.kb_dir)
    return copied


def _scan(kb_dir: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in _DOC_GLOBS:
        files.extend(kb_dir.glob(pattern))
    return sorted({f for f in files if f.is_file()})


def _chunk_rows(doc_id: str, chunks: list[dict[str, Any]], meta: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = str(meta.get("scenario") or "generic")
    rows = []
    for chunk in chunks:
        rows.append(
            {
                "id": new_id("chunk"),
                "doc_id": doc_id,
                "ordinal": chunk["ordinal"],
                "text": chunk["text"],
                "heading_path": chunk["heading_path"],
                "scenario": scenario,
            }
        )
    return rows


async def _load_all_chunks(db: Database, doc_titles: dict[str, str]) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        """SELECT c.*, d.title AS doc_title FROM kb_chunks c
           JOIN kb_documents d ON d.id = c.doc_id AND d.enabled = 1
           ORDER BY c.doc_id, c.ordinal"""
    )
    return [
        {
            "id": r["id"],
            "doc_id": r["doc_id"],
            "doc_title": r["doc_title"] or doc_titles.get(r["doc_id"], ""),
            "scenario": r["scenario"],
            "heading_path": r["heading_path"],
            "text": r["text"],
        }
        for r in rows
    ]


async def ingest_all(
    settings: Settings,
    db: Database,
    retriever: HybridRetriever,
    embedder: Embedder,
    store: VectorStore,
    *,
    rebuild: bool = False,
) -> dict[str, Any]:
    kb_dir = settings.kb_dir
    kb_dir.mkdir(parents=True, exist_ok=True)
    files = _scan(kb_dir)

    existing_rows = await db.fetchall("SELECT * FROM kb_documents")
    existing = {r["path"]: dict(r) for r in existing_rows}

    stats = {"docs": 0, "added": 0, "updated": 0, "removed": 0, "chunks": 0, "embedded": 0}
    seen: set[str] = set()

    if rebuild:
        store.clear()

    for path in files:
        rel = str(path.relative_to(kb_dir)).replace("\\", "/")
        seen.add(rel)
        raw = path.read_text(encoding="utf-8", errors="replace")
        content_hash = sha256_bytes(raw.encode("utf-8"))
        prior = existing.get(rel)
        if prior and prior["content_hash"] == content_hash and not rebuild:
            stats["docs"] += 1
            stats["chunks"] += int(prior["chunk_count"] or 0)
            continue

        meta, chunks = chunk_document(
            raw, chunk_size=settings.chunk_size, overlap=settings.chunk_overlap
        )
        doc_id = prior["id"] if prior else new_id("doc")
        new_rows = _chunk_rows(doc_id, chunks, meta)

        if prior:
            old_ids = [
                r["id"]
                for r in await db.fetchall("SELECT id FROM kb_chunks WHERE doc_id = ?", (doc_id,))
            ]
            store.delete_ids(old_ids)
            await db.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (doc_id,))
            stats["updated"] += 1
        else:
            stats["added"] += 1

        # 先落 kb_documents（kb_chunks 有外键依赖），再写 chunks
        tags = meta.get("tags") or []

        await db.execute(
            """INSERT INTO kb_documents(id, path, title, scenario, doc_type, tags,
                                        content_hash, chunk_count, enabled, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
               ON CONFLICT(path) DO UPDATE SET
                 title=excluded.title, scenario=excluded.scenario, doc_type=excluded.doc_type,
                 tags=excluded.tags, content_hash=excluded.content_hash,
                 chunk_count=excluded.chunk_count, updated_at=excluded.updated_at""",
            (
                doc_id,
                rel,
                str(meta.get("title") or path.stem),
                str(meta.get("scenario") or "generic"),
                str(meta.get("doc_type") or ""),
                json.dumps(tags, ensure_ascii=False),
                content_hash,
                len(new_rows),
                now_ms(),
            ),
        )

        if new_rows:
            await db.executemany(
                """INSERT INTO kb_chunks(id, doc_id, ordinal, text, heading_path, scenario, meta)
                   VALUES (?, ?, ?, ?, ?, ?, '{}')""",
                [
                    (r["id"], r["doc_id"], r["ordinal"], r["text"], r["heading_path"], r["scenario"])
                    for r in new_rows
                ],
            )
            if embedder.available and store.available:
                try:
                    vectors = await asyncio.to_thread(
                        embedder.embed_documents, [r["text"] for r in new_rows]
                    )
                    store.upsert(
                        ids=[r["id"] for r in new_rows],
                        embeddings=vectors,
                        documents=[r["text"] for r in new_rows],
                        metadatas=[{"doc_id": doc_id, "scenario": r["scenario"]} for r in new_rows],
                    )
                    stats["embedded"] += len(new_rows)
                except Exception as exc:
                    logger.warning("dense index update failed (%s): %s", rel, exc)

        stats["docs"] += 1
        stats["chunks"] += len(new_rows)

    # 清理已删除的文档
    for rel, prior in existing.items():
        if rel in seen:
            continue
        old_ids = [
            r["id"]
            for r in await db.fetchall("SELECT id FROM kb_chunks WHERE doc_id = ?", (prior["id"],))
        ]
        store.delete_ids(old_ids)
        await db.execute("DELETE FROM kb_chunks WHERE doc_id = ?", (prior["id"],))
        await db.execute("DELETE FROM kb_documents WHERE id = ?", (prior["id"],))
        stats["removed"] += 1

    all_chunks = await _load_all_chunks(db, {})
    retriever.rebuild(all_chunks)

    kb_version = f"kb_{date.today().isoformat()}_{stats['docs']}docs"
    await db.execute(
        """INSERT INTO kb_index_state(id, kb_version, bm25_chunks, dense_chunks, updated_at)
           VALUES (1, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             kb_version=excluded.kb_version, bm25_chunks=excluded.bm25_chunks,
             dense_chunks=excluded.dense_chunks, updated_at=excluded.updated_at""",
        (kb_version, len(all_chunks), store.count(), now_ms()),
    )
    stats["kb_version"] = kb_version
    stats["mode"] = retriever.rag_mode
    logger.info("kb ingest done: %s", stats)
    return stats
