"""规则引擎数据模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field

SCENARIOS = (
    "product_damage_claim",
    "medical_cert_claim",
    "seeding_post",
    "generic",
)


class RuleWhen(BaseModel):
    any_keywords: list[str] = Field(default_factory=list)
    all_keywords: list[str] = Field(default_factory=list)
    none_keywords: list[str] = Field(default_factory=list)
    any_regex: list[str] = Field(default_factory=list)
    # 语义命中：取 semantic.anchors 的键（如 refund_intent），由向量相似度判定
    any_semantic: list[str] = Field(default_factory=list)
    has_image: bool | None = None
    image_min: int | None = None
    channel_in: list[str] = Field(default_factory=list)


class RuleAction(BaseModel):
    need_analysis: bool = True
    require_confirm: bool = True
    risk_hint: str | None = None


class Rule(BaseModel):
    id: str
    priority: int = 0
    description: str = ""
    scenario: str | None = None
    when: RuleWhen = Field(default_factory=RuleWhen)
    action: RuleAction = Field(default_factory=RuleAction)


class Defaults(BaseModel):
    need_analysis: bool = False
    require_confirm: bool = True
    risk_hint: str | None = None


class SemanticConfig(BaseModel):
    """语义触发配置：把客户文本与锚点短语做余弦相似度（复用本地向量模型）。"""

    enabled: bool = True
    # 全局阈值 + 分组覆盖（不同锚点组的可分性不同，按标定结果微调更稳）
    threshold: float = 0.66
    thresholds: dict[str, float] = Field(default_factory=dict)
    # 命中等级：在分组阈值基础上加相对余量
    level_full_margin: float = 0.10
    level_suspect_margin: float = 0.04
    max_clauses: int = 8
    anchors: dict[str, list[str]] = Field(default_factory=dict)

    def threshold_for(self, anchor_key: str) -> float:
        return self.thresholds.get(anchor_key, self.threshold)


class RuleSet(BaseModel):
    version: str = "0"
    defaults: Defaults = Field(default_factory=Defaults)
    synonyms: dict[str, list[str]] = Field(default_factory=dict)
    semantic: SemanticConfig = Field(default_factory=SemanticConfig)
    rules: list[Rule] = Field(default_factory=list)


class MatchedRule(BaseModel):
    id: str
    priority: int
    scenario: str | None = None
    hits: list[str] = Field(default_factory=list)


class Decision(BaseModel):
    need_analysis: bool
    scenario: str | None = None
    risk_hint: str | None = None
    require_confirm: bool = True
    matched_rules: list[MatchedRule] = Field(default_factory=list)
    reason: str = ""
    rules_version: str = "0"
    # 语义匹配观测：通过的锚点及其相似度、命中等级，以及语义通道状态
    semantic_hits: dict[str, float] = Field(default_factory=dict)
    semantic_levels: dict[str, str] = Field(default_factory=dict)  # 完全命中 | 疑似 | 普通
    semantic_status: str = "disabled"  # matched | no_match | disabled | unavailable
