"""提示词加载器：全部提示词外置为同目录 .md，支持 {placeholder} 简单替换。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

_PROMPT_DIR = Path(__file__).resolve().parent


def load_prompt(name: str, **kwargs: object) -> str:
    raw = _read(name)
    for key, value in kwargs.items():
        raw = raw.replace("{" + key + "}", str(value))
    return raw


@lru_cache(maxsize=64)
def _read(name: str) -> str:
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"提示词不存在: {path}")
    return path.read_text(encoding="utf-8")
