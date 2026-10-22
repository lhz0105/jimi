"""工具注册：统一预算闸门 / 事件发射 / 调用持久化 / 结果截断。"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import BaseTool
from langchain_core.tools import tool as tool_decorator

from app.agent import budget as budget_mod
from app.agent.runtime import MAX_TOOL_RESULT_CHARS, RunRuntime
from app.agent.tools import (
    file_tools,
    history_tools,
    image_tools,
    rag_tool,
    tavily_tool,
    vision_tool,
)
from app.core.ids import new_id
from app.core.text import truncate
from app.db.repositories import tool_calls as tool_calls_repo
from app.observability.events import EventType

logger = logging.getLogger(__name__)


async def _guarded(
    runtime: RunRuntime,
    name: str,
    args: dict[str, Any],
    impl: Callable[[], Awaitable[str]],
) -> str:
    """工具执行统一包装：预算 → 事件 → 持久化 → 截断。"""
    reason = budget_mod.tool_allowed(runtime.budget, name)
    if reason:
        runtime.emitter.emit(
            EventType.TOOL_ERROR,
            {
                "tool": name,
                "error_code": "BUDGET_EXCEEDED",
                "message": reason,
                "retried": False,
            },
            level="warn",
        )
        return f"[工具受限] {reason}。请基于现有证据继续分析，不要再调用该工具。"

    call_id = new_id("tc")
    call_event = runtime.emitter.emit(
        EventType.TOOL_CALL,
        {
            "tool": name,
            "args_preview": truncate(json.dumps(args, ensure_ascii=False), 300),
            "call_id": call_id,
        },
    )
    started = time.perf_counter()
    status, error = "ok", None
    try:
        result = await impl()
    except Exception as exc:
        logger.exception("tool %s failed", name)
        status, error, result = "error", str(exc), f"工具执行失败：{exc}"
    latency_ms = int((time.perf_counter() - started) * 1000)
    budget_mod.record_tool(runtime.budget, name, emitter=runtime.emitter)

    try:
        await tool_calls_repo.add(
            runtime.db,
            run_id=runtime.run_id,
            seq=call_event["seq"],
            tool=name,
            args=args,
            status=status,
            result={"text": result[:4000]},
            latency_ms=latency_ms,
            cost={"tool_calls": 1},
        )
    except Exception:  # pragma: no cover
        logger.exception("tool_calls persist failed")

    if status == "ok":
        runtime.emitter.emit(
            EventType.TOOL_RESULT,
            {
                "tool": name,
                "call_id": call_id,
                "latency_ms": latency_ms,
                "status": "ok",
                "result_preview": truncate(result, 300),
            },
        )
    else:
        runtime.emitter.emit(
            EventType.TOOL_ERROR,
            {"tool": name, "call_id": call_id, "error_code": "TOOL_ERROR", "message": error, "retried": False},
            level="error",
        )
    return truncate(result, MAX_TOOL_RESULT_CHARS)


def build_tools(runtime: RunRuntime, scenario: str) -> list[BaseTool]:
    """按场景构建工具集（全部为闭包，捕获 runtime）。"""

    @tool_decorator
    async def vision_analyze(sha256: str, focus: str = "") -> str:
        """对本案指定图片运行视觉取证分析（结果有持久缓存，重复调用不再产生费用）。
        Args:
            sha256: 图片的 sha256（完整值，或图片清单中的短前缀如 3c19d88c5b70）
            focus: 可选，本次特别关注的方面（如"裂纹边缘是否自然"）
        """
        return await _guarded(
            runtime,
            "vision_analyze",
            {"sha256": sha256, "focus": focus},
            lambda: vision_tool.vision_analyze_impl(runtime, sha256, focus),
        )

    @tool_decorator
    async def lookup_kb(query: str) -> str:
        """在本地知识库（鉴别方法/欺诈案例/特征清单）中做混合检索。优先使用，零外部成本。
        Args:
            query: 检索问题或关键词
        """
        return await _guarded(
            runtime, "lookup_kb", {"query": query}, lambda: rag_tool.lookup_kb_impl(runtime, query)
        )

    @tool_decorator
    async def web_search(query: str) -> str:
        """联网搜索（Tavily）。仅在需要外部事实时使用，次数受限。
        Args:
            query: 搜索关键词
        """
        return await _guarded(
            runtime, "web_search", {"query": query}, lambda: tavily_tool.web_search_impl(runtime, query)
        )

    @tool_decorator
    async def get_customer_statements(limit: int = 12) -> str:
        """查看会话中的完整客户/客服消息记录（按时间正序）。
        Args:
            limit: 最多返回的最近消息条数
        """
        return await _guarded(
            runtime,
            "get_customer_statements",
            {"limit": limit},
            lambda: history_tools.get_customer_statements_impl(runtime, limit),
        )

    @tool_decorator
    async def find_similar_claim_images(sha256: str) -> str:
        """在历史索赔图库中查找与该图视觉相似（感知哈希）的图片，识别同图复用。
        Args:
            sha256: 待比对的图片 sha256（完整值，或图片清单中的短前缀）
        """
        return await _guarded(
            runtime,
            "find_similar_claim_images",
            {"sha256": sha256},
            lambda: image_tools.find_similar_claim_images_impl(runtime, sha256),
        )

    @tool_decorator
    async def read_file(path: str) -> str:
        """读取当前运行工作目录内的文件（沙箱限制，禁止越界路径）。
        工作目录初始为空，只包含本运行通过 write_file 创建的文件；不存在预置的案件文件。
        Args:
            path: 相对工作目录的路径
        """
        return await _guarded(
            runtime, "read_file", {"path": path}, lambda: file_tools.read_file_impl(runtime, path)
        )

    @tool_decorator
    async def write_file(path: str, content: str) -> str:
        """把中间分析结论写入当前运行工作目录内的文件（沙箱限制）。
        Args:
            path: 相对工作目录的路径
            content: 文件内容
        """
        return await _guarded(
            runtime,
            "write_file",
            {"path": path, "content": content},
            lambda: file_tools.write_file_impl(runtime, path, content),
        )

    common = [lookup_kb, get_customer_statements, read_file, write_file]
    dup_check = (
        [find_similar_claim_images]
        if runtime.settings.image_duplicate_check_enabled
        else []
    )
    if scenario == "medical_cert_claim":
        return [*common, web_search, *dup_check]
    if scenario == "seeding_post":
        return [*common, web_search]
    # product_damage_claim / generic
    return [*common, web_search, vision_analyze, *dup_check]
