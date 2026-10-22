from __future__ import annotations

from typing import Any

from app.core.clock import now_ms
from app.core.ids import new_id
from app.db.database import Database


async def add(
    db: Database,
    *,
    conversation_id: str | None,
    sha256: str,
    mime: str,
    path: str,
    width: int | None,
    height: int | None,
    size_bytes: int | None,
    message_id: str | None = None,
) -> dict[str, Any]:
    att_id = new_id("att")
    ts = now_ms()
    await db.execute(
        """INSERT INTO attachments(id, message_id, conversation_id, sha256, mime, path,
                                   width, height, bytes, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (att_id, message_id, conversation_id, sha256, mime, path, width, height, size_bytes, ts),
    )
    return await get(db, att_id)  # type: ignore[return-value]


async def get(db: Database, att_id: str) -> dict[str, Any] | None:
    row = await db.fetchone("SELECT * FROM attachments WHERE id = ?", (att_id,))
    return dict(row) if row is not None else None


async def find_by_conv_sha(db: Database, conversation_id: str, sha256: str) -> dict[str, Any] | None:
    row = await db.fetchone(
        "SELECT * FROM attachments WHERE conversation_id = ? AND sha256 = ? LIMIT 1",
        (conversation_id, sha256),
    )
    return dict(row) if row is not None else None


async def list_by_conversation(db: Database, conversation_id: str) -> list[dict[str, Any]]:
    rows = await db.fetchall(
        "SELECT * FROM attachments WHERE conversation_id = ? ORDER BY created_at", (conversation_id,)
    )
    return [dict(r) for r in rows]


async def list_by_sha(db: Database, sha256: str) -> list[dict[str, Any]]:
    rows = await db.fetchall("SELECT * FROM attachments WHERE sha256 = ?", (sha256,))
    return [dict(r) for r in rows]


async def list_by_ids(db: Database, att_ids: list[str]) -> list[dict[str, Any]]:
    if not att_ids:
        return []
    placeholders = ",".join("?" for _ in att_ids)
    rows = await db.fetchall(
        f"SELECT * FROM attachments WHERE id IN ({placeholders}) ORDER BY created_at",
        tuple(att_ids),
    )
    return [dict(r) for r in rows]


async def list_window(
    db: Database,
    conversation_id: str,
    *,
    message_ids: list[str],
    since_ts: int,
) -> list[dict[str, Any]]:
    """窗口内附件：绑定到窗口消息的图 + 尚未绑定消息的新上传图（按时间兜底）。"""
    clauses = ["(message_id IS NULL AND created_at >= ?)"]
    params: list[Any] = [since_ts]
    if message_ids:
        placeholders = ",".join("?" for _ in message_ids)
        clauses.insert(0, f"message_id IN ({placeholders})")
        params = [*message_ids, since_ts]
    rows = await db.fetchall(
        f"""SELECT * FROM attachments
             WHERE conversation_id = ? AND ({" OR ".join(clauses)})
             ORDER BY created_at""",
        (conversation_id, *params),
    )
    return [dict(r) for r in rows]


async def bind_message(db: Database, att_ids: list[str], message_id: str) -> None:
    if not att_ids:
        return
    placeholders = ",".join("?" for _ in att_ids)
    await db.execute(
        f"UPDATE attachments SET message_id = ? WHERE id IN ({placeholders})",
        (message_id, *att_ids),
    )
