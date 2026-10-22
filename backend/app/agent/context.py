"""案件上下文组装：会话 / 内联载荷 → CaseBundle（压缩摘要 + 图片清单）。

成本原则：进入 LLM 的是压缩 transcript（每条截断 + 首尾采样），完整消息按需工具拉取。
"""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.core.errors import AppError
from app.core.files import sha256_bytes, sniff_image
from app.core.text import truncate
from app.db.repositories import attachments as attachments_repo
from app.db.repositories import messages as messages_repo

logger = logging.getLogger(__name__)

PER_MESSAGE_LIMIT = 200
RECENT_MESSAGES = 30
EARLIEST_MESSAGES = 3
MAX_INLINE_IMAGE_BYTES = 15 * 1024 * 1024


def compress_transcript(
    messages: list[dict[str, Any]],
    *,
    per_limit: int = PER_MESSAGE_LIMIT,
    recent: int = RECENT_MESSAGES,
    earliest: int = EARLIEST_MESSAGES,
) -> str:
    if not messages:
        return "（无会话消息）"
    selected = messages
    if len(messages) > recent + earliest:
        selected = messages[:earliest] + messages[-(recent):]
    lines: list[str] = []
    omitted = len(messages) - len(selected)
    for m in selected:
        speaker = {"customer": "客户", "agent": "客服"}.get(m.get("role", ""), m.get("role", ""))
        lines.append(f"[{m.get('seq', '?')}] {speaker}: {truncate(m.get('content', ''), per_limit)}")
    if omitted > 0:
        lines.insert(earliest, f"…（中间省略 {omitted} 条消息，可用 get_customer_statements 查看全文）…")
    return "\n".join(lines)


async def _store_inline_bytes(
    runtime: Any, data: bytes, *, filename_hint: str = "inline"
) -> dict[str, Any]:
    if not data:
        raise AppError("内联图片内容为空")
    if len(data) > MAX_INLINE_IMAGE_BYTES:
        raise AppError("内联图片超过大小上限 15MB")
    try:
        mime, width, height = sniff_image(data)
    except Exception as exc:
        raise AppError("内联图片不是有效图片") from exc

    sha = sha256_bytes(data)
    sub = runtime.settings.upload_dir / sha[:2]
    sub.mkdir(parents=True, exist_ok=True)
    suffix = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }.get(mime, ".img")
    path = sub / f"{sha}{suffix}"
    if not path.exists():
        path.write_bytes(data)

    existing = await attachments_repo.list_by_sha(runtime.db, sha)
    if existing:
        return _image_entry(existing[0])
    att = await attachments_repo.add(
        runtime.db,
        conversation_id=None,
        sha256=sha,
        mime=mime,
        path=str(path),
        width=width,
        height=height,
        size_bytes=len(data),
    )
    return _image_entry(att)


def _image_entry(att: dict[str, Any]) -> dict[str, Any]:
    return {
        "sha256": att["sha256"],
        "path": att["path"],
        "mime": att["mime"],
        "width": att.get("width"),
        "height": att.get("height"),
    }


async def _resolve_inline_images(runtime: Any, images: list[Any]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for image in images:
        sha = getattr(image, "sha256", None)
        b64 = getattr(image, "base64", None)
        url = getattr(image, "url", None)
        if sha:
            rows = await attachments_repo.list_by_sha(runtime.db, sha)
            if not rows:
                raise AppError(f"引用的附件不存在: {sha}")
            resolved.append(_image_entry(rows[0]))
        elif b64:
            payload = b64.split(",", 1)[-1] if b64.startswith("data:") else b64
            try:
                data = base64.b64decode(payload)
            except Exception as exc:
                raise AppError("base64 图片解码失败") from exc
            resolved.append(await _store_inline_bytes(runtime, data))
        elif url:
            try:
                async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    data = resp.content
            except Exception as exc:
                logger.warning("inline image download failed: %s", exc)
                raise AppError(f"内联图片下载失败: {url}") from exc
            resolved.append(await _store_inline_bytes(runtime, data))
        else:
            raise AppError("内联图片必须提供 sha256 / base64 / url 之一")
    return resolved


async def build_case_bundle(
    runtime: Any,
    *,
    conversation_id: str | None,
    inline: Any | None,
    rule_decision: dict[str, Any] | None = None,
    image_attachment_ids: list[str] | None = None,
) -> dict[str, Any]:
    """统一为 {conversation_id, channel, messages, digest_text, images}。

    image_attachment_ids 由触发窗口给出（最近 N 条消息内选定的图片）；
    未提供时回退为会话全部附件（兼容直接调用 /runs 的场景）。
    """
    if conversation_id:
        from app.db.repositories import conversations as conversations_repo

        conv = await conversations_repo.get(runtime.db, conversation_id)
        if conv is None:
            raise AppError(f"会话不存在: {conversation_id}")
        messages = await messages_repo.list_by_conversation(runtime.db, conversation_id)
        if image_attachment_ids is not None:
            atts = await attachments_repo.list_by_ids(runtime.db, list(image_attachment_ids))
        else:
            atts = await attachments_repo.list_by_conversation(runtime.db, conversation_id)
        return {
            "conversation_id": conversation_id,
            "channel": conv["channel"],
            "customer_name": conv.get("customer_name", ""),
            "messages": messages,
            "digest_text": compress_transcript(messages),
            "images": [_image_entry(a) for a in atts],
        }

    if inline is not None:
        messages = [
            {
                "seq": index + 1,
                "role": getattr(m, "role", "customer"),
                "content": getattr(m, "text", "") or "",
            }
            for index, m in enumerate(inline.messages or [])
        ]
        images = await _resolve_inline_images(runtime, list(inline.images or []))
        return {
            "conversation_id": None,
            "channel": inline.channel or "inline",
            "customer_name": "",
            "messages": messages,
            "digest_text": compress_transcript(messages),
            "images": images,
        }

    raise AppError("必须提供 conversation_id 或 inline 载荷")
