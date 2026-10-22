"""规则匹配引擎：归一化 → 逐条求值 → 优先级短路决策。纯函数，无 IO。"""

from __future__ import annotations

import re

from app.core.text import normalize_text
from app.rules.models import Decision, MatchedRule, Rule, RuleSet, RuleWhen

_REGEX_CACHE: dict[str, re.Pattern[str]] = {}


def _compiled(pattern: str) -> re.Pattern[str]:
    if pattern not in _REGEX_CACHE:
        _REGEX_CACHE[pattern] = re.compile(pattern, re.IGNORECASE)
    return _REGEX_CACHE[pattern]


def apply_synonyms(text: str, synonyms: dict[str, list[str]]) -> str:
    """把同义词变体替换为规范词（先长后短，避免部分覆盖）。"""
    if not text or not synonyms:
        return text
    pairs: list[tuple[str, str]] = []
    for canonical, variants in synonyms.items():
        for variant in variants:
            normalized_variant = normalize_text(variant)
            if normalized_variant and normalized_variant != normalize_text(canonical):
                pairs.append((normalized_variant, normalize_text(canonical)))
    for variant, canonical in sorted(pairs, key=lambda x: -len(x[0])):
        if variant in text:
            text = text.replace(variant, canonical)
    return text


def _match_when(
    when: RuleWhen,
    text: str,
    image_count: int,
    channel: str | None,
    semantic_hits: dict[str, float] | None = None,
) -> list[str] | None:
    """全条件 AND；命中返回 hits 描述列表，未命中返回 None。

    semantic_hits 为已通过阈值的 {锚点组: 相似度}（阈值判定在 loader 完成）。
    """
    hits: list[str] = []
    semantic_hits = semantic_hits or {}

    if when.any_keywords:
        matched = [k for k in when.any_keywords if normalize_text(k) in text]
        if not matched:
            return None
        hits.append(f"any_keywords:{','.join(matched)}")

    if when.all_keywords:
        missing = [k for k in when.all_keywords if normalize_text(k) not in text]
        if missing:
            return None
        hits.append(f"all_keywords:{','.join(when.all_keywords)}")

    if when.none_keywords:
        violated = [k for k in when.none_keywords if normalize_text(k) in text]
        if violated:
            return None
        hits.append("none_keywords:ok")

    if when.any_regex:
        matched = [p for p in when.any_regex if _compiled(p).search(text)]
        if not matched:
            return None
        hits.append(f"any_regex:{','.join(matched)}")

    if when.any_semantic:
        matched = [k for k in when.any_semantic if k in semantic_hits]
        if not matched:
            return None
        detail = ",".join(f"{k}({semantic_hits[k]:.3f})" for k in matched)
        hits.append(f"any_semantic:{detail}")

    if when.has_image is not None:
        has_image = image_count > 0
        if has_image != when.has_image:
            return None
        hits.append(f"has_image:{str(when.has_image).lower()}")

    if when.image_min is not None:
        if image_count < when.image_min:
            return None
        hits.append(f"image_min:{when.image_min}")

    if when.channel_in:
        if not channel or channel not in when.channel_in:
            return None
        hits.append(f"channel_in:{channel}")

    if not hits:
        hits.append("always")
    return hits


def evaluate(
    rule_set: RuleSet,
    *,
    text: str,
    image_count: int = 0,
    channel: str | None = None,
    semantic_hits: dict[str, float] | None = None,
    semantic_levels: dict[str, str] | None = None,
    semantic_status: str = "disabled",
) -> Decision:
    normalized = apply_synonyms(normalize_text(text), rule_set.synonyms)

    matches: list[tuple[Rule, list[str]]] = []
    for rule in sorted(rule_set.rules, key=lambda r: -r.priority):
        hits = _match_when(rule.when, normalized, image_count, channel, semantic_hits)
        if hits is not None:
            matches.append((rule, hits))

    if not matches:
        d = rule_set.defaults
        return Decision(
            need_analysis=d.need_analysis,
            scenario=None,
            risk_hint=d.risk_hint,
            require_confirm=d.require_confirm,
            matched_rules=[],
            reason="未命中任何规则，采用默认策略",
            rules_version=rule_set.version,
            semantic_hits=dict(semantic_hits or {}),
            semantic_levels=dict(semantic_levels or {}),
            semantic_status=semantic_status,
        )

    top_rule, _ = matches[0]
    matched_rules = [
        MatchedRule(id=r.id, priority=r.priority, scenario=r.scenario, hits=h)
        for r, h in matches
    ]
    reason = f"命中规则 {top_rule.id}"
    if top_rule.description:
        reason += f"（{top_rule.description}）"

    return Decision(
        need_analysis=top_rule.action.need_analysis,
        scenario=top_rule.scenario if top_rule.action.need_analysis else None,
        risk_hint=top_rule.action.risk_hint,
        require_confirm=top_rule.action.require_confirm,
        matched_rules=matched_rules,
        reason=reason,
        rules_version=rule_set.version,
        semantic_hits=dict(semantic_hits or {}),
        semantic_levels=dict(semantic_levels or {}),
        semantic_status=semantic_status,
    )
