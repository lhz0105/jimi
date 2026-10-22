"""触发窗口：最近 N 条消息的文本 + 该窗口内的图片。

客服对话中图片与文字往往分开发送，因此触发判断以"窗口"为单位：
- 文本先到：先在窗口文本上判定意图（关键词 + 语义），再在窗口内取图作为证据；
- 图片先到：图片本身不含文本意图，回看窗口内最近 N 条文本是否表达退款等诉求；
- 二者都在同一窗口内即视为"同一诉求的连贯表达"，可触发分析。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.text import truncate
from app.db.database import Database
from app.db.repositories import attachments as attachments_repo
from app.db.repositories import messages as messages_repo

logger = logging.getLogger(__name__)

SPEAKER_LABEL = {"customer": "客户", "agent": "客服", "system": "系统"}


@dataclass
class CaseWindow:
    conversation_id: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    text: str = ""
    attachments: list[dict[str, Any]] = field(default_factory=list)

    @property
    def image_count(self) -> int:
        return len(self.attachments)

    @property
    def attachment_ids(self) -> list[str]:
        return [a["id"] for a in self.attachments]

    @property
    def oldest_seq(self) -> int | None:
        return self.messages[0]["seq"] if self.messages else None

    @property
    def newest_seq(self) -> int | None:
        return self.messages[-1]["seq"] if self.messages else None

    @property
    def newest_customer_seq(self) -> int | None:
        """窗口内最新一条客户消息的 seq（客服消息不推进水位，避免续聊重复触发）。"""
        seqs = [m["seq"] for m in self.messages if m.get("role") == "customer"]
        return seqs[-1] if seqs else None

    def has_new_customer_since(self, last_seq: int | None) -> bool:
        newest = self.newest_customer_seq
        return newest is not None and newest > int(last_seq or 0)

    def digest(self) -> str:
        """窗口文本（每条截断），用于关键词判定与摘要。"""
        lines = []
        for m in self.messages:
            speaker = SPEAKER_LABEL.get(m.get("role", ""), m.get("role", ""))
            lines.append(f"[{m.get('seq', '?')}] {speaker}: {truncate(m.get('content', ''), 200)}")
        return "\n".join(lines) or "（窗口内无消息）"

    @property
    def customer_text(self) -> str:
        """客户原文（无说话人/序号前缀）——语义匹配用，避免模板字符稀释相似度。"""
        return "\n".join(
            (m.get("content") or "") for m in self.messages if m.get("role") == "customer"
        ).strip()

    def snapshot_fields(self) -> dict[str, Any]:
        """写入运行 input_snapshot 的窗口信息（供 prepare_case 取同一批图片）。"""
        return {
            "window_size": len(self.messages),
            "window_oldest_seq": self.oldest_seq,
            "window_newest_seq": self.newest_seq,
            "image_attachment_ids": self.attachment_ids,
        }


async def load_window(db: Database, conversation_id: str, *, window: int = 5) -> CaseWindow:
    """取最近 window 条消息 + 这些消息绑定的图片（含窗口期内未绑定消息的新上传图）。"""
    messages = await messages_repo.list_by_conversation(db, conversation_id, limit=max(1, window))
    if not messages:
        return CaseWindow(conversation_id=conversation_id)

    since_ts = messages[0]["created_at"]
    attachments = await attachments_repo.list_window(
        db,
        conversation_id,
        message_ids=[m["id"] for m in messages],
        since_ts=since_ts,
    )
    case_window = CaseWindow(
        conversation_id=conversation_id, messages=messages, attachments=attachments
    )
    case_window.text = case_window.digest()
    return case_window
