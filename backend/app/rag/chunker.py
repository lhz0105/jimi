"""中文友好的文档分块：标题切段 + 句末聚合 + overlap。"""

from __future__ import annotations

import re

from app.core.text import strip_front_matter

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？；!?;\n])")


def _split_sections(body: str) -> list[tuple[str, str]]:
    """返回 [(heading_path, text)]。"""
    sections: list[tuple[str, str]] = []
    positions = [(m.start(), m.group(1), m.group(2).strip()) for m in _HEADING_RE.finditer(body)]
    if not positions:
        return [("", body)]

    heading_stack: list[str] = []
    for index, (start, hashes, title) in enumerate(positions):
        level = len(hashes)
        heading_stack = heading_stack[: level - 1]
        heading_stack.append(title)
        end = positions[index + 1][0] if index + 1 < len(positions) else len(body)
        text = body[start:end]
        sections.append((" > ".join(heading_stack), text))
    return sections


def _aggregate(
    text: str, *, chunk_size: int, overlap: int
) -> list[str]:
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s and s.strip()]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) <= chunk_size:
            current += sentence
            continue
        if current:
            chunks.append(current.strip())
            tail = current[-overlap:] if overlap > 0 else ""
            current = tail + sentence
        else:
            # 单句超长：硬切
            while len(sentence) > chunk_size:
                chunks.append(sentence[:chunk_size].strip())
                sentence = sentence[chunk_size - overlap :]
            current = sentence
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if len(c) >= 20]


def chunk_document(
    raw_text: str, *, chunk_size: int = 500, overlap: int = 100
) -> tuple[dict, list[dict]]:
    """返回 (front_matter_meta, chunks)，chunk = {ordinal, text, heading_path}。"""
    meta, body = strip_front_matter(raw_text)
    chunks: list[dict] = []
    ordinal = 0
    for heading_path, section_text in _split_sections(body):
        for piece in _aggregate(section_text, chunk_size=chunk_size, overlap=overlap):
            ordinal += 1
            chunks.append({"ordinal": ordinal, "text": piece, "heading_path": heading_path})
    return meta, chunks
