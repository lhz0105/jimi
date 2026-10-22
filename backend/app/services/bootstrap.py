"""组件装配与关闭：rules / bus / runner / kb 的构建入口。"""

from __future__ import annotations

import logging

from app.deps import AppState
from app.observability.bus import EventBus
from app.rules.loader import RulesService
from app.services.decision_cache import DecisionCache

logger = logging.getLogger(__name__)


async def build_components(state: AppState) -> None:
    # 规则引擎
    rules = RulesService()
    rules.load()
    state.rules = rules
    state.extra["decision_cache"] = DecisionCache()

    # 事件总线（进程内 pub/sub；必须单 worker）
    state.bus = EventBus()

    # 知识库（RAG）：后台初始化（首次可能需下载向量模型），不阻塞服务启动。
    # 初始化完成后，把同一个向量模型接到"语义触发通道"（规则引擎的余弦相似度判定）。
    if state.settings.kb_enabled:
        try:
            import asyncio

            from app.services.kb_service import KbService

            kb = KbService(state.settings, state.db)
            state.kb = kb
            state.extra["kb_init_task"] = asyncio.create_task(
                _init_kb_and_wire_semantics(kb, state), name="kb-init"
            )
        except Exception as exc:  # pragma: no cover - KB 不可用不阻塞服务
            logger.warning("knowledge base unavailable: %s", exc)
    else:
        logger.info("knowledge base disabled (KB_ENABLED=false)")
        if state.settings.prior_case_enabled:
            import asyncio

            from app.services.prior_case_service import PriorCaseService

            service = PriorCaseService(state.settings, state.db)
            state.prior_cases = service
            state.extra["prior_case_service"] = service
            state.extra["prior_case_init_task"] = asyncio.create_task(
                _init_prior_cases(service), name="prior-case-init"
            )

    # 分析运行器（LangGraph 图）
    from app.agent.runner import AnalysisRunner

    state.runner = AnalysisRunner(state)

    # 历史运行的人工复核资格回填（迁移新增列后执行一次；幂等）
    try:
        await _backfill_review_required(state)
    except Exception as exc:  # pragma: no cover - 回填失败不影响启动
        logger.warning("review_required backfill failed: %s", exc)

    # 过期事件清理（写入频繁的表，按保留期截断）
    try:
        from app.core.clock import now_ms
        from app.db.repositories import events as events_repo

        cutoff = now_ms() - state.settings.event_retention_days * 86400_000
        deleted = await events_repo.delete_older_than(state.db, cutoff)
        if deleted:
            logger.info("expired run_events cleaned: %d", deleted)
    except Exception as exc:  # pragma: no cover - 清理失败不影响启动
        logger.warning("event retention cleanup failed: %s", exc)

    # 演示数据（不触发分析，无 LLM 成本）
    if state.settings.demo_seed_on_start:
        from app.services import demo_service

        created = await demo_service.seed_all_on_startup(state)
        if created:
            logger.info("demo conversations seeded: %s", ", ".join(created))


async def _init_kb_and_wire_semantics(kb: object, state: AppState) -> None:
    """KB 初始化（内部自带降级）后，把向量模型接入规则引擎的语义通道。"""
    await kb.initialize()  # type: ignore[attr-defined]
    embedder = getattr(kb, "embedder", None)
    if embedder is None or state.rules is None:
        return
    from app.rules.semantic import SemanticMatcher

    matcher = SemanticMatcher(
        embedder,
        max_clauses=state.rules.ruleset.semantic.max_clauses,
    )
    state.rules.set_semantic_matcher(matcher)
    semantic = state.rules.ruleset.semantic
    if matcher.available and semantic.enabled:
        logger.info(
            "semantic trigger channel ready: threshold=%.2f anchors=%s",
            semantic.threshold,
            ",".join(semantic.anchors.keys()),
        )
    else:
        logger.info("semantic trigger channel unavailable（触发判断退回纯关键词）")

    if state.settings.prior_case_enabled:
        try:
            from app.services.prior_case_service import PriorCaseService

            service = PriorCaseService(state.settings, state.db, embedder=embedder)
            await service.initialize()
            state.prior_cases = service
            state.extra["prior_case_service"] = service
        except Exception:
            logger.exception("prior case service init failed")


async def _init_prior_cases(service: object) -> None:
    await service.initialize()  # type: ignore[attr-defined]


async def _backfill_review_required(state: AppState) -> None:
    from app.db.repositories import runs as runs_repo
    from app.db.repositories.util import loads_json
    from app.services.review_policy import requires_review

    rows = await state.db.fetchall(
        "SELECT id, verdict FROM analysis_runs WHERE review_required = 0 AND verdict IS NOT NULL"
    )
    changed = 0
    for row in rows:
        if requires_review(loads_json(row["verdict"], {})):
            await runs_repo.set_review_required(state.db, row["id"], True)
            changed += 1
    if changed:
        logger.info("review_required backfilled: %d runs", changed)


async def shutdown_components(state: AppState) -> None:
    if state.runner is not None:
        await state.runner.shutdown()
    for key in ("kb_init_task", "prior_case_init_task"):
        task = state.extra.get(key)
        if task is not None and not task.done():
            task.cancel()
