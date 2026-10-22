"""中文友好的文本工具：归一化、截断、token 估算。"""

from __future__ import annotations

import re
import unicodedata

_WS_RE = re.compile(r"\s+")
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")


def normalize_text(text: str) -> str:
    """全角→半角、转小写、折叠空白。用于规则匹配与检索。"""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKC", text)
    return _WS_RE.sub(" ", normalized.lower()).strip()


def truncate(text: str, limit: int, suffix: str = "…") -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[: max(0, limit - len(suffix))] + suffix


def preview(text: str, limit: int = 300) -> str:
    return truncate(normalize_text(text), limit)


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：CJK 字符 ~0.75 token/字，其余按 ~4 字符/token。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    other = max(0, len(text) - cjk)
    return int(cjk * 0.75 + other / 4) + 1


def strip_front_matter(text: str) -> tuple[dict, str]:
    """解析 md 顶部的简单 YAML front-matter，返回 (meta, body)。"""
    import yaml

    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    body = text[end + 4 :].lstrip("\n")
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, body
