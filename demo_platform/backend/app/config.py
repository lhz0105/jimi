"""演示客服平台配置（独立服务）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

_PATH_FIELDS = ("data_dir",)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    host: str = "127.0.0.1"
    port: int = 8001
    log_level: str = "INFO"

    public_base_url: str = "http://127.0.0.1:8001"
    data_dir: Path = BASE_DIR / "data"

    # 对接 Agent（仅使用对外接口 /api/v1/analyze/*）
    agent_base_url: str = "http://127.0.0.1:8000"
    agent_api_key: str = "change-me-ext"
    agent_timeout_s: int = 60

    context_window_messages: int = 8
    context_window_images: int = 5

    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174"

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        for name in _PATH_FIELDS:
            value = getattr(self, name)
            if not value.is_absolute():
                setattr(self, name, (BASE_DIR / value).resolve())
        return self

    @property
    def db_path(self) -> Path:
        return self.data_dir / "demo.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
