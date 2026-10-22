"""Chroma 集合名隔离：doctrine 与先前案例不得共用一个集合。"""

from __future__ import annotations

from app.config import Settings
from app.rag.store import VectorStore


def test_vector_store_uses_explicit_collection(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = Settings(chroma_dir=tmp_path / "chroma")
    docs = VectorStore(settings, "test_doctrine_chunks")
    prior = VectorStore(settings, "test_prior_case_chunks")
    assert docs.available and prior.available

    docs.upsert(
        ids=["doc-1"],
        embeddings=[[0.0, 1.0]],
        documents=["doctrine"],
        metadatas=[{"kind": "doctrine"}],
    )
    prior.upsert(
        ids=["case-1"],
        embeddings=[[1.0, 0.0]],
        documents=["prior case"],
        metadatas=[{"kind": "prior"}],
    )
    assert docs.count() == 1
    assert prior.count() == 1

    prior.delete_ids(["case-1"])
    assert prior.count() == 0
    assert docs.count() == 1

    prior.clear()
    assert prior.count() == 0
    assert docs.count() == 1
