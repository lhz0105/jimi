"""事件发射器与总线测试：seq 单调、先落库后发布、订阅/取消订阅。"""

from __future__ import annotations

import asyncio

from app.db.repositories import events as events_repo
from app.observability.bus import EventBus
from app.observability.emitter import RunEmitter


async def test_seq_monotonic_and_persisted(db) -> None:
    bus = EventBus()
    emitter = RunEmitter("run_test1", db, bus, flush_interval_ms=10, flush_batch=2)
    emitter.start()
    for i in range(5):
        emitter.emit("node_start", {"i": i})
    await asyncio.sleep(0.1)
    await emitter.close()

    events = await events_repo.list_after(db, "run_test1", limit=100)
    assert [e["seq"] for e in events] == [1, 2, 3, 4, 5]
    assert all(e["type"] == "node_start" for e in events)
    assert events[0]["payload"] == {"i": 0}
    assert emitter.last_seq == 5


async def test_published_after_persisted(db) -> None:
    """收到事件时，DB 中必须已存在该 seq（SSE 可回放的保证）。"""
    bus = EventBus()
    emitter = RunEmitter("run_test2", db, bus, flush_interval_ms=5, flush_batch=1)
    emitter.start()

    seen: list[tuple[int, bool]] = []
    async with bus.subscribe("run_test2") as queue:
        emitter.emit("evidence", {"x": 1})
        event = await asyncio.wait_for(queue.get(), timeout=2)
        persisted = await events_repo.max_seq(db, "run_test2")
        seen.append((event["seq"], persisted >= event["seq"]))
    await emitter.close()

    assert seen == [(1, True)]


async def test_unsubscribe_stops_delivery(db) -> None:
    bus = EventBus()
    emitter = RunEmitter("run_test3", db, bus, flush_interval_ms=5, flush_batch=1)
    emitter.start()
    async with bus.subscribe("run_test3") as queue:
        pass  # 立即退出订阅
    emitter.emit("warn", {})
    await asyncio.sleep(0.05)
    assert bus.run_subscriber_count("run_test3") == 0
    await emitter.close()


async def test_events_published_after_flush(db) -> None:
    """flush 后事件应到达订阅者（先落库后发布的另一半）。"""
    bus = EventBus()
    emitter = RunEmitter("run_test4", db, bus, flush_interval_ms=5, flush_batch=1)
    emitter.start()
    async with bus.subscribe("run_test4") as queue:
        for i in range(3):
            emitter.emit("x", {"i": i}, node=None)
        await asyncio.sleep(0.1)
        received = []
        while not queue.empty():
            received.append(queue.get_nowait()["payload"]["i"])
        assert received == [0, 1, 2]
    await emitter.close()


async def test_slow_consumer_drops_oldest(monkeypatch) -> None:
    """队列打满时丢弃最旧事件而不是抛错/阻塞。"""
    import app.observability.bus as bus_module

    monkeypatch.setattr(bus_module, "QUEUE_MAX", 3)
    bus = EventBus()
    async with bus.subscribe("run_x") as queue:
        for i in range(10):
            bus.publish({"run_id": "run_x", "seq": i, "type": "x", "payload": {}})
        assert queue.qsize() == 3
        remaining = [queue.get_nowait()["seq"] for _ in range(3)]
        assert remaining == [7, 8, 9]  # 保留最新的 3 条
