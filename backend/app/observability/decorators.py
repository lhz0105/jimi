"""图节点装饰器：node_start/node_end 事件、取消检查、进度更新。"""

from __future__ import annotations

import functools
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core.errors import RunCancelled
from app.observability.context import current_node
from app.observability.events import EventType

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _check_cancelled(state: dict[str, Any]) -> None:
    cancel_event = state.get("_cancel_event")
    if cancel_event is not None and cancel_event.is_set():
        raise RunCancelled("运行已被取消")


async def _update_progress(state: dict[str, Any], node: str) -> None:
    runtime = state.get("_runtime")
    if runtime is None:
        return
    progress_map: dict[str, int] = getattr(runtime, "node_progress", None) or {}
    percent = progress_map.get(node)
    db = getattr(runtime, "db", None)
    run_id = getattr(runtime, "run_id", None)
    if percent is None or db is None or run_id is None:
        return
    try:
        from app.db.repositories import runs as runs_repo

        await runs_repo.set_progress(db, run_id, {"node": node, "percent": percent})
    except Exception:  # pragma: no cover - 进度并非关键路径
        pass


def observed_node(name: str) -> Callable[[NodeFn], NodeFn]:
    """装饰图节点：发 node_start/node_end、检查取消、刷新进度。"""

    def decorator(fn: NodeFn) -> NodeFn:
        @functools.wraps(fn)
        async def wrapper(state: dict[str, Any]) -> dict[str, Any]:
            emitter = state.get("_emitter")
            token = current_node.set(name)
            started = time.perf_counter()
            if emitter is not None:
                emitter.emit(EventType.NODE_START, {"node": name}, node=name)
            _check_cancelled(state)
            await _update_progress(state, name)
            try:
                result = await fn(state)
            except RunCancelled:
                if emitter is not None:
                    emitter.emit(
                        EventType.WARNING,
                        {"code": "RUN_CANCELLED", "message": f"节点 {name} 被取消"},
                        node=name,
                        level="warn",
                    )
                raise
            except Exception as exc:
                if emitter is not None:
                    emitter.emit(
                        EventType.ERROR,
                        {"code": "NODE_ERROR", "message": str(exc), "fatal": True},
                        node=name,
                        level="error",
                    )
                raise
            finally:
                current_node.reset(token)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if emitter is not None:
                keys = sorted(result.keys()) if isinstance(result, dict) else []
                emitter.emit(
                    EventType.NODE_END,
                    {"node": name, "latency_ms": latency_ms, "state_delta_keys": keys},
                    node=name,
                )
            return result

        return wrapper

    return decorator
