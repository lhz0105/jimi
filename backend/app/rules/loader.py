"""规则集加载/热重载/校验/替换。"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.errors import ConfigError
from app.rules.engine import evaluate
from app.rules.models import Decision, RuleSet
from app.rules.semantic import SemanticMatcher

logger = logging.getLogger(__name__)

DEFAULT_RULES_PATH = Path(__file__).resolve().parent / "rules.yaml"


def semantic_level(
    score: float,
    threshold: float,
    *,
    full_margin: float = 0.10,
    suspect_margin: float = 0.04,
) -> str:
    """语义命中强度（不是案件风险）：完全命中 / 疑似 / 普通。"""
    if score >= threshold + full_margin:
        return "完全命中"
    if score >= threshold + suspect_margin:
        return "疑似"
    return "普通"


class RulesService:
    def __init__(self, path: Path = DEFAULT_RULES_PATH) -> None:
        self._path = path
        self._ruleset: RuleSet | None = None
        self._mtime_ns: int = 0
        self._semantic_matcher: SemanticMatcher | None = None

    # ---- 加载与热重载 ----

    def load(self) -> RuleSet:
        text = self._read_text()
        try:
            raw = yaml.safe_load(text) or {}
            ruleset = RuleSet.model_validate(raw)
        except ValidationError as exc:
            raise ConfigError(f"规则文件校验失败: {exc}") from exc
        except yaml.YAMLError as exc:
            raise ConfigError(f"规则文件 YAML 解析失败: {exc}") from exc
        self._ruleset = ruleset
        self._mtime_ns = self._stat_mtime()
        logger.info("rules loaded: version=%s rules=%d", ruleset.version, len(ruleset.rules))
        return ruleset

    def maybe_reload(self) -> None:
        mtime = self._stat_mtime()
        if self._ruleset is None or mtime != self._mtime_ns:
            self.load()

    def _stat_mtime(self) -> int:
        try:
            return self._path.stat().st_mtime_ns
        except OSError:
            return 0

    def _read_text(self) -> str:
        try:
            return self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ConfigError(f"无法读取规则文件 {self._path}: {exc}") from exc

    # ---- 查询 ----

    @property
    def version(self) -> str:
        return self._ruleset.version if self._ruleset else "unloaded"

    @property
    def ruleset(self) -> RuleSet:
        if self._ruleset is None:
            self.load()
        assert self._ruleset is not None
        return self._ruleset

    def raw_yaml(self) -> str:
        return self._read_text()

    # ---- 语义匹配接入（由 bootstrap 注入本地向量模型，未注入则纯关键词） ----

    def set_semantic_matcher(self, matcher: SemanticMatcher | None) -> None:
        self._semantic_matcher = matcher

    @property
    def semantic_mode(self) -> str:
        if not self.ruleset.semantic.enabled:
            return "disabled"
        matcher = self._semantic_matcher
        if matcher is None:
            return "unavailable"
        return "on" if matcher.available else "unavailable"

    def _semantic_hits(self, text: str) -> tuple[dict[str, float], dict[str, str], str]:
        semantic = self.ruleset.semantic
        if not semantic.enabled:
            return {}, {}, "disabled"
        matcher = self._semantic_matcher
        if matcher is None or not matcher.available or not semantic.anchors:
            return {}, {}, "unavailable"
        try:
            raw = matcher.match(text, semantic.anchors)
        except Exception as exc:  # pragma: no cover - 语义通道失败不影响关键词判定
            logger.warning("semantic matching failed: %s", exc)
            return {}, {}, "unavailable"
        passed = {
            key: score for key, score in raw.items() if score >= semantic.threshold_for(key)
        }
        levels = {
            key: semantic_level(
                score,
                semantic.threshold_for(key),
                full_margin=semantic.level_full_margin,
                suspect_margin=semantic.level_suspect_margin,
            )
            for key, score in passed.items()
        }
        return passed, levels, "matched" if passed else "no_match"

    # ---- 评估 ----

    def decide(
        self,
        *,
        text: str,
        image_count: int = 0,
        channel: str | None = None,
        semantic_text: str | None = None,
    ) -> Decision:
        """text 供关键词/正则匹配（可含窗口摘要）；semantic_text 建议传客户原文，
        避免"客户:"等模板前缀稀释语义相似度。"""
        self.maybe_reload()
        semantic_hits, semantic_levels, semantic_status = self._semantic_hits(
            semantic_text or text
        )
        return evaluate(
            self.ruleset,
            text=text,
            image_count=image_count,
            channel=channel,
            semantic_hits=semantic_hits,
            semantic_levels=semantic_levels,
            semantic_status=semantic_status,
        )

    # ---- 替换（管理接口使用） ----

    def replace(self, yaml_text: str) -> RuleSet:
        try:
            raw = yaml.safe_load(yaml_text) or {}
            ruleset = RuleSet.model_validate(raw)
        except (ValidationError, yaml.YAMLError) as exc:
            raise ConfigError(f"规则校验失败，未替换: {exc}") from exc
        self._path.write_text(yaml_text, encoding="utf-8")
        self._ruleset = ruleset
        self._mtime_ns = self._stat_mtime()
        logger.info("rules replaced: version=%s", ruleset.version)
        return ruleset
