"""ReasoningChatOpenAI：兼容第三方网关的 reasoning_content 收发。

- 入站：把响应中的 reasoning_content 收进 AIMessage.additional_kwargs（观测用）
- 出站：默认从请求 payload 中剥离 reasoning_content（DeepSeek 系要求不得回传，
  剥离可避免第三方网关 400；由 settings.llm_reasoning_passthrough 关闭"剥离"）
"""

from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class ReasoningChatOpenAI(ChatOpenAI):
    """带 reasoning_content 兼容处理的 ChatOpenAI。"""

    strip_reasoning_outbound: bool = True

    def _create_chat_result(self, response: Any, generation_info: Any = None) -> Any:
        result = super()._create_chat_result(response, generation_info)
        try:
            data = response if isinstance(response, dict) else response.model_dump()
            choices = data.get("choices") or []
            for generation, choice in zip(result.generations[0], choices):
                message = choice.get("message") or {}
                reasoning = message.get("reasoning_content") or message.get("reasoning")
                if reasoning:
                    generation.message.additional_kwargs["reasoning_content"] = reasoning
        except Exception:  # pragma: no cover - 兼容性兜底，不影响主流程
            logger.debug("failed to extract reasoning_content", exc_info=True)
        return result

    def _convert_delta_to_message_chunk(self, _dict: Any, default_class: Any) -> Any:
        chunk = super()._convert_delta_to_message_chunk(_dict, default_class)
        try:
            reasoning = None
            if isinstance(_dict, dict):
                reasoning = _dict.get("reasoning_content") or _dict.get("reasoning")
            else:
                delta = getattr(_dict, "delta", None)
                if delta is not None:
                    reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                extra = dict(chunk.additional_kwargs or {})
                extra["reasoning_content"] = extra.get("reasoning_content", "") + str(reasoning)
                chunk.additional_kwargs = extra
        except Exception:  # pragma: no cover
            logger.debug("failed to attach reasoning delta", exc_info=True)
        return chunk

    def _get_request_payload(self, input_: Any, *, stop: Any = None, **kwargs: Any) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        if self.strip_reasoning_outbound:
            try:
                for message in payload.get("messages", []) or []:
                    message.pop("reasoning_content", None)
            except Exception:  # pragma: no cover
                logger.debug("failed to strip reasoning_content", exc_info=True)
        return payload
