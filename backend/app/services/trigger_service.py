"""触发去重：证据指纹 + 活跃运行守卫。

持续消息 + 滑动窗口会让同一诉求被反复判定（客户补一张图、再发一句"在吗"都可能再次命中）。
这里做两层防护：

1) **证据指纹（signature）**：= 命中规则（去掉相似度分数）+ 窗口内图片 sha256 集合 + 场景。
   - 指纹相同且窗口内没有新增客户消息 → 永不重复分析（客服续聊、客户寒暄不触发）；
   - 指纹相同但客户又发了消息 → 冷却期（`TRIGGER_DEDUP_TTL_MINUTES`）内仍不重复，
     超过冷却期才允许"同一诉求再次分析"；
   - 图片集合变化（补图/换图）或命中证据变化（新增关键词/语义锚点）→ 指纹变化 → 新分析。
2) **活跃运行守卫**：同会话已有 queued / awaiting_confirm / running 的运行 → 直接复用该运行，
   不并发新建（手动触发同样如此）。上一次运行失败时允许重试。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from app.core.clock import now_ms
from app.db.repositories import runs as runs_repo
from app.db.repositories import trigger_state as trigger_state_repo
from app.deps import AppState
from app.rules.models import Decision
from app.services.case_window import CaseWindow

logger = logging.getLogger(__name__)

_SCORE_RE = re.compile(r"\([\d.]+\)")  # 去掉 any_semantic:refund_intent(0.907) 中的分数

TriggerAction = Literal["start", "reuse", "skip"]


@dataclass
class TriggerOutcome:
    action: TriggerAction
    reason: str
    signature: str
    run: dict[str, Any] | None = None

    @property
    def run_id(self) -> str | None:
        return self.run["id"] if self.run else None

    def to_hint(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "signature": self.signature,
            "run_id": self.run_id,
        }


_locks: dict[str, asyncio.Lock] = {}


def _lock_for(conversation_id: str) -> asyncio.Lock:
    lock = _locks.get(conversation_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[conversation_id] = lock
    return lock


def compute_signature(decision: Decision, window: CaseWindow) -> str:
    """证据指纹：规则 + 命中细节（去分数）+ 图片 sha 集合 + 场景。"""
    rules = []
    for matched in decision.matched_rules:
        rules.append(
            {
                "rule": matched.id,
                "hits": sorted(_SCORE_RE.sub("", h) for h in matched.hits),
            }
        )
    payload = {
        "scenario": decision.scenario,
        "need_analysis": decision.need_analysis,
        "rules": sorted(rules, key=lambda item: item["rule"]),
        "images": sorted(a["sha256"] for a in window.attachments),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return digest[:16]


async def guard_and_start(
    state: AppState,
    *,
    conversation_id: str,
    decision: Decision,
    window: CaseWindow,
    trigger_mode: str,
    auto_confirm: bool,
    force: bool = False,
    input_snapshot: dict[str, Any] | None = None,
    inline: Any = None,
    external_ref: dict[str, Any] | None = None,
    idempotency_key: str | None = None,
    callback_url: str | None = None,
) -> TriggerOutcome:
    """去重后决定：新建运行 / 复用现有运行 / 跳过。"""
    runner = state.runner
    signature = compute_signature(decision, window)

    if runner is None or not decision.need_analysis or not decision.scenario:
        return TriggerOutcome("skip", "not_required", signature)

    db = state.db
    async with _lock_for(conversation_id):
        # ① 活跃运行守卫：同会话不并发（手动触发也不并发）
        active = await runs_repo.get_active_for_conversation(db, conversation_id)
        if active is not None:
            logger.info(
                "trigger reuse: conversation=%s active_run=%s status=%s",
                conversation_id,
                active["id"],
                active["status"],
            )
            return TriggerOutcome("reuse", "active_run", signature, active)

        # ② 证据指纹去重（自动链）
        if not force:
            prev = await trigger_state_repo.get(db, conversation_id)
            if prev is not None and prev["last_signature"] == signature:
                prev_run = (
                    await runs_repo.get(db, prev["last_run_id"])
                    if prev.get("last_run_id")
                    else None
                )
                if prev_run is None or prev_run["status"] != "failed":
                    if not window.has_new_customer_since(prev.get("last_message_seq", 0)):
                        logger.info("trigger skip: conversation=%s reason=no_new_content", conversation_id)
                        return TriggerOutcome("skip", "no_new_content", signature, prev_run)

                    ttl_ms = state.settings.trigger_dedup_ttl_minutes * 60_000
                    elapsed = now_ms() - int(prev.get("last_triggered_at") or 0)
                    if (
                        not state.settings.trigger_dedup_enabled
                        or ttl_ms <= 0
                        or elapsed < ttl_ms
                    ):
                        logger.info(
                            "trigger skip: conversation=%s reason=same_signature elapsed=%ss",
                            conversation_id,
                            elapsed // 1000,
                        )
                        return TriggerOutcome("skip", "same_signature", signature, prev_run)

        # ③ 新建运行并记录指纹水位
        run = await runner.start_run(
            conversation_id=conversation_id,
            scenario=decision.scenario,
            trigger_mode=trigger_mode,
            auto_confirm=auto_confirm,
            inline=inline,
            rules_decision=decision.model_dump(),
            input_snapshot=input_snapshot or {},
            external_ref=external_ref,
            idempotency_key=idempotency_key,
            callback_url=callback_url,
        )
        await trigger_state_repo.upsert(
            db,
            conversation_id=conversation_id,
            run_id=run["id"],
            signature=signature,
            last_message_seq=window.newest_customer_seq or 0,
        )
        return TriggerOutcome("start", "started", signature, run)
