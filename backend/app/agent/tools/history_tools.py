"""会话历史工具：按需拉取完整客户陈述（避免全量消息进上下文）。"""

from __future__ import annotations

from typing import Any

from app.db.repositories import messages as messages_repo


async def get_customer_statements_impl(runtime: Any, limit: int = 12) -> str:
    conversation_id = runtime.case.get("conversation_id")
    if not conversation_id:
        # 内联载荷：直接返回摘要文本
        return runtime.case.get("digest_text") or "（无会话上下文）"
    messages = await messages_repo.list_by_conversation(
        runtime.db, conversation_id, limit=max(2, min(limit, 50))
    )
    lines = []
    for m in messages:
        speaker = {"customer": "客户", "agent": "客服"}.get(m["role"], m["role"])
        lines.append(f"[{m['seq']}] {speaker}: {m['content']}")
    return "\n".join(lines) or "（无消息）"
