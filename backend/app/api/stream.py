"""SSE 实时事件流（对外/管理/演示共用）。

流程：先订阅总线 → 回放 DB（seq > from）→ 缓冲增量按 seq 去重续发；
断线重连经 Last-Event-ID 续传；终态 run 回放完即关闭。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

import orjson
from fastapi import Request

from app.core.errors import NotFoundError
from app.db.repositories import events as events_repo
from app.db.repositories import runs as runs_repo
from app.deps import AppState
from app.observability.events import EventType

logger = logging.getLogger(__name__)

_TERMINAL = ("succeeded", "failed", "cancelled")
_LIVE_POLL_S = 1.0
_REPLAY_BATCH = 500


def _sse_message(event: dict) -> dict:
    return {
        "id": str(event["seq"]),
        "event": str(event["type"]),
        "data": orjson.dumps(event).decode("utf-8"),
    }


async def run_event_stream(
    state: AppState, request: Request, run_id: str, from_seq: int = 0
) -> AsyncIterator[dict]:
    """订阅 + 回放 + 增量的生成器。"""
    run = await runs_repo.get(state.db, run_id)
    if run is None:
        raise NotFoundError(f"运行不存在: {run_id}")

    bus = state.bus
    if bus is None:  # pragma: no cover - bus 在启动时装配
        raise NotFoundError("事件总线未就绪")

    last_seq = max(from_seq, 0)
    state.sse_connections += 1
    try:
        async with bus.subscribe(run_id) as queue:
            # 1) 回放 DB（订阅已建立，期间新事件在 queue 中缓冲）
            while True:
                batch = await events_repo.list_after(
                    state.db, run_id, since_seq=last_seq, limit=_REPLAY_BATCH
                )
                if not batch:
                    break
                for event in batch:
                    if await request.is_disconnected():
                        return
                    last_seq = event["seq"]
                    yield _sse_message(event)

            # 2) 终态判断：DB 已追平且 run 已终止 → 直接结束
            if await _is_done(state, run_id, last_seq):
                return

            # 3) 增量（丢弃回放期间已发过的 seq）
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=_LIVE_POLL_S)
                except TimeoutError:
                    if await _is_done(state, run_id, last_seq):
                        return
                    continue
                if event["seq"] <= last_seq:
                    continue
                last_seq = event["seq"]
                yield _sse_message(event)
                if event["type"] == str(EventType.RUN_END):
                    return
    finally:
        state.sse_connections -= 1


async def _is_done(state: AppState, run_id: str, last_seq: int) -> bool:
    run = await runs_repo.get(state.db, run_id)
    if run is None or run["status"] not in _TERMINAL:
        return False
    max_seq = await events_repo.max_seq(state.db, run_id)
    return last_seq >= max_seq


def resolve_from_seq(request: Request, from_seq: int) -> int:
    """Last-Event-ID 优先于 ?from_seq=。"""
    header = request.headers.get("Last-Event-ID")
    if header:
        try:
            return max(int(header), 0)
        except ValueError:
            pass
    return max(from_seq, 0)
