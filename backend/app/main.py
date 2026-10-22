"""FastAPI 应用入口：lifespan 装配全部组件，挂载三组路由。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import admin as admin_api
from app.api import admin_reviews as admin_reviews_api
from app.api import demo as demo_api
from app.api import v1_analyze as analyze_api
from app.config import get_settings
from app.core.errors import AppError
from app.db.database import Database
from app.db.migrate import migrate
from app.deps import AppState
from app.logging_setup import setup_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_json)
    settings.ensure_dirs()
    logger.info(
        "starting jimi-evidence backend (llm_mode=%s, data_dir=%s)",
        settings.llm_mode,
        settings.data_dir,
    )

    db = Database(settings.db_path)
    await db.connect()
    await migrate(db)

    state = AppState(settings=settings, db=db)
    app.state.ctx = state

    from app.services.bootstrap import build_components, shutdown_components

    await build_components(state)

    logger.info("startup complete")
    try:
        yield
    finally:
        await shutdown_components(state)
        await db.close()
        logger.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="迹觅·Evidence Agent API",
        version="0.1.0",
        description="迹觅·Evidence：客服欺骗识别（退款欺诈/单据真伪）与种草文案真伪分析 —— 高可观测多 Agent 后端",
        lifespan=lifespan,
    )

    # 管理台前端跨域（开发态走 Vite 代理，独立部署时走 CORS）
    origins = settings.cors_origin_list
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
        )

    @app.exception_handler(AppError)
    async def _app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content={
                "error": {"code": exc.code, "message": exc.message, "detail": exc.detail}
            },
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "请求参数校验失败",
                    "detail": exc.errors(),
                }
            },
        )

    @app.get("/", include_in_schema=False)
    async def root() -> dict:
        return {
            "service": "jimi-evidence-backend",
            "docs": "/docs",
            "admin": "/api/admin/health",
        }

    app.include_router(admin_api.router)
    app.include_router(admin_reviews_api.router)
    app.include_router(analyze_api.router)
    app.include_router(demo_api.router)
    app.include_router(demo_api.files_router)
    return app


app = create_app()
