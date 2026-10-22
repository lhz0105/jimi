"""报告构建：JSON 结构 + Markdown 渲染（零额外 LLM 成本）。"""

from __future__ import annotations

import logging
from typing import Any

from jinja2 import Template

from app.agent.budget import cost_summary
from app.core.clock import now_ms
from app.core.text import truncate
from app.db.repositories import events as events_repo
from app.observability.events import EventType

logger = logging.getLogger(__name__)

_STANDARD_LIMITATIONS = [
    "EXIF 元数据可被平台/编辑工具清除或伪造，元数据缺失不构成反驳证据。",
    "视觉模型对 AIGC 痕迹的判断存在不确定性，高置信结论建议结合人工复核。",
    "知识库内容为用户提供的先例/标准，非实时数据。",
]

# trim_blocks：删除块标签（{% %}）后的换行，避免表格行之间出现空行
# （GFM 表格遇空行即终止，会被渲染成普通文本）与列表项之间多余空行。
_MARKDOWN_TEMPLATE = Template(
    """# 分析报告 {{ report.run_id }}

**场景**：{{ report.scenario }} ｜ **生成时间**：{{ report.generated_at_text }}

## 结论摘要

- **判定**：{{ report.summary.conclusion }} ｜ **风险等级**：{{ report.summary.risk_level }} ｜ **置信度**：{{ "%.2f"|format(report.summary.confidence) }}
- {{ report.summary.one_line }}

{% if report.recommended_actions %}
## 建议动作

{% for action in report.recommended_actions %}
{{ loop.index }}. **{{ action.action }}**（优先级 {{ action.priority }}）{% if action.note %} — {{ action.note }}{% endif %}

{% endfor %}
{% endif %}
## 证据链（{{ report.evidence_chain | length }} 条）

| # | 编号 | 类别 | 方向 | 权重 | 发现 |
|---|------|------|------|------|------|
{% for ev in report.evidence_chain %}
| {{ loop.index }} | {{ ev.evidence_id }} | {{ ev.category }} | {{ ev.direction }} | {{ ev.weight }} | {{ ev.finding | replace("|", "\\|") | replace("\\n", " ") }} |
{% endfor %}

{% if report.thought_timeline %}
## 思维链时间线（节选）

<details>
<summary>展开思维链时间线（{{ report.thought_timeline | length }} 条）</summary>

{% for item in report.thought_timeline %}
- [seq {{ item.seq }}] {{ item.node or "-" }}：{{ item.summary }}
{% endfor %}
</details>
{% endif %}

## 输入摘要

- 会话：{{ report.input_digest.conversation_id or "（内联载荷）" }}
- 消息数：{{ report.input_digest.message_count }} ｜ 图片：{{ report.input_digest.image_sha256s | join(", ") or "无" }}
- 规则版本：{{ report.input_digest.rules_version }}

## 成本

- LLM 调用 {{ report.cost.llm_calls }} 次（prompt {{ report.cost.prompt_tokens }} / completion {{ report.cost.completion_tokens }} tokens）
- 工具调用 {{ report.cost.tool_calls }} 次（识图 {{ report.cost.vision_calls }}，联网 {{ report.cost.tavily_calls }}）
- 估算成本：{{ report.cost.est_cost }}

## 版本与限制

- 规则 {{ report.versions.rules }} ｜ 知识库 {{ report.versions.kb }} ｜ 模型 {{ report.versions.models.main }} / {{ report.versions.models.vision }}
{% for limit in report.limitations %}
- {{ limit }}
{% endfor %}
""",
    trim_blocks=True,
)


def _timeline_summary(event: dict[str, Any]) -> str:
    payload = event.get("payload") or {}
    event_type = event["type"]
    if event_type == EventType.THOUGHT:
        return truncate(str(payload.get("text", "")), 220)
    if event_type == EventType.TOOL_CALL:
        return f"调用工具 {payload.get('tool')} {truncate(str(payload.get('args_preview', '')), 120)}"
    if event_type == EventType.TOOL_RESULT:
        return f"工具 {payload.get('tool')} 返回：{truncate(str(payload.get('result_preview', '')), 160)}"
    if event_type == EventType.RAG_HIT:
        return f"知识库命中 {len(payload.get('hits') or [])} 条"
    if event_type == EventType.NODE_START:
        return f"进入节点 {payload.get('node')}"
    return truncate(str(payload), 160)


async def build_thought_timeline(runtime: Any, limit: int = 80) -> list[dict[str, Any]]:
    wanted = {
        str(EventType.THOUGHT),
        str(EventType.TOOL_CALL),
        str(EventType.TOOL_RESULT),
        str(EventType.RAG_HIT),
        str(EventType.NODE_START),
    }
    events = await events_repo.list_after(runtime.db, runtime.run_id, since_seq=0, limit=2000)
    timeline = []
    for event in events:
        if event["type"] not in wanted:
            continue
        if event["type"] == str(EventType.NODE_START):
            continue
        timeline.append(
            {
                "seq": event["seq"],
                "ts": event["ts"],
                "node": event.get("node"),
                "summary": _timeline_summary(event),
                "ref_seq": event["seq"],
            }
        )
    return timeline[-limit:]


async def build_report(state: dict[str, Any], runtime: Any) -> dict[str, Any]:
    verdict = state.get("verdict") or runtime.verdict or {}
    case = state.get("case") or {}
    # 预算对象为运行期共享可变对象（各节点就地累加），以 runtime 为准
    budget = getattr(runtime, "budget", None) or state.get("budget") or {}
    evidence = state.get("evidence") or []
    timeline = await build_thought_timeline(runtime)

    limitations = list(_STANDARD_LIMITATIONS)
    for warning in (state.get("warnings") or [])[:3]:
        limitations.append(f"运行提示：{warning}")

    return {
        "report_id": f"rep_{runtime.run_id}",
        "run_id": runtime.run_id,
        "generated_at": now_ms(),
        "scenario": state.get("scenario"),
        "summary": {
            "conclusion": verdict.get("conclusion", "inconclusive"),
            "risk_level": verdict.get("risk_level", "medium"),
            "confidence": verdict.get("confidence", 0.0),
            "one_line": verdict.get("summary", ""),
        },
        "evidence_chain": evidence,
        "thought_timeline": timeline,
        "recommended_actions": verdict.get("recommended_actions") or [],
        "key_counterpoints": verdict.get("key_counterpoints") or [],
        "input_digest": {
            "conversation_id": case.get("conversation_id"),
            "message_count": len(case.get("messages") or []),
            "image_sha256s": [img["sha256"][:12] for img in (case.get("images") or [])],
            "rules_version": (state.get("rule_decision") or {}).get("rules_version"),
            "loop_count": state.get("loop_count", 0),
        },
        "cost": cost_summary(budget),
        "versions": {
            "rules": runtime.rules_version if hasattr(runtime, "rules_version") else "",
            "kb": getattr(runtime.kb, "kb_version", "") if runtime.kb else "",
            "prompts": "p1",
            "models": {
                "main": runtime.settings.llm_main_model,
                "vision": runtime.settings.llm_vision_model,
            },
        },
        "limitations": limitations,
    }


def render_markdown(report: dict[str, Any]) -> str:
    from datetime import datetime

    payload = dict(report)
    payload["generated_at_text"] = datetime.fromtimestamp(
        report.get("generated_at", now_ms()) / 1000
    ).strftime("%Y-%m-%d %H:%M:%S")
    return _MARKDOWN_TEMPLATE.render(report=payload)
