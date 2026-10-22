"""结构化证据链：唯一定义处。每条证据 = 来源 + 工具 + 发现 + 方向 + 权重。"""

from __future__ import annotations

from typing import Any

from app.observability.events import EventType

EVIDENCE_CATEGORIES = (
    "aigc_artifact",           # 图像生成痕迹
    "image_manipulation",      # 图像篡改/拼接
    "metadata",                # EXIF/元数据
    "duplicate_image",         # 复用/重复图
    "document_field",          # 单据字段抽取
    "statement_contradiction", # 陈述矛盾
    "rag_precedent",           # 知识库先例
    "web_fact",                # 联网事实
    "marketing_pattern",       # 营销话术模式
    "customer_behavior",       # 客户行为特征
)

DIRECTIONS = ("supports_fake", "supports_genuine", "neutral", "unknown")


def make_evidence(
    *,
    evidence_id: str,
    category: str,
    source: dict[str, Any],
    tool: str,
    finding: str,
    direction: str = "unknown",
    weight: float = 0.5,
    raw_ref: dict[str, Any] | None = None,
    notes: str = "",
) -> dict[str, Any]:
    if category not in EVIDENCE_CATEGORIES:
        category = "customer_behavior"
    if direction not in DIRECTIONS:
        direction = "unknown"
    return {
        "evidence_id": evidence_id,
        "category": category,
        "source": source,
        "tool": tool,
        "finding": finding,
        "direction": direction,
        "weight": round(max(0.0, min(1.0, weight)), 2),
        "raw_ref": raw_ref or {},
        "notes": notes,
    }


class EvidenceBuilder:
    """在节点内收集证据：自动编号 + 即时发射 evidence 事件。"""

    def __init__(self, state: dict[str, Any]) -> None:
        self._emitter = state.get("_emitter")
        self._counter = len(state.get("evidence") or [])

    @property
    def next_id(self) -> str:
        return f"ev_{self._counter + 1:04d}"

    def add(
        self,
        *,
        category: str,
        source: dict[str, Any],
        tool: str,
        finding: str,
        direction: str = "unknown",
        weight: float = 0.5,
        raw_ref: dict[str, Any] | None = None,
        notes: str = "",
    ) -> dict[str, Any]:
        self._counter += 1
        item = make_evidence(
            evidence_id=f"ev_{self._counter:04d}",
            category=category,
            source=source,
            tool=tool,
            finding=finding,
            direction=direction,
            weight=weight,
            raw_ref=raw_ref,
            notes=notes,
        )
        if self._emitter is not None:
            self._emitter.emit(EventType.EVIDENCE, {"evidence": item})
        return item
