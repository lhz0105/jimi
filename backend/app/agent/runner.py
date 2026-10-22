"""AnalysisRunner：建 run、后台驱动图、确认/取消、终态收口。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.agent.budget import new_budget
from app.agent.graph import RECURSION_LIMIT, build_graph
from app.agent.runtime import RunRuntime
from app.agent.state import NODE_PROGRESS
from app.core.clock import now_ms
from app.core.errors import AppError, InvalidRunState, NotFoundError, RunCancelled
from app.core.ids import new_id
from app.db.repositories import confirmations as confirmations_repo
from app.db.repositories import runs as runs_repo
from app.deps import AppState
from app.observability.emitter import RunEmitter
from app.observability.events import EventType

logger = logging.getLogger(__name__)

TERMINAL = ("succeeded", "failed", "cancelled")


class AnalysisRunner:
    def __init__(self, app_state: AppState) -> None:
        self._app = app_state
        self._graph = build_graph()
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._emitters: dict[str, RunEmitter] = {}
        self._inline_payloads: dict[str, Any] = {}

    # ------------------------------------------------------------ 启动

    async def start_run(
        self,
        *,
        conversation_id: str | None,
        scenario: str,
        trigger_mode: str,
        auto_confirm: bool,
        rules_decision: dict[str, Any],
        input_snapshot: dict[str, Any],
        inline: Any = None,
        external_ref: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        db = self._app.db

        if idempotency_key:
            existing = await runs_repo.get_by_idempotency(db, idempotency_key)
            if existing is not None:
                return existing

        # 早期校验 LLM 配置：配置错误直接拒绝，不产生半途失败的 run
        llm_main, llm_vision = self._build_llms()

        run_id = new_id("run")
        status = "running" if auto_confirm else "awaiting_confirm"

        try:
            run = await runs_repo.create(
                db,
                run_id=run_id,
                conversation_id=conversation_id,
                scenario=scenario,
                trigger_mode=trigger_mode,
                status=status,
                rules_decision=rules_decision,
                input_snapshot=input_snapshot,
                external_ref=external_ref,
                idempotency_key=idempotency_key,
                callback_url=callback_url,
            )
        except Exception as exc:  # 幂等键并发写入等
            if idempotency_key:
                existing = await runs_repo.get_by_idempotency(db, idempotency_key)
                if existing is not None:
                    return existing
            raise AppError(f"创建运行失败: {exc}") from exc

        emitter = self._make_emitter(run_id)
        self._cancel_events[run_id] = asyncio.Event()
        self._emitters[run_id] = emitter
        if inline is not None:
            self._inline_payloads[run_id] = inline
        emitter.start()

        if status == "awaiting_confirm":
            emitter.emit(
                EventType.RUN_QUEUED,
                {"trigger_mode": trigger_mode, "scenario": scenario},
            )
            emitter.emit(
                EventType.RUN_AWAITING_CONFIRM,
                {"prompt_text": "检测到疑似欺诈场景，是否开始分析？"},
            )
            await emitter.flush()
        else:
            emitter.emit(
                EventType.RUN_QUEUED,
                {"trigger_mode": trigger_mode, "scenario": scenario},
            )
            self._launch(run_id, llm_main, llm_vision, inline)

        return run

    # ------------------------------------------------------------ 确认 / 取消

    async def confirm_run(self, run_id: str, *, decided_by: str = "api") -> dict[str, Any]:
        db = self._app.db
        run = await runs_repo.get(db, run_id)
        if run is None:
            raise NotFoundError(f"运行不存在: {run_id}")

        if run["status"] != "awaiting_confirm":
            # 幂等：已在运行/已结束则原样返回
            return run

        await confirmations_repo.add(db, run_id=run_id, decision="confirm", decided_by=decided_by)
        emitter = self._emitters.get(run_id) or self._make_emitter(run_id)
        self._emitters[run_id] = emitter
        emitter.start()
        self._cancel_events.setdefault(run_id, asyncio.Event())
        emitter.emit(EventType.RUN_CONFIRMED, {"decided_by": decided_by})

        llm_main, llm_vision = self._build_llms()
        inline = self._inline_payloads.get(run_id)
        self._launch(run_id, llm_main, llm_vision, inline)
        updated = await runs_repo.get(db, run_id) or run
        # 后台任务可能尚未把状态刷成 running（或已极快完成），返回视图与实际一致
        task = self._tasks.get(run_id)
        if updated["status"] == "awaiting_confirm" and task is not None and not task.done():
            updated = {**updated, "status": "running"}
        return updated

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        db = self._app.db
        run = await runs_repo.get(db, run_id)
        if run is None:
            raise NotFoundError(f"运行不存在: {run_id}")
        if run["status"] in TERMINAL:
            return run

        await confirmations_repo.add(db, run_id=run_id, decision="cancel", decided_by="api")
        cancel_event = self._cancel_events.get(run_id)
        if cancel_event is not None:
            cancel_event.set()

        if run["status"] == "awaiting_confirm":
            await runs_repo.update_status(db, run_id, "cancelled", mark_finished=True)
            emitter = self._emitters.get(run_id) or self._make_emitter(run_id)
            self._emitters[run_id] = emitter
            emitter.start()
            emitter.emit(EventType.RUN_END, {"status": "cancelled", "cost": {}}, node="runner")
            await emitter.close()
            self._cleanup(run_id)
        else:
            # 运行中：立即置为 cancelled 保证查询一致性；runner 收口时会再次确认并补发 run_end
            await runs_repo.update_status(db, run_id, "cancelled", mark_finished=True)
        updated = await runs_repo.get(db, run_id)
        return updated or run

    # ------------------------------------------------------------ 内部

    def _build_llms(self):
        from app.llm.gateway import build_main_llm, build_vision_llm

        settings = self._app.settings
        try:
            llm_main = build_main_llm(settings)
        except Exception as exc:
            raise AppError(f"主模型不可用: {exc}", detail={"hint": "检查 .env 网关配置或设 LLM_MODE=fake"}) from exc
        try:
            llm_vision = build_vision_llm(settings)
        except Exception as exc:
            logger.warning("vision model unavailable: %s", exc)
            llm_vision = None
        return llm_main, llm_vision

    def _make_emitter(self, run_id: str) -> RunEmitter:
        settings = self._app.settings
        return RunEmitter(
            run_id,
            self._app.db,
            self._app.bus,  # type: ignore[arg-type]
            flush_interval_ms=settings.event_flush_interval_ms,
            flush_batch=settings.event_flush_batch,
        )

    def _launch(self, run_id: str, llm_main: Any, llm_vision: Any, inline: Any) -> None:
        if run_id in self._tasks and not self._tasks[run_id].done():
            raise InvalidRunState(f"运行已在执行中: {run_id}")
        task = asyncio.create_task(
            self._run_graph(run_id, llm_main, llm_vision, inline), name=f"run-{run_id}"
        )
        self._tasks[run_id] = task

    async def _run_graph(self, run_id: str, llm_main: Any, llm_vision: Any, inline: Any) -> None:
        db = self._app.db
        settings = self._app.settings
        emitter = self._emitters[run_id]
        cancel_event = self._cancel_events[run_id]

        run = await runs_repo.get(db, run_id)
        if run is None:  # pragma: no cover
            return

        snapshot = run.get("input_snapshot") or {}
        runtime = RunRuntime(
            run_id=run_id,
            db=db,
            settings=settings,
            emitter=emitter,
            bus=self._app.bus,
            budget=new_budget(settings),
            cancel_event=cancel_event,
            llm_main=llm_main,
            llm_vision=llm_vision,
            kb=self._app.kb,
            prior_cases=self._app.prior_cases,
            node_progress=dict(NODE_PROGRESS),
        )
        runtime.callback_url = run.get("callback_url")  # type: ignore[attr-defined]
        runtime.started_at = now_ms()  # type: ignore[attr-defined]
        runtime.rules_version = self._app.rules.version if self._app.rules else ""  # type: ignore[attr-defined]

        inline_payload = inline if inline is not None else self._inline_payloads.get(run_id)
        initial_state: dict[str, Any] = {
            "run_id": run_id,
            "scenario": run["scenario"],
            "rule_decision": run.get("rules_decision") or {},
            "budget": runtime.budget,
            "_runtime": runtime,
            "_emitter": emitter,
            "_cancel_event": cancel_event,
            "_inputs": {
                "conversation_id": run.get("conversation_id"),
                "inline": inline_payload,
                "snapshot": snapshot,
            },
        }

        await runs_repo.update_status(db, run_id, "running", mark_started=True)
        try:
            await self._graph.ainvoke(
                initial_state,
                config={"recursion_limit": RECURSION_LIMIT},
            )
            # 成功路径：图完全退出后才发 run_end，保证它是本运行的最后一条事件
            from app.agent.budget import cost_summary

            started_at = getattr(runtime, "started_at", None)
            emitter.emit(
                EventType.RUN_END,
                {
                    "status": "succeeded",
                    "cost": cost_summary(runtime.budget),
                    "duration_ms": now_ms() - started_at if started_at else None,
                },
                node="runner",
            )
        except RunCancelled:
            await runs_repo.update_status(db, run_id, "cancelled", mark_finished=True)
            emitter.emit(EventType.RUN_END, {"status": "cancelled", "cost": {}}, node="runner")
        except Exception as exc:
            logger.exception("run %s failed", run_id)
            await runs_repo.update_status(
                db, run_id, "failed", error=str(exc), mark_finished=True
            )
            emitter.emit(
                EventType.ERROR,
                {"code": "RUN_FAILED", "message": str(exc), "fatal": True},
                level="error",
            )
            emitter.emit(EventType.RUN_END, {"status": "failed", "cost": {}}, node="runner")
        finally:
            try:
                await emitter.close()
            finally:
                self._cleanup(run_id)

    def _cleanup(self, run_id: str) -> None:
        self._tasks.pop(run_id, None)
        self._cancel_events.pop(run_id, None)
        self._emitters.pop(run_id, None)
        self._inline_payloads.pop(run_id, None)

    async def shutdown(self) -> None:
        for cancel_event in self._cancel_events.values():
            cancel_event.set()
        tasks = [t for t in self._tasks.values() if not t.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
