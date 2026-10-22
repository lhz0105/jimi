"""灌入 3 个内置演示会话（不触发分析，无 LLM 成本）。

用法: python scripts/seed_demo_data.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:  # Windows 控制台默认 GBK，强制 UTF-8 输出
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover
    pass

from app.config import get_settings
from app.db.database import Database
from app.db.migrate import migrate
from app.deps import AppState
from app.rules.loader import RulesService
from app.services import demo_seed, demo_service
from app.services.decision_cache import DecisionCache


async def run() -> int:
    settings = get_settings()
    settings.ensure_dirs()

    db = Database(settings.db_path)
    await db.connect()
    try:
        await migrate(db)

        state = AppState(settings=settings, db=db)
        state.rules = RulesService()
        state.rules.load()
        state.extra["decision_cache"] = DecisionCache()

        for scenario in demo_seed.SCENARIO_NAMES:
            result = await demo_service.seed_new_conversation(state, scenario)
            print(
                f"[OK] {scenario}: conversation={result['conversation_id']} "
                f"messages={result['messages_created']} images={result['attachments_created']} "
                f"need_analysis={result['hint']['need_analysis']}"
            )
        return 0
    finally:
        # 必须关闭，否则 aiosqlite 工作线程会阻塞解释器退出
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
