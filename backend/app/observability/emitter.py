"""运行事件发射器：seq 单调分配 → 批量落库 → 发布总线。

保证：先写库后发布（DB 里有的，SSE 一定能回放）。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.clock import now_ms
from app.db.database import Database
from app.db.repositories import events as events_repo
from app.observability.bus import EventBus
from app.observability.events import PROTOCOL_VERSION, EventType

logger = logging.getLogger(__name__)

_FLUSH_TIMEOUT_S = 0.5


class RunEmitter:
    def __init__(
        self,
        run_id: str,
        db: Database,
        bus: EventBus,
        *,
        flush_interval_ms: int = 50,
        flush_batch: int = 20,
        persist: bool = True,
    ) -> None:
        self.run_id = run_id
        self._db = db
        self._bus = bus
        self._interval = max(flush_interval_ms, 5) / 1000
        self._batch = max(flush_batch, 1)
        self._persist = persist
        self._seq = 0
        self._buffer: list[dict[str, Any]] = []
        self._wake = asyncio.Event()
        self._closed = False
        self._task: asyncio.Task | None = None

    # ---- 生命周期 ----

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name=f"emitter-{self.run_id}")

    async def close(self) -> None:
        self._closed = True
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=_FLUSH_TIMEOUT_S * 4)
            except (TimeoutError, asyncio.CancelledError):  # pragma: no cover
                self._task.cancel()
        await self.flush()

    async def _loop(self) -> None:
        while not self._closed:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except TimeoutError:
                pass
            self._wake.clear()
            try:
                await self.flush()
            except Exception:  # pragma: no cover
                logger.exception("event flush failed (run=%s)", self.run_id)

    # ---- 发射 ----

    @property
    def last_seq(self) -> int:
        return self._seq

    def emit(
        self,
        event_type: EventType | str,
        payload: dict[str, Any] | None = None,
        *,
        node: str | None = None,
        level: str = "info",
    ) -> dict[str, Any]:
        self._seq += 1
        event = {
            "v": PROTOCOL_VERSION,
            "run_id": self.run_id,
            "seq": self._seq,
            "ts": now_ms(),
            "type": str(event_type),
            "node": node,
            "level": level,
            "payload": payload or {},
        }
        self._buffer.append(event)
        if len(self._buffer) >= self._batch:
            self._wake.set()
        return event

    # ---- 落库 + 发布 ----

    async def flush(self) -> None:
        if not self._buffer:
            return
        batch, self._buffer = self._buffer, []
        if self._persist:
            try:
                await events_repo.insert_batch(self._db, batch)
            except Exception:
                logger.exception("event persist failed (run=%s), publishing anyway", self.run_id)
        for event in batch:
            self._bus.publish(event)
