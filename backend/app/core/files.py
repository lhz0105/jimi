"""文件工具：sha256、mime 探测、沙箱路径解析。"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

from app.core.errors import SandboxViolation

_IMAGE_MIME_BY_FORMAT = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def sniff_image(data: bytes) -> tuple[str, int, int]:
    """返回 (mime, width, height)；非图片或不可解析时抛 ValueError。"""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        fmt = (img.format or "").upper()
        mime = _IMAGE_MIME_BY_FORMAT.get(fmt, "application/octet-stream")
        return mime, int(img.width), int(img.height)


def safe_join(base: Path, *parts: str) -> Path:
    """在 base 沙箱内拼接路径；越界抛 SandboxViolation。"""
    base_resolved = base.resolve()
    candidate = base_resolved
    for part in parts:
        p = Path(part)
        if p.is_absolute() or part.startswith(("/", "\\")) or ":" in part:
            raise SandboxViolation(f"绝对路径不允许: {part}")
        candidate = candidate / p
    resolved = candidate.resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise SandboxViolation(f"路径越界: {resolved}")
    return resolved
