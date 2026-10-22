"""可观测上下文：以 ContextVar 传递"当前节点"，供回调处理器标注事件归属。"""

from __future__ import annotations

import contextvars

current_node: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_node", default=None
)
