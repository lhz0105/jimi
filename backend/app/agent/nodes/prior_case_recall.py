"""prior_case_recall：从人工判决沉淀的先前案例中检索相似先例。"""

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
_VERDICT_LABEL = {"fraud": "欺诈", "genuine": "真实", "insufficient": "证据不足"}
_DIRECTION = {
    "fraud": "supports_fake",
    "genuine": "supports_genuine",
    "insufficient": "unknown",
}


def _build_query(state: dict[str, Any]) -> str:
    case = state.get("case") or {}
    scenario = state.get("scenario") or "generic"
    digest = (case.get("digest_text") or "")[:300]
    return f"{_SCENARIO_LABEL.get(scenario, '')}：{digest}"


@observed_node("prior_case_recall")
async def prior_case_recall(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    service = getattr(runtime, "prior_cases", None)
    if service is None or not getattr(service, "ready", False):
        return {"prior_cases": [], "warnings": []}

    query = _build_query(state)
    try:
        hits = await service.search(
            query,
            top_k=runtime.settings.prior_case_top_k,
            scenario=state.get("scenario"),
        )
    except Exception as exc:
        return {"prior_cases": [], "warnings": [f"先前案例检索失败：{exc}"]}

    unique_hits: list[tuple[dict[str, Any], dict[str, Any]]] = []
    seen_cases: set[str] = set()
    for hit in hits:
        meta = service.chunk_meta(hit.get("chunk_id")) or {}
        case_id = str(meta.get("case_id") or hit.get("doc_id") or "")
        if not case_id or case_id in seen_cases:
            continue
        seen_cases.add(case_id)
        unique_hits.append((hit, meta))

    hit_payload = []
    for hit, meta in unique_hits:
        hit_payload.append(
            {
                "chunk_id": hit.get("chunk_id"),
                "case_id": meta.get("case_id") or hit.get("doc_id"),
                "doc_title": hit.get("doc_title"),
                "scenario": hit.get("scenario"),
                "human_verdict": meta.get("human_verdict"),
                "reliability": hit.get("reliability"),
                "score_dense": hit.get("score_dense"),
                "score_bm25": hit.get("score_bm25"),
                "score_rrf": hit.get("score_rrf"),
                "score_adjusted": hit.get("score_adjusted"),
                "preview": (hit.get("text") or "")[:200],
            }
        )
    runtime.emitter.emit(
        EventType.RAG_HIT,
        {
            "source": "prior_cases",
            "query": query[:200],
            "top_k": runtime.settings.prior_case_top_k,
            "rag_mode": getattr(service, "rag_mode", "hybrid"),
            "hits": hit_payload,
        },
    )

    builder = EvidenceBuilder(state)
    evidence = []
    for hit, meta in unique_hits[:2]:
        score = float(hit.get("score_adjusted") or hit.get("score_rrf") or 0.0)
        if score <= 0:
            continue
        human_verdict = str(meta.get("human_verdict") or "insufficient")
        label = _VERDICT_LABEL.get(human_verdict, human_verdict)
        case_id = meta.get("case_id") or hit.get("doc_id")
        reliability = float(hit.get("reliability") or 0.5)
        if human_verdict in ("fraud", "genuine"):
            weight = 0.3 + 0.6 * reliability
        else:
            weight = 0.2 + 0.4 * reliability
        evidence.append(
            builder.add(
                category="rag_precedent",
                source={
                    "type": "prior_case",
                    "ref": case_id,
                    "detail": hit.get("doc_title") or "",
                },
                tool="prior_case_recall",
                finding=(
                    f"人工复核先例「{hit.get('doc_title')}」（当前可靠性 {reliability:.2f}）："
                    f"人工判决为{label}。依据：{(hit.get('text') or '')[:220]}"
                    "（需比较与本案的相似点/差异，不得直接照搬结论）"
                ),
                direction=_DIRECTION.get(human_verdict, "unknown"),
                weight=round(weight, 2),
                raw_ref={
                    "case_id": case_id,
                    "human_verdict": human_verdict,
                    "reliability": round(reliability, 4),
                    "score_adjusted": score,
                },
            )
        )
    return {
        "prior_cases": [hit for hit, _meta in unique_hits],
        "evidence": evidence,
    }
