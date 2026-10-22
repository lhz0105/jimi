"""FastAPI 依赖：应用状态容器与 API Key 鉴权。"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi import Header, Request

from app.config import Settings
from app.core.clock import now_ms
from app.core.errors import UnauthorizedError
from app.db.database import Database

if TYPE_CHECKING:  # 后续里程碑逐步接入，避免循环导入
    from app.agent.runner import AnalysisRunner
    from app.observability.bus import EventBus
    from app.rules.loader import RulesService
    from app.services.kb_service import KbService

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}
_DEFAULT_EXTERNAL_KEYS = {"", "change-me-ext"}
_DEFAULT_ADMIN_KEYS = {"", "change-me-admin"}


@dataclass
class AppState:
    settings: Settings
    db: Database
    started_at: int = field(default_factory=now_ms)
    # 以下组件在后续里程碑装配
    bus: EventBus | None = None
    rules: RulesService | None = None
    kb: KbService | None = None
    prior_cases: Any = None
    runner: AnalysisRunner | None = None
    sse_connections: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


def get_state(request: Request) -> AppState:
    return request.app.state.ctx


def _is_loopback(request: Request) -> bool:
    client = request.client
    return client is not None and client.host in _LOOPBACK_HOSTS


def _check_key(
    request: Request,
    provided: str,
    expected: str,
    default_values: set[str],
    header_name: str,
) -> None:
    if expected and expected not in default_values:
        if provided and hmac.compare_digest(provided, expected):
            return
        raise UnauthorizedError(f"无效的 {header_name}", detail={"header": header_name})
    # 仍是默认/空 key：仅允许本机回环访问
    if _is_loopback(request):
        return
    raise UnauthorizedError(
        "服务尚未配置 API Key，仅允许本机访问", detail={"header": header_name}
    )


async def require_external(request: Request, x_api_key: str = Header(default="")) -> None:
    state = get_state(request)
    _check_key(
        request,
        x_api_key,
        state.settings.external_api_key,
        _DEFAULT_EXTERNAL_KEYS,
        "X-API-Key",
    )


async def require_admin(request: Request, x_api_key: str = Header(default="")) -> None:
    state = get_state(request)
    _check_key(
        request,
        x_api_key,
        state.settings.admin_api_key,
        _DEFAULT_ADMIN_KEYS,
        "X-API-Key",
    )
