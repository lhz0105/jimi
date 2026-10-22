"""知识库检索工具（混合检索）。"""

from __future__ import annotations

from typing import Any


async def lookup_kb_impl(runtime: Any, query: str) -> str:
    kb = runtime.kb
    if kb is None:
        return "知识库未就绪"
    results = await kb.search(query, top_k=runtime.settings.rag_top_k)
    if not results:
        return f"知识库中未检索到与「{query}」相关的内容"
    lines = [f"知识库检索结果（{len(results)} 条）："]
    for item in results:
        title = item.get("doc_title") or item.get("title") or "未命名"
        scenario = item.get("scenario") or ""
        score = item.get("score_rrf")
        preview = (item.get("text") or "")[:400]
        lines.append(f"【{title}】（场景:{scenario} 相关度:{score:.3f}）\n{preview}")
    return "\n\n".join(lines)
