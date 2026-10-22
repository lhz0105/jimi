from __future__ import annotations

import secrets

_PREFIXES = (
    "conv",
    "msg",
    "att",
    "run",
    "dec",
    "ev",
    "rep",
    "tc",
    "doc",
    "chunk",
    "conf",
    "rev",
    "rmsg",
    "case",
    "fb",
)


def new_id(prefix: str) -> str:
    if prefix not in _PREFIXES:
        raise ValueError(f"unknown id prefix: {prefix}")
    return f"{prefix}_{secrets.token_hex(4)}"
