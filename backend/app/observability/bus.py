"""进程内事件总线：按 run_id 的 pub/sub。

约束：EventBus 仅进程内有效，服务必须单 worker 运行（见 scripts/run_server.py）。
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)

QUEUE_MAX = 2000


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def subscribe(self, run_id: str) -> AsyncIterator[asyncio.Queue]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        async with self._lock:
            self._subs[run_id].add(queue)
        try:
            yield queue
        finally:
            async with self._lock:
                self._subs[run_id].discard(queue)
                if not self._subs[run_id]:
                    self._subs.pop(run_id, None)

    def publish(self, event: dict[str, Any]) -> None:
        queues = self._subs.get(event.get("run_id", ""))
        if not queues:
            return
        for queue in list(queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # 慢消费者：丢弃最旧事件，保证流不阻塞
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                except Exception:  # pragma: no cover
                    logger.warning("event bus queue overflow, event dropped")

    @property
    def subscriber_count(self) -> int:
        return sum(len(qs) for qs in self._subs.values())

    def run_subscriber_count(self, run_id: str) -> int:
        return len(self._subs.get(run_id, ()))
