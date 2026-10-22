"""LLM 网关工厂：按用途构建主模型 / 识图模型，支持 fake 模式。"""

from __future__ import annotations

import logging
from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from app.config import Settings, get_settings
from app.core.errors import ConfigError
from app.llm.reasoning import ReasoningChatOpenAI

logger = logging.getLogger(__name__)


def build_chat_model(
    *,
    model: str,
    base_url: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
    timeout_s: int,
    max_retries: int,
    strip_reasoning_outbound: bool = True,
) -> BaseChatModel:
    if not base_url or not api_key:
        raise ConfigError(
            "LLM 网关未配置：请在 .env 中设置 base_url 与 api_key（或设 LLM_MODE=fake 先跑通流程）"
        )
    return ReasoningChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout_s,
        max_retries=max_retries,
        stream_usage=True,
        strip_reasoning_outbound=strip_reasoning_outbound,
    )


def build_main_llm(settings: Settings) -> BaseChatModel:
    if settings.llm_mode == "fake":
        from app.llm.fake import build_fake_main

        return build_fake_main()
    return build_chat_model(
        model=settings.llm_main_model,
        base_url=settings.llm_main_base_url,
        api_key=settings.llm_main_api_key,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_completion_tokens,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
        # 出站一律剥离 reasoning_content（DeepSeek 系契约）；LLM_REASONING_PASSTHROUGH 只影响入站捕获
        strip_reasoning_outbound=True,
    )


def build_vision_llm(settings: Settings) -> BaseChatModel:
    if settings.llm_mode == "fake":
        from app.llm.fake import build_fake_vision

        return build_fake_vision()
    if not settings.llm_vision_base_url or not settings.llm_vision_api_key:
        raise ConfigError("识图模型网关未配置：请设置 LLM_VISION_BASE_URL / LLM_VISION_API_KEY")
    return build_chat_model(
        model=settings.llm_vision_model,
        base_url=settings.llm_vision_base_url,
        api_key=settings.llm_vision_api_key,
        temperature=0,
        # 推理型模型（qwen3 等）的思考过程也计入 max_completion_tokens；
        # 识图用独立上限，避免思考耗尽预算后正文为空
        max_tokens=settings.llm_vision_max_completion_tokens,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
    )


@lru_cache(maxsize=1)
def get_main_llm() -> BaseChatModel:
    return build_main_llm(get_settings())


@lru_cache(maxsize=1)
def get_vision_llm() -> BaseChatModel:
    return build_vision_llm(get_settings())
