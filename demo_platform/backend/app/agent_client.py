"""Agent 对外接口客户端（只用 /api/v1/analyze/*，不依赖任何管理接口）。

演示平台把自己会话的上下文以 inline 载荷（最近消息 + 图片 URL）提交给 agent，
这正是"已有客服平台接入"的标准姿势：agent 不依赖平台的数据库。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

logger = logging.getLogger(__name__)


class AgentError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, code: str = "AGENT_ERROR") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class AgentClient:
    def __init__(self, base_url: str, api_key: str, *, timeout_s: int = 60) -> None:
        self._base_url = base_url.rstrip("/")
        headers = {"Accept": "application/json"}
        if api_key:
            headers["X-API-Key"] = api_key
        self._client = httpx.AsyncClient(base_url=self._base_url, headers=headers, timeout=timeout_s)

    async def close(self) -> None:
        await self._client.aclose()

    # ------------------------------ 基础请求 ------------------------------

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise AgentError(f"无法连接 Agent 服务（{self._base_url}）：{exc}", code="AGENT_UNREACHABLE") from exc
        if resp.status_code >= 400:
            message = f"Agent 返回 HTTP {resp.status_code}"
            code = "AGENT_ERROR"
            try:
                body = resp.json()
                err = body.get("error") or {}
                message = err.get("message") or message
                code = err.get("code") or code
            except (ValueError, AttributeError):
                pass
            raise AgentError(message, status=resp.status_code, code=code)
        if resp.headers.get("content-type", "").startswith("application/json"):
            return resp.json()
        return resp.text

    # ------------------------------ 对外接口 ------------------------------

    async def check(self, inline: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "/api/v1/analyze/check", json={"inline": inline})

    async def start_run(
        self,
        inline: dict[str, Any],
        *,
        decision_id: str | None = None,
        scenario: str | None = None,
        trigger_mode: str = "auto",
        auto_confirm: bool = True,
        idempotency_key: str | None = None,
        external_ref: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "inline": inline,
            "trigger_mode": trigger_mode,
            "auto_confirm": auto_confirm,
        }
        if decision_id:
            payload["decision_id"] = decision_id
        if scenario:
            payload["scenario"] = scenario
        if external_ref:
            payload["external_ref"] = external_ref
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return await self._request("POST", "/api/v1/analyze/runs", json=payload, headers=headers)

    async def confirm_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/v1/analyze/runs/{run_id}/confirm")

    async def get_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("GET", f"/api/v1/analyze/runs/{run_id}")

    async def get_report(self, run_id: str, fmt: str = "json") -> Any:
        return await self._request(
            "GET", f"/api/v1/analyze/runs/{run_id}/report", params={"format": fmt}
        )

    async def cancel_run(self, run_id: str) -> dict[str, Any]:
        return await self._request("POST", f"/api/v1/analyze/runs/{run_id}/cancel")

    # ------------------------------ SSE 代理 ------------------------------

    async def stream_run(
        self,
        run_id: str,
        *,
        from_seq: int = 0,
        last_event_id: str | None = None,
    ) -> AsyncIterator[bytes]:
        """把 agent 的 SSE 原样转发给浏览器（保留 id/event/data 与心跳）。"""
        headers = {"Accept": "text/event-stream"}
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        try:
            async with self._client.stream(
                "GET",
                f"/api/v1/analyze/runs/{run_id}/stream",
                params={"from_seq": from_seq},
                headers=headers,
                timeout=None,
            ) as response:
                if response.status_code >= 400:
                    body = await response.aread()
                    logger.warning("agent stream error %s: %s", response.status_code, body[:200])
                    raise AgentError(
                        f"事件流连接失败（HTTP {response.status_code}）",
                        status=response.status_code,
                    )
                async for chunk in response.aiter_raw():
                    yield chunk
        except httpx.HTTPError as exc:
            raise AgentError(f"事件流中断：{exc}", code="AGENT_STREAM_ERROR") from exc


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
