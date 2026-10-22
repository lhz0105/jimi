"""rag_recall：混合检索知识库，命中即发 rag_hit 事件并生成先例证据。"""

from __future__ import annotations

from typing import Any

from app.agent.evidence import EvidenceBuilder
from app.observability.decorators import observed_node
from app.observability.events import EventType

_SCENARIO_LABEL = {
    "product_damage_claim": "退款欺诈 商品破损索赔 伪造图片鉴别",
    "medical_cert_claim": "医疗索赔 诊断单真伪 陈述矛盾",
    "seeding_post": "种草文案 商单营销 真伪鉴别",
    "generic": "欺诈识别 判定标准",
}


def _build_query(state: dict[str, Any]) -> str:
    case = state.get("case") or {}
    scenario = state.get("scenario") or "generic"
    digest = (case.get("digest_text") or "")[:300]
    return f"{_SCENARIO_LABEL.get(scenario, '')}：{digest}"


@observed_node("rag_recall")
async def rag_recall(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    kb = runtime.kb
    if kb is None:
        return {"warnings": ["知识库未就绪，跳过 RAG 召回"], "rag_hits": []}

    query = _build_query(state)
    try:
        hits = await kb.search(
            query,
            top_k=runtime.settings.rag_top_k,
            scenario=state.get("scenario"),
        )
    except Exception as exc:
        return {"warnings": [f"知识库检索失败：{exc}"], "rag_hits": []}

    runtime.emitter.emit(
        EventType.RAG_HIT,
        {
            "source": "doctrine",
            "query": query[:200],
            "top_k": runtime.settings.rag_top_k,
            "rag_mode": getattr(kb, "rag_mode", "hybrid"),
            "hits": [
                {
                    "chunk_id": h.get("chunk_id"),
                    "doc_title": h.get("doc_title"),
                    "scenario": h.get("scenario"),
                    "score_dense": h.get("score_dense"),
                    "score_bm25": h.get("score_bm25"),
                    "score_rrf": h.get("score_rrf"),
                    "preview": (h.get("text") or "")[:200],
                }
                for h in hits
            ],
        },
    )

    builder = EvidenceBuilder(state)
    evidence = []
    for hit in hits[:2]:
        score = hit.get("score_rrf") or 0.0
        if score <= 0:
            continue
        evidence.append(
            builder.add(
                category="rag_precedent",
                source={
                    "type": "knowledge_base",
                    "ref": hit.get("chunk_id") or hit.get("doc_id"),
                    "detail": hit.get("doc_title") or "",
                },
                tool="lookup_kb",
                finding=f"知识库先例/判定标准：{(hit.get('text') or '')[:200]}",
                direction="neutral",
                weight=min(0.5, 0.2 + score),
                raw_ref={"score_dense": hit.get("score_dense"), "score_bm25": hit.get("score_bm25"), "score_rrf": score},
            )
        )
    return {"rag_hits": hits, "evidence": evidence}
