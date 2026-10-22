"""对外分析接口（/api/v1/analyze）请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MessageRole = Literal["customer", "agent", "system"]


class InlineMessage(BaseModel):
    role: MessageRole = "customer"
    text: str = ""
    ts: int | None = None


class InlineImage(BaseModel):
    url: str | None = None
    base64: str | None = None
    mime: str | None = None
    sha256: str | None = Field(default=None, description="已上传附件的 sha256 引用")


class InlinePayload(BaseModel):
    messages: list[InlineMessage] = Field(default_factory=list)
    images: list[InlineImage] = Field(default_factory=list)
    channel: str | None = None


class CheckRequest(BaseModel):
    conversation_id: str | None = None
    inline: InlinePayload | None = None


class MatchedRuleOut(BaseModel):
    id: str
    priority: int
    scenario: str | None = None
    hits: list[str] = Field(default_factory=list)


class CheckResponse(BaseModel):
    need_analysis: bool
    scenario: str | None = None
    risk_hint: str | None = None
    require_confirm: bool = True
    matched_rules: list[MatchedRuleOut] = Field(default_factory=list)
    reason: str = ""
    rules_version: str = "0"
    decision_id: str = ""
    image_count: int = 0
    message: str = ""
    # 触发窗口与语义通道观测
    window_size: int = Field(default=0, description="参与判定的最近消息条数（窗口）")
    semantic_status: str = Field(
        default="disabled", description="语义通道：matched / no_match / disabled / unavailable"
    )
    semantic_hits: dict[str, float] = Field(default_factory=dict, description="通过的语义锚点及相似度")
    semantic_levels: dict[str, str] = Field(
        default_factory=dict, description="语义命中等级：完全命中 / 疑似 / 普通"
    )


class ExternalRef(BaseModel):
    """外部平台来源标识：只用于观测台展示与追溯，不参与分析。"""

    source: str | None = None
    conversation_id: str | None = None
    customer_name: str | None = None


class StartRunRequest(BaseModel):
    conversation_id: str | None = None
    inline: InlinePayload | None = None
    scenario: str | None = None
    trigger_mode: Literal["auto", "manual"] = "manual"
    auto_confirm: bool = True
    decision_id: str | None = None
    external_ref: ExternalRef | None = None
    callback_url: str | None = None


class RunStartedResponse(BaseModel):
    run_id: str
    status: str
    scenario: str
    confirm_required: bool = False
    message: str = ""


class RunStatusResponse(BaseModel):
    run_id: str
    status: str
    scenario: str
    trigger_mode: str
    progress: dict = Field(default_factory=dict)
    verdict: dict | None = None
    risk_level: str | None = None
    confidence: float | None = None
    cost: dict = Field(default_factory=dict)
    error: str | None = None
    created_at: int
    started_at: int | None = None
    finished_at: int | None = None


class EventsPage(BaseModel):
    run_id: str
    items: list[dict] = Field(default_factory=list)
    next_seq: int | None = None
