"""联网搜索工具（Tavily）。"""

from __future__ import annotations

import asyncio
from typing import Any


async def web_search_impl(runtime: Any, query: str) -> str:
    api_key = runtime.settings.tavily_api_key
    if not api_key:
        return "联网搜索不可用：未配置 TAVILY_API_KEY"
    try:
        from tavily import TavilyClient
    except ImportError:  # pragma: no cover
        return "联网搜索不可用：tavily-python 未安装"

    client = TavilyClient(api_key=api_key)

    def _search() -> dict:
        return client.search(
            query=query,
            max_results=runtime.settings.tavily_max_results,
            search_depth=runtime.settings.tavily_search_depth,
            include_answer=False,
        )

    response = await asyncio.to_thread(_search)
    results = response.get("results") or []
    if not results:
        return f"未找到与「{query}」相关的结果"
    lines = [f"「{query}」的搜索结果："]
    for item in results[: runtime.settings.tavily_max_results]:
        title = item.get("title") or ""
        url = item.get("url") or ""
        content = (item.get("content") or "")[:300]
        lines.append(f"- {title}\n  {url}\n  {content}")
    return "\n".join(lines)
