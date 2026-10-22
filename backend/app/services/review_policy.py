"""人工复核资格：只对系统明确建议复核的运行开放。"""

from __future__ import annotations

from typing import Any

REVIEW_CONCLUSIONS = {"suspicious", "fake_claim"}


def requires_review(verdict: dict[str, Any] | None) -> bool:
    if not verdict:
        return False
    if verdict.get("conclusion") in REVIEW_CONCLUSIONS:
        return True
    for action in verdict.get("recommended_actions") or []:
        value = action.get("action") if isinstance(action, dict) else action
        if value == "manual_review":
            return True
    return False
