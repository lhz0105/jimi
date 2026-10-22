"""演示客服平台后端入口（独立服务，端口 8001）。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse

from app.agent_client import AgentClient, AgentError
from app.api import files_router, router
from app.config import get_settings
from app.store import Store

logger = logging.getLogger("demo_platform")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    settings.ensure_dirs()
    store = Store(settings.db_path)
    await store.connect()
    agent = AgentClient(settings.agent_base_url, settings.agent_api_key, timeout_s=settings.agent_timeout_s)
    app.state.settings = settings
    app.state.store = store
    app.state.agent = agent
    logger.info(
        "demo platform ready: db=%s agent=%s", settings.db_path, settings.agent_base_url
    )
    try:
        yield
    finally:
        await agent.close()
        await store.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="迹觅·Evidence 客服演示台（Demo CS Platform）",
        description="迹觅·Evidence 模拟客服平台：独立后端与数据库，完全通过 agent 对外接口 /api/v1/analyze 完成分析",
        version="0.1.0",
        lifespan=lifespan,
        default_response_class=ORJSONResponse,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

    @app.exception_handler(AgentError)
    async def _agent_error(_: Request, exc: AgentError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status or 502,
            content={"error": {"code": exc.code, "message": str(exc)}},
        )

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {"service": "lumi-demo-cs-platform", "docs": "/docs", "api": "/api/health"}

    app.include_router(router)
    app.include_router(files_router())
    return app


app = create_app()

