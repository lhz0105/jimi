from __future__ import annotations

import json
from typing import Any

import aiosqlite


def row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    # 注意：sqlite3.Row 的 `in` 检测的是值而非键，故统一用 dict(row) 转换
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows: list[aiosqlite.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def loads_json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def dumps_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
