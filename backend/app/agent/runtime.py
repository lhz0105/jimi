"""RunRuntime：一次分析运行的全部共享依赖（注入图状态与工具闭包）。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel

from app.config import Settings
from app.db.database import Database
from app.llm.pricing import PriceTable, load_prices
from app.observability.bus import EventBus
from app.observability.emitter import RunEmitter

MAX_TOOL_RESULT_CHARS = 800


@dataclass
class RunRuntime:
    run_id: str
    db: Database
    settings: Settings
    emitter: RunEmitter
    bus: EventBus
    budget: dict[str, Any]
    cancel_event: asyncio.Event
    case: dict[str, Any] = field(default_factory=dict)
    prices: PriceTable | None = None
    llm_main: BaseChatModel | None = None
    llm_vision: BaseChatModel | None = None
    kb: Any = None
    prior_cases: Any = None
    verdict: dict[str, Any] | None = None
    node_progress: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.prices is None:
            self.prices = load_prices(self.settings)

    # 图片索引：sha256 -> {path, mime, width, height}
    @property
    def images(self) -> list[dict[str, Any]]:
        return list(self.case.get("images") or [])

    def image_by_sha(self, sha256: str) -> dict[str, Any] | None:
        """按完整 sha256 或清单中的前缀定位图片（容忍 sha256: 前缀与末尾省略号）。"""
        wanted = (sha256 or "").strip().lower()
        if wanted.startswith("sha256:"):
            wanted = wanted[len("sha256:"):]
        wanted = wanted.rstrip("…. ").strip()
        if not wanted:
            return None
        for image in self.images:
            if (image.get("sha256") or "").lower() == wanted:
                return image
        if len(wanted) >= 8:
            matches = [
                image
                for image in self.images
                if (image.get("sha256") or "").lower().startswith(wanted)
            ]
            if len(matches) == 1:
                return matches[0]
        return None

    def workspace_dir(self):
        path = self.settings.workspace_dir / self.run_id
        path.mkdir(parents=True, exist_ok=True)
        return path
