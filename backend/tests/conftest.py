"""测试夹具：临时目录 Settings / 迁移后的 DB / 完整 AppState（fake LLM）。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import pytest_asyncio

from app.config import Settings
from app.db.database import Database
from app.db.migrate import migrate
from app.deps import AppState


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        db_path=tmp_path / "data" / "app.db",
        upload_dir=tmp_path / "data" / "uploads",
        workspace_dir=tmp_path / "data" / "workspace",
        report_dir=tmp_path / "data" / "reports",
        chroma_dir=tmp_path / "data" / "chroma",
        embedding_cache_dir=tmp_path / "data" / "models",
        kb_dir=tmp_path / "data" / "kb",
        kb_seed_dir=tmp_path / "kb_seed_absent",
        kb_enabled=False,
        prior_case_enabled=False,
        llm_mode="fake",
        demo_seed_on_start=False,
        event_flush_interval_ms=10,
        event_flush_batch=5,
    )


@pytest_asyncio.fixture
async def db(settings: Settings):
    settings.ensure_dirs()
    database = Database(settings.db_path)
    await database.connect()
    await migrate(database)
    try:
        yield database
    finally:
        await database.close()


@pytest_asyncio.fixture
async def app_state(settings: Settings, db: Database):
    from app.agent.runner import AnalysisRunner
    from app.observability.bus import EventBus
    from app.rules.loader import RulesService
    from app.services.decision_cache import DecisionCache

    state = AppState(settings=settings, db=db)
    state.bus = EventBus()
    state.rules = RulesService()
    state.rules.load()
    state.extra["decision_cache"] = DecisionCache()
    state.runner = AnalysisRunner(state)
    try:
        yield state
    finally:
        await state.runner.shutdown()


async def wait_for_run(
    db: Database, run_id: str, *, timeout_s: float = 20.0, interval_s: float = 0.05
) -> dict[str, Any]:
    """轮询等待运行进入终态。"""
    from app.db.repositories import runs as runs_repo

    elapsed = 0.0
    while elapsed < timeout_s:
        run = await runs_repo.get(db, run_id)
        if run is not None and run["status"] in ("succeeded", "failed", "cancelled"):
            return run
        await asyncio.sleep(interval_s)
        elapsed += interval_s
    run = await runs_repo.get(db, run_id)
    raise AssertionError(f"run {run_id} 未在 {timeout_s}s 内结束，当前状态: {run and run['status']}")
