"""Sightengine AI 生成检测：识图前的第三方预检（按图缓存）。

分数只表示“可能经过 AI 生成/编辑”，不指出篡改位置，不能单独认定欺诈。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import httpx

from app.db.repositories import vision_cache as vision_cache_repo
from app.llm.vision import prompt_hash
from app.observability.events import EventType

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.sightengine.com/1.0/check.json"
_CACHE_PROMPT = prompt_hash("sightengine_ai_generated", "")


def sightengine_ready(runtime: Any) -> bool:
    """真实模式且配置齐全才启用（fake 模式/单测不触网）。"""
    settings = runtime.settings
    return bool(
        settings.llm_mode == "real"
        and settings.sightengine_enabled
        and settings.sightengine_api_user
        and settings.sightengine_api_secret
    )


def _cache_model(runtime: Any) -> str:
    return f"sightengine:{runtime.settings.sightengine_model}"


def _with_thresholds(payload: dict[str, Any], settings: Any) -> dict[str, Any]:
    """阈值属于策略而非检测结果：缓存命中时也按当前配置重新标注。"""
    score = float(payload.get("score") or 0.0)
    consider = settings.sightengine_ai_threshold
    constraint = settings.sightengine_constraint_threshold
    return {
        **payload,
        "threshold": consider,
        "consider_threshold": consider,
        "constraint_threshold": constraint,
        "is_ai_generated": score >= consider,
        "is_high_confidence": score >= constraint,
    }


async def detect_ai_generated(
    runtime: Any, *, sha256: str, emit: bool = True
) -> dict[str, Any]:
    image = runtime.image_by_sha(sha256)
    if image is None:
        return {"status": "error", "message": f"图片不存在于本案: {sha256}"}
    sha256 = image["sha256"]

    model = _cache_model(runtime)
    cached = await vision_cache_repo.get(runtime.db, sha256, _CACHE_PROMPT, model)
    if cached is not None:
        if emit:
            runtime.emitter.emit(
                EventType.TOOL_CALL,
                {
                    "tool": "sightengine_detect",
                    "args_preview": f"sha256={sha256[:12]}…（缓存查询）",
                    "cache_lookup": True,
                },
            )
            runtime.emitter.emit(
                EventType.TOOL_RESULT,
                {
                    "tool": "sightengine_detect",
                    "status": "ok",
                    "latency_ms": 0,
                    "result_preview": "（缓存命中，未产生新调用）",
                    "cache_hit": True,
                },
            )
        return {
            "status": "ok",
            "cache_hit": True,
            "data": _with_thresholds(cached, runtime.settings),
        }

    if not sightengine_ready(runtime):
        return {"status": "skipped", "message": "Sightengine 未启用（或非 real 模式）"}

    settings = runtime.settings
    path = Path(image["path"])
    if emit:
        runtime.emitter.emit(
            EventType.TOOL_CALL,
            {"tool": "sightengine_detect", "args_preview": f"sha256={sha256[:12]}…"},
        )
    started = time.monotonic()
    try:
        with path.open("rb") as fh:
            async with httpx.AsyncClient(timeout=settings.sightengine_timeout_s) as client:
                response = await client.post(
                    _ENDPOINT,
                    data={
                        "models": settings.sightengine_model,
                        "api_user": settings.sightengine_api_user,
                        "api_secret": settings.sightengine_api_secret,
                    },
                    files={"media": (path.name, fh, image.get("mime") or "image/png")},
                )
        response.raise_for_status()
        body = response.json()
        if body.get("status") != "success":
            raise ValueError(str(body.get("error") or "未知错误"))
        score = float((body.get("type") or {}).get("ai_generated") or 0.0)
        payload = _with_thresholds(
            {
                "score": score,
                "request_id": (body.get("request") or {}).get("id"),
            },
            settings,
        )
        await vision_cache_repo.put(runtime.db, sha256, _CACHE_PROMPT, model, payload)
        if emit:
            if payload["is_high_confidence"]:
                verdict = "达到 AI 生成考量阈值，并触发裁决硬约束"
            elif payload["is_ai_generated"]:
                verdict = "达到 AI 生成考量阈值，未触发裁决硬约束"
            else:
                verdict = "未达到 AI 生成考量阈值"
            runtime.emitter.emit(
                EventType.TOOL_RESULT,
                {
                    "tool": "sightengine_detect",
                    "status": "ok",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "result_preview": f"AI 生成概率 {score:.2f}（{verdict}）",
                },
            )
        return {"status": "ok", "cache_hit": False, "data": payload}
    except Exception as exc:
        # 第三方失败不中断分析，只记 warning
        logger.warning("sightengine detect failed: %s", exc)
        if emit:
            runtime.emitter.emit(
                EventType.TOOL_RESULT,
                {
                    "tool": "sightengine_detect",
                    "status": "error",
                    "latency_ms": int((time.monotonic() - started) * 1000),
                    "result_preview": f"调用失败: {exc}",
                },
            )
        return {"status": "error", "message": f"Sightengine 调用失败: {exc}"}
