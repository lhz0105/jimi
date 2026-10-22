"""演示平台自己的轻量存储（SQLite）：会话 / 消息 / 图片 / 分析记录。

与 agent 服务完全独立；agent 侧只通过对外 HTTP 接口交互。
"""

from __future__ import annotations

import asyncio
import json
import secrets
import time
from pathlib import Path
from typing import Any, Sequence

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  customer_name TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL DEFAULT 'demo',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  check_result TEXT,
  created_at INTEGER NOT NULL,
  UNIQUE(conversation_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, seq);

CREATE TABLE IF NOT EXISTS attachments (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  message_id TEXT,
  sha256 TEXT NOT NULL,
  mime TEXT NOT NULL,
  path TEXT NOT NULL,
  width INTEGER,
  height INTEGER,
  bytes INTEGER,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_attachments_conv ON attachments(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS analyses (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  run_id TEXT NOT NULL,
  decision_id TEXT,
  scenario TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  risk_level TEXT,
  confidence REAL,
  verdict TEXT,
  cost_json TEXT NOT NULL DEFAULT '{}',
  last_error TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analyses_conv ON analyses(conversation_id, created_at DESC);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(4)}"


class Store:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("store not connected")
        return self._conn

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _write(self, sql: str, params: Sequence[Any] = ()) -> int:
        async with self._lock:
            cur = await self.conn.execute(sql, params)
            await self.conn.commit()
            return cur.rowcount

    async def _fetchone(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        cur = await self.conn.execute(sql, params)
        row = await cur.fetchone()
        await cur.close()
        return dict(row) if row else None

    async def _fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cur = await self.conn.execute(sql, params)
        rows = await cur.fetchall()
        await cur.close()
        return [dict(r) for r in rows]

    # ------------------------------ 会话 ------------------------------

    async def create_conversation(self, *, customer_name: str, channel: str = "demo") -> dict[str, Any]:
        conv_id = new_id("conv")
        ts = now_ms()
        await self._write(
            "INSERT INTO conversations(id, customer_name, channel, created_at, updated_at) VALUES (?,?,?,?,?)",
            (conv_id, customer_name, channel, ts, ts),
        )
        return (await self.get_conversation(conv_id)) or {}

    async def get_conversation(self, conv_id: str) -> dict[str, Any] | None:
        return await self._fetchone("SELECT * FROM conversations WHERE id = ?", (conv_id,))

    async def delete_conversation(self, conv_id: str) -> bool:
        """删除会话及其消息/图片/分析记录；图片文件仅在没有其他会话引用时移除。"""
        attachments = await self.list_attachments(conv_id)
        async with self._lock:
            conn = self.conn
            await conn.execute("DELETE FROM analyses WHERE conversation_id = ?", (conv_id,))
            await conn.execute("DELETE FROM attachments WHERE conversation_id = ?", (conv_id,))
            await conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
            cur = await conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
            await conn.commit()
            deleted = cur.rowcount > 0
        if deleted:
            for att in attachments:
                remaining = await self._fetchone(
                    "SELECT 1 FROM attachments WHERE path = ? LIMIT 1", (att["path"],)
                )
                if remaining is None:
                    try:
                        Path(att["path"]).unlink(missing_ok=True)
                    except OSError:
                        pass
        return deleted

    async def list_conversations(self) -> list[dict[str, Any]]:
        return await self._fetchall(
            """SELECT c.*,
                      (SELECT content FROM messages m WHERE m.conversation_id = c.id
                        ORDER BY m.seq DESC LIMIT 1) AS last_message,
                      (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count
                 FROM conversations c ORDER BY c.updated_at DESC"""
        )

    async def touch_conversation(self, conv_id: str) -> None:
        await self._write("UPDATE conversations SET updated_at = ? WHERE id = ?", (now_ms(), conv_id))

    # ------------------------------ 消息 ------------------------------

    async def add_message(
        self,
        *,
        conversation_id: str,
        role: str,
        content: str,
        check_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        msg_id = new_id("msg")
        ts = now_ms()
        async with self._lock:
            row = await (
                await self.conn.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM messages WHERE conversation_id = ?",
                    (conversation_id,),
                )
            ).fetchone()
            seq = int(row["n"])
            await self.conn.execute(
                """INSERT INTO messages(id, conversation_id, seq, role, content, check_result, created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (
                    msg_id,
                    conversation_id,
                    seq,
                    role,
                    content,
                    json.dumps(check_result, ensure_ascii=False) if check_result else None,
                    ts,
                ),
            )
            await self.conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?", (ts, conversation_id)
            )
            await self.conn.commit()
        message = await self._fetchone("SELECT * FROM messages WHERE id = ?", (msg_id,))
        return _message_out(message)

    async def list_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        rows = await self._fetchall(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY seq", (conversation_id,)
        )
        return [_message_out(r) for r in rows]

    async def update_message_check(self, message_id: str, check_result: dict[str, Any]) -> None:
        await self._write(
            "UPDATE messages SET check_result = ? WHERE id = ?",
            (json.dumps(check_result, ensure_ascii=False), message_id),
        )

    # ------------------------------ 附件 ------------------------------

    async def add_attachment(
        self,
        *,
        conversation_id: str,
        sha256: str,
        mime: str,
        path: str,
        width: int | None,
        height: int | None,
        size_bytes: int | None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        att_id = new_id("att")
        await self._write(
            """INSERT INTO attachments(id, conversation_id, message_id, sha256, mime, path,
                                       width, height, bytes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (att_id, conversation_id, message_id, sha256, mime, path, width, height, size_bytes, now_ms()),
        )
        return (await self._fetchone("SELECT * FROM attachments WHERE id = ?", (att_id,))) or {}

    async def list_attachments(self, conversation_id: str) -> list[dict[str, Any]]:
        return await self._fetchall(
            "SELECT * FROM attachments WHERE conversation_id = ? ORDER BY created_at",
            (conversation_id,),
        )

    async def find_attachment(self, sha256: str) -> dict[str, Any] | None:
        return await self._fetchone(
            "SELECT * FROM attachments WHERE sha256 = ? ORDER BY created_at LIMIT 1", (sha256,)
        )

    async def find_conv_attachment(self, conversation_id: str, sha256: str) -> dict[str, Any] | None:
        return await self._fetchone(
            "SELECT * FROM attachments WHERE conversation_id = ? AND sha256 = ? LIMIT 1",
            (conversation_id, sha256),
        )

    async def bind_attachments(self, att_ids: list[str], message_id: str) -> None:
        if not att_ids:
            return
        placeholders = ",".join("?" for _ in att_ids)
        await self._write(
            f"UPDATE attachments SET message_id = ? WHERE id IN ({placeholders})",
            (message_id, *att_ids),
        )

    # ------------------------------ 分析 ------------------------------

    async def create_analysis(
        self,
        *,
        conversation_id: str,
        run_id: str,
        decision_id: str | None,
        scenario: str | None,
        status: str,
    ) -> dict[str, Any]:
        analysis_id = new_id("ana")
        ts = now_ms()
        await self._write(
            """INSERT INTO analyses(id, conversation_id, run_id, decision_id, scenario, status,
                                    created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (analysis_id, conversation_id, run_id, decision_id, scenario, status, ts, ts),
        )
        return (await self.get_analysis(analysis_id)) or {}

    async def get_analysis(self, analysis_id: str) -> dict[str, Any] | None:
        return await self._fetchone("SELECT * FROM analyses WHERE id = ?", (analysis_id,))

    async def find_analysis_by_run(
        self, conversation_id: str, run_id: str
    ) -> dict[str, Any] | None:
        return await self._fetchone(
            """SELECT * FROM analyses WHERE conversation_id = ? AND run_id = ?
               ORDER BY created_at DESC LIMIT 1""",
            (conversation_id, run_id),
        )

    async def list_analyses(self, conversation_id: str) -> list[dict[str, Any]]:
        return await self._fetchall(
            "SELECT * FROM analyses WHERE conversation_id = ? ORDER BY created_at DESC",
            (conversation_id,),
        )

    async def update_analysis(
        self,
        analysis_id: str,
        *,
        status: str | None = None,
        risk_level: str | None = None,
        confidence: float | None = None,
        verdict: dict[str, Any] | None = None,
        cost: dict[str, Any] | None = None,
        last_error: str | None = None,
    ) -> None:
        sets = ["updated_at = ?"]
        params: list[Any] = [now_ms()]
        if status is not None:
            sets.append("status = ?")
            params.append(status)
        if risk_level is not None:
            sets.append("risk_level = ?")
            params.append(risk_level)
        if confidence is not None:
            sets.append("confidence = ?")
            params.append(confidence)
        if verdict is not None:
            sets.append("verdict = ?")
            params.append(json.dumps(verdict, ensure_ascii=False))
        if cost is not None:
            sets.append("cost_json = ?")
            params.append(json.dumps(cost, ensure_ascii=False))
        if last_error is not None:
            sets.append("last_error = ?")
            params.append(last_error)
        params.append(analysis_id)
        await self._write(f"UPDATE analyses SET {', '.join(sets)} WHERE id = ?", tuple(params))


def _message_out(row: dict[str, Any] | None) -> dict[str, Any]:
    if row is None:
        return {}
    data = dict(row)
    raw = data.get("check_result")
    data["check_result"] = json.loads(raw) if raw else None
    return data
