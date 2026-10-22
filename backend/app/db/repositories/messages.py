from __future__ import annotations

from typing import Any

from app.core.clock import now_ms
from app.core.errors import NotFoundError
from app.core.ids import new_id
from app.db.database import Database
from app.db.repositories.util import dumps_json, loads_json


async def add(
    db: Database,
    *,
    conversation_id: str,
    role: str,
    content: str,
    content_type: str = "text",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    msg_id = new_id("msg")
    ts = now_ms()
    async with db.write() as conn:
        row = await (
            await conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next_seq FROM messages WHERE conversation_id = ?",
                (conversation_id,),
            )
        ).fetchone()
        seq = int(row["next_seq"])
        await conn.execute(
            """INSERT INTO messages(id, conversation_id, seq, role, content, content_type, meta, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, conversation_id, seq, role, content, content_type, dumps_json(meta or {}), ts),
        )
        await conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?", (ts, conversation_id)
        )
    return {
        "id": msg_id,
        "conversation_id": conversation_id,
        "seq": seq,
        "role": role,
        "content": content,
        "content_type": content_type,
        "meta": meta or {},
        "created_at": ts,
    }


async def list_by_conversation(
    db: Database, conversation_id: str, *, limit: int | None = None
) -> list[dict[str, Any]]:
    if limit is not None:
        rows = await db.fetchall(
            """SELECT * FROM messages WHERE conversation_id = ?
                ORDER BY seq DESC LIMIT ?""",
            (conversation_id, limit),
        )
        rows = list(reversed(rows))
    else:
        rows = await db.fetchall(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY seq", (conversation_id,)
        )
    out = []
    for row in rows:
        d = dict(row)
        d["meta"] = loads_json(d.get("meta"), {})
        out.append(d)
    return out


async def transcript_text(
    db: Database, conversation_id: str, *, limit: int = 12
) -> str:
    """最近 N 条消息拼接文本，供规则引擎判断（只取 customer/agent 双方）。"""
    messages = await list_by_conversation(db, conversation_id, limit=limit)
    parts = []
    for m in messages:
        speaker = {"customer": "客户", "agent": "客服"}.get(m["role"], m["role"])
        parts.append(f"{speaker}: {m['content']}")
    return "\n".join(parts)


async def get(db: Database, message_id: str) -> dict[str, Any]:
    row = await db.fetchone("SELECT * FROM messages WHERE id = ?", (message_id,))
    if row is None:
        raise NotFoundError(f"消息不存在: {message_id}")
    d = dict(row)
    d["meta"] = loads_json(d.get("meta"), {})
    return d
