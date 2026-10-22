"""识图调用封装：data URI 构造、JSON 强约束解析、容错。"""

from __future__ import annotations

import base64
import hashlib
import logging
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.llm.fake import extract_json

logger = logging.getLogger(__name__)

_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


def prompt_hash(prompt: str, extra: str = "") -> str:
    return hashlib.sha256((prompt + "\x00" + extra).encode("utf-8")).hexdigest()[:16]


def image_data_uri(path: Path) -> str:
    mime = _MIME_BY_SUFFIX.get(path.suffix.lower(), "image/png")
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def analyze_image(
    llm: BaseChatModel,
    *,
    image_path: Path,
    prompt: str,
    system: str | None = None,
) -> dict[str, Any]:
    """返回 {raw, data}；data 为解析出的 JSON（解析失败为 None）。"""
    content: list[dict[str, Any]] = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": image_data_uri(image_path)}},
    ]
    messages: list[Any] = []
    if system:
        messages.append(SystemMessage(content=system))
    messages.append(HumanMessage(content=content))

    response = await llm.ainvoke(messages)
    text = response.content if isinstance(response.content, str) else str(response.content)
    data = extract_json(text)
    if data is None:
        logger.warning("vision output is not valid json, raw length=%d", len(text))
    return {"raw": text, "data": data}
