"""Fake 模型：LLM_MODE=fake 时用于无 key 跑通全链路 / 单元测试。

行为约定（可预测、可断言的脚本化响应）：
- bind 了工具且对话中还没有工具结果 → 发起一次 lookup_kb 工具调用（走通 tool calling 路径）
- 有工具结果 / 无工具 → 按提示词中出现的输出契约返回对应 JSON
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def _text_of(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "\n".join(parts)
    return str(content)


def _all_text(messages: Sequence[BaseMessage]) -> str:
    return "\n".join(_text_of(m) for m in messages)


def _last_human_text(messages: Sequence[BaseMessage]) -> str:
    for msg in reversed(messages):
        if not isinstance(msg, ToolMessage) and msg.type == "human":
            return _text_of(msg)
    return _text_of(messages[-1]) if messages else ""


def _usage(prompt: str, output: str) -> dict[str, int]:
    input_tokens = max(10, len(prompt) // 3)
    output_tokens = max(5, len(output) // 3)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }


_EVIDENCE_ID_RE = re.compile(r"ev_\d{4}")


def _scripted_answer(prompt: str) -> str:
    """按提示词中的输出契约返回脚本化 JSON。"""
    if "new_evidence" in prompt:
        return json.dumps(
            {
                "new_evidence": [
                    {
                        "category": "rag_precedent",
                        "finding": "（fake）知识库检索命中破损索赔模式，与常见伪造索赔特征一致",
                        "direction": "supports_fake",
                        "weight": 0.45,
                        "source_detail": "工具: lookup_kb",
                    }
                ],
                "open_questions": [],
                "notes": "（fake）完成一轮调查，未发现需要追加证据的问题",
            },
            ensure_ascii=False,
        )
    if "evidence_refs" in prompt:
        ids = _EVIDENCE_ID_RE.findall(prompt)
        refs = ids[:3]
        return json.dumps(
            {
                "conclusion": "suspicious",
                "risk_level": "high",
                "confidence": 0.72,
                "summary": "（fake 模式）模拟裁决：综合证据指向疑似欺诈，建议人工复核。",
                "evidence_refs": refs,
                "key_counterpoints": ["（fake）无对立证据"],
                "recommended_actions": [
                    {"action": "manual_review", "priority": 1, "note": "转人工复核"},
                    {"action": "request_original_media", "priority": 2, "note": "要求提供原始文件"},
                ],
            },
            ensure_ascii=False,
        )
    if "contradictions" in prompt:
        return json.dumps(
            {
                "contradictions": [
                    {
                        "field": "诊断名称",
                        "customer_says": "（fake）客户声称激素相关问题",
                        "document_says": "（fake）单据诊断为过敏性皮炎",
                        "severity": "clear",
                        "finding": "（fake）客户陈述与单据诊断名称不一致",
                    }
                ],
                "consistency_score": 0.4,
                "notes": "（fake）存在一处明确不一致",
            },
            ensure_ascii=False,
        )
    if "inconsistencies" in prompt:
        return json.dumps(
            {
                "inconsistencies": [
                    {"aspect": "图文一致性", "detail": "（fake）文案与图片细节不匹配", "severity": "minor"}
                ],
                "commercial_signals": ["（fake）评论区模板化话术"],
                "consistency_score": 0.5,
                "notes": "（fake）存在轻微不一致与商业信号",
            },
            ensure_ascii=False,
        )
    return json.dumps({"findings": ["（fake）未发现明显异常"], "confidence": 0.4}, ensure_ascii=False)


class FakeChatModel(BaseChatModel):
    """可预测的假模型。"""

    tools_bound: list[Any] = []

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeChatModel:
        if tools:
            self.tools_bound = list(tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        has_tool_result = any(isinstance(m, ToolMessage) for m in messages)
        if self.tools_bound and not has_tool_result and self._should_call_tool(messages):
            tool = self._pick_tool()
            args = self._fake_args(tool.name)
            message = AIMessage(
                content="",
                tool_calls=[
                    {"name": tool.name, "args": args, "id": "call_fake_1", "type": "tool_call"}
                ],
            )
            message.usage_metadata = _usage(_all_text(messages), json.dumps(args))
            return ChatResult(generations=[ChatGeneration(message=message)])

        prompt = _all_text(messages)
        content = _scripted_answer(prompt)
        message = AIMessage(content=content)
        message.usage_metadata = _usage(prompt, content)
        return ChatResult(generations=[ChatGeneration(message=message)])

    # ---- 脚本化选择 ----

    def _should_call_tool(self, messages: list[BaseMessage]) -> bool:
        """仅调查节点会输出 new_evidence 契约；其余节点（裁决/一致性）直接产出 JSON。"""
        prompt = _all_text(messages)
        return "new_evidence" in prompt

    def _pick_tool(self) -> Any:
        for tool in self.tools_bound:
            if tool.name == "lookup_kb":
                return tool
        return self.tools_bound[0]

    def _fake_args(self, tool_name: str) -> dict[str, Any]:
        if tool_name == "lookup_kb":
            return {"query": "破损索赔 欺诈模式 判定标准"}
        if tool_name == "get_customer_statements":
            return {"limit": 10}
        if tool_name == "web_search":
            return {"query": "常见退款欺诈手法"}
        return {}


class FakeVisionModel(FakeChatModel):
    """识图假模型：返回结构化分区分析。"""

    @property
    def _llm_type(self) -> str:
        return "fake-vision-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeVisionModel:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt = _all_text(messages)
        if "医疗" in prompt or "诊断" in prompt or "单据" in prompt:
            payload = {
                "summary": "（fake）门诊病历样式文档，诊断为接触性皮炎（过敏性皮炎）。",
                "fields": {
                    "诊断": "接触性皮炎（过敏性皮炎）",
                    "科室": "皮肤科",
                    "就诊日期": "2026-09-28",
                },
                "tamper_suspected": False,
                "tamper_hints": [],
                "regions": [{"name": "正文", "aigc_suspected": False, "reason": "（fake）排版自然"}],
                "raw_confidence": 0.6,
                "caveats": [],
            }
        elif "种草" in prompt or "营销" in prompt or "随手拍" in prompt:
            payload = {
                "summary": "（fake）图片呈精修商拍风格。",
                "style": "commercial",
                "signals": ["（fake）统一摆拍构图", "（fake）版式与文案高度模板化"],
                "regions": [{"name": "主体", "aigc_suspected": False, "reason": "（fake）未见生成痕迹"}],
                "raw_confidence": 0.55,
                "caveats": [],
            }
        else:
            payload = {
                "summary": "（fake）产品主体区域疑似存在生成痕迹，人像区域经过美颜处理。",
                "regions": [
                    {"name": "产品主体", "aigc_suspected": True, "reason": "（fake）裂纹边缘与纹理异常"},
                    {"name": "人像/背景", "aigc_suspected": True, "reason": "（fake）磨皮痕迹明显"},
                ],
                "product_region_verdict": "suspected_ai",
                "irrelevant_region_aigc": True,
                "tamper_suspected": False,
                "raw_confidence": 0.55,
                "caveats": ["（fake）模拟输出，非真实判断"],
            }
        content = json.dumps(payload, ensure_ascii=False)
        message = AIMessage(content=content)
        message.usage_metadata = _usage(prompt + "x" * 2000, content)
        return ChatResult(generations=[ChatGeneration(message=message)])


def build_fake_main() -> FakeChatModel:
    return FakeChatModel()


def build_fake_vision() -> FakeVisionModel:
    return FakeVisionModel()


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str) -> dict | None:
    """从模型输出中稳健提取 JSON 对象。"""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    match = _JSON_RE.search(cleaned)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None
