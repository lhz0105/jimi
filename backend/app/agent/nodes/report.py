"""report：组装报告 + Markdown 渲染 + 落库/落盘。零 LLM 成本。"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.report_builder import build_report, render_markdown
from app.db.repositories import reports as reports_repo
from app.observability.decorators import observed_node
from app.observability.events import EventType

logger = logging.getLogger(__name__)


@observed_node("report")
async def report(state: dict[str, Any]) -> dict[str, Any]:
    runtime = state["_runtime"]
    report_data = await build_report(state, runtime)
    markdown = render_markdown(report_data)

    saved = await reports_repo.upsert(
        runtime.db, run_id=runtime.run_id, report=report_data, markdown=markdown
    )
    try:
        report_path = runtime.settings.report_dir / f"{runtime.run_id}.md"
        report_path.write_text(markdown, encoding="utf-8")
    except OSError:  # pragma: no cover
        logger.warning("report markdown write failed", exc_info=True)

    runtime.emitter.emit(
        EventType.REPORT,
        {
            "report_id": saved["id"],
            "markdown_preview": markdown[:300],
            "evidence_count": len(report_data.get("evidence_chain") or []),
        },
        node="report",
    )
    return {"report": report_data}
