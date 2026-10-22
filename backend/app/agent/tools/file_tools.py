"""文件读写工具：硬编码限制在运行专属工作目录（workspace/<run_id>/）内。"""

from __future__ import annotations

from typing import Any

from app.core.errors import SandboxViolation
from app.core.files import safe_join

MAX_READ_CHARS = 4000
MAX_WRITE_CHARS = 20000


def _list_workspace(runtime: Any, limit: int = 20) -> str:
    root = runtime.workspace_dir()
    files: list[str] = []
    try:
        for item in sorted(root.rglob("*")):
            if item.is_file():
                files.append(item.relative_to(root).as_posix())
                if len(files) >= limit:
                    break
    except OSError:
        return ""
    return "、".join(files)


async def read_file_impl(runtime: Any, path: str) -> str:
    try:
        target = safe_join(runtime.workspace_dir(), path)
    except SandboxViolation as exc:
        return f"读取被拒绝（沙箱限制）：{exc}"
    if not target.exists() or not target.is_file():
        existing = _list_workspace(runtime)
        return (
            f"文件不存在: {path}（工作目录初始为空，仅含本运行通过 write_file 创建的文件）。"
            f"现有文件: {existing or '（无）'}。"
            "不要假设 case_summary.md / evidence.json 等预置文件存在；如需要请先用 write_file 创建。"
        )
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + f"\n…（已截断，原文 {len(text)} 字符）"
    return text


async def write_file_impl(runtime: Any, path: str, content: str) -> str:
    if len(content) > MAX_WRITE_CHARS:
        return f"写入被拒绝：内容超过 {MAX_WRITE_CHARS} 字符上限"
    try:
        target = safe_join(runtime.workspace_dir(), path)
    except SandboxViolation as exc:
        return f"写入被拒绝（沙箱限制）：{exc}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"已写入 {path}（{len(content)} 字符）"
