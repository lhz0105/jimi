"""触发去重状态：每会话记录最近一次分析的证据指纹。"""

from __future__ import annotations

from typing import Any

from app.core.clock import now_ms
from app.db.database import Database


async def get(db: Database, conversation_id: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        "SELECT * FROM conversation_trigger_state WHERE conversation_id = ?",
        (conversation_id,),
    )
    return dict(row) if row is not None else None


async def upsert(
    db: Database,
    *,
    conversation_id: str,
    run_id: str | None,
    signature: str,
    last_message_seq: int,
) -> None:
    ts = now_ms()
    await db.execute(
        """INSERT INTO conversation_trigger_state(
               conversation_id, last_run_id, last_signature, last_message_seq,
               last_triggered_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(conversation_id) DO UPDATE SET
             last_run_id=excluded.last_run_id,
             last_signature=excluded.last_signature,
             last_message_seq=excluded.last_message_seq,
             last_triggered_at=excluded.last_triggered_at,
             updated_at=excluded.updated_at""",
        (conversation_id, run_id, signature, last_message_seq, ts, ts),
    )
