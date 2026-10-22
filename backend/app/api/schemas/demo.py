"""演示客服平台接口（/api/demo）请求/响应模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ConvMode = Literal["auto", "manual", "off"]
DemoScenario = Literal["product_damage_claim", "medical_cert_claim", "seeding_post"]


class CreateConversationRequest(BaseModel):
    customer_name: str = ""
    channel: str = "demo"
    mode: ConvMode = "manual"


class PostMessageRequest(BaseModel):
    role: Literal["customer", "agent"] = "customer"
    text: str = ""
    attachment_ids: list[str] = Field(default_factory=list)


class AnalysisHint(BaseModel):
    need_analysis: bool = False
    scenario: str | None = None
    risk_hint: str | None = None
    require_confirm: bool = True
    matched_rules: list[dict] = Field(default_factory=list)
    reason: str = ""
    decision_id: str = ""
    run_id: str | None = None
    prompt_text: str = ""


class UploadResponse(BaseModel):
    attachment_id: str
    sha256: str
    mime: str
    width: int | None = None
    height: int | None = None
    bytes: int | None = None
    url: str
    deduplicated: bool = False


class SeedResponse(BaseModel):
    conversation_id: str
    scenario: str
    messages_created: int
    attachments_created: int
    hint: AnalysisHint


class TriggerAnalysisRequest(BaseModel):
    scenario: str | None = None
    trigger_mode: Literal["manual"] = "manual"
    auto_confirm: bool = True
