"""文件工具：缺失文件提示工作目录内容，避免模型臆测预置文件。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.tools import file_tools


@pytest.mark.asyncio
async def test_read_missing_file_lists_workspace(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "notes.md").write_text("中间结论", encoding="utf-8")
    runtime = SimpleNamespace(workspace_dir=lambda: tmp_path)
    message = await file_tools.read_file_impl(runtime, "case_summary.md")
    assert "文件不存在" in message
    assert "初始为空" in message
    assert "notes.md" in message
    assert "write_file" in message


@pytest.mark.asyncio
async def test_read_existing_file(tmp_path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "notes.md").write_text("中间结论", encoding="utf-8")
    runtime = SimpleNamespace(workspace_dir=lambda: tmp_path)
    assert await file_tools.read_file_impl(runtime, "notes.md") == "中间结论"
