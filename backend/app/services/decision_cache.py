"""内存决策缓存：/check 产出的 decision_id 可被后续建 run 复用（带 TTL 与容量上限）。

规则判断本身零成本，缓存只为可追溯与接口语义完整；过期/缺失时重新判断即可。
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from app.core.ids import new_id
from app.rules.models import Decision


@dataclass
class CachedDecision:
    decision: Decision
    fingerprint: dict[str, Any]
    created_at: float


class DecisionCache:
    def __init__(self, ttl_s: int = 1800, max_size: int = 1000) -> None:
        self._ttl_s = ttl_s
        self._max_size = max_size
        self._items: OrderedDict[str, CachedDecision] = OrderedDict()

    def put(self, decision: Decision, fingerprint: dict[str, Any]) -> str:
        decision_id = new_id("dec")
        self._items[decision_id] = CachedDecision(
            decision=decision, fingerprint=fingerprint, created_at=time.time()
        )
        self._evict()
        return decision_id

    def get(self, decision_id: str) -> CachedDecision | None:
        item = self._items.get(decision_id)
        if item is None:
            return None
        if time.time() - item.created_at > self._ttl_s:
            self._items.pop(decision_id, None)
            return None
        self._items.move_to_end(decision_id)
        return item

    def _evict(self) -> None:
        now = time.time()
        expired = [k for k, v in self._items.items() if now - v.created_at > self._ttl_s]
        for k in expired:
            self._items.pop(k, None)
        while len(self._items) > self._max_size:
            self._items.popitem(last=False)
