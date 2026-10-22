"""SQLite 访问层：单连接 + WAL + 应用层写锁 + 事务上下文。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("database not connected")
        return self._conn

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self._path))
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.commit()
        logger.info("sqlite connected: %s", self._path)

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    @asynccontextmanager
    async def write(self) -> AsyncIterator[aiosqlite.Connection]:
        """写事务：持有全局写锁，最多等待 10s（超时抛 TimeoutError）。"""
        async with asyncio.timeout(10):
            async with self._write_lock:
                conn = self.conn
                try:
                    yield conn
                    await conn.commit()
                except BaseException:
                    await conn.rollback()
                    raise

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        async with self.write() as conn:
            cur = await conn.execute(sql, params)
            return cur.rowcount

    async def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> int:
        async with self.write() as conn:
            cur = await conn.executemany(sql, list(seq))
            return cur.rowcount

    async def executescript(self, script: str) -> None:
        async with self._write_lock:
            await self.conn.executescript(script)
            await self.conn.commit()

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        cur = await self.conn.execute(sql, params)
        try:
            return await cur.fetchone()
        finally:
            await cur.close()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        cur = await self.conn.execute(sql, params)
        try:
            return list(await cur.fetchall())
        finally:
            await cur.close()

    async def fetchval(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = await self.fetchone(sql, params)
        if row is None:
            return None
        return row[0]
