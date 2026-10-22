"""应用配置：全部来自环境变量 / .env（pydantic-settings）。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

_PATH_FIELDS = (
    "data_dir",
    "db_path",
    "upload_dir",
    "workspace_dir",
    "report_dir",
    "chroma_dir",
    "embedding_cache_dir",
    "kb_dir",
    "kb_seed_dir",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 服务 ----
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    log_json: bool = False

    data_dir: Path = BASE_DIR / "data"
    db_path: Path = BASE_DIR / "data" / "app.db"
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    workspace_dir: Path = BASE_DIR / "data" / "workspace"
    report_dir: Path = BASE_DIR / "data" / "reports"

    # ---- 鉴权 ----
    external_api_key: str = "change-me-ext"
    admin_api_key: str = "change-me-admin"

    # ---- CORS（管理台前端地址；逗号分隔，* 表示全部）----
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:4173,http://127.0.0.1:4173"
    )

    # ---- LLM 网关 ----
    llm_mode: str = "real"  # real | fake
    llm_main_base_url: str = ""
    llm_main_api_key: str = ""
    llm_main_model: str = "deepseek-v4-flash"
    llm_vision_base_url: str = ""
    llm_vision_api_key: str = ""
    llm_vision_model: str = "qwen3.7-flash"
    llm_cheap_model: str = ""
    llm_timeout_s: int = 60
    llm_max_retries: int = 2
    llm_max_completion_tokens: int = 1500
    # 识图模型单独预算：qwen 的思考过程较长，4096 仍可能耗尽后正文为空
    llm_vision_max_completion_tokens: int = 8192
    llm_temperature: float = 0.0
    llm_reasoning_passthrough: bool = True

    # ---- Tavily ----
    tavily_api_key: str = ""
    tavily_max_results: int = 4
    tavily_search_depth: str = "basic"

    # ---- RAG ----
    kb_enabled: bool = True
    embedding_model: str = "BAAI/bge-small-zh-v1.5"
    embedding_device: str = "cpu"
    embedding_cache_dir: Path = BASE_DIR / "data" / "models"
    hf_endpoint: str = "https://hf-mirror.com"
    kb_dir: Path = BASE_DIR / "data" / "kb"
    kb_seed_dir: Path = BASE_DIR / "kb_seed"
    chroma_dir: Path = BASE_DIR / "data" / "chroma"
    chunk_size: int = 500
    chunk_overlap: int = 100
    rag_candidates: int = 20
    rag_top_k: int = 4
    rag_rrf_k: int = 60
    rag_w_dense: float = 1.0
    rag_w_bm25: float = 0.8
    rag_min_dense_score: float = 0.35
    rag_query_prefix: str = "为这个句子生成表示以用于检索相关文章："

    # ---- 先前案例（人工判决沉淀，独立索引） ----
    prior_case_enabled: bool = True
    prior_case_top_k: int = 3
    prior_case_collection: str = "prior_case_chunks"

    # ---- 预算 / 成本闸门 ----
    budget_max_llm_calls: int = 12
    budget_max_tool_calls: int = 10
    budget_max_vision_calls: int = 6
    budget_max_tavily_calls: int = 3
    budget_max_prompt_tokens: int = 60000
    budget_max_run_cost: float = 1.00
    max_investigate_loops: int = 2
    # DeepSeek Flash 谷值（CNY / 1K tokens，官方 2026-09-10 价格）
    # 谷值：缓存命中输入 0.02 元/M、缓存未命中 1 元/M、输出 4 元/M
    pricing_main_input_per_1k: float = 0.001
    pricing_main_input_cache_hit_per_1k: float = 0.00002
    pricing_main_output_per_1k: float = 0.004
    pricing_vision_input_per_1k: float = 0.002
    pricing_vision_output_per_1k: float = 0.004

    # ---- 图片本地检测 ----
    phash_hamming_threshold: int = 8
    # 图片重复排查（pHash 历史图库比对 + find_similar_claim_images 工具）
    image_duplicate_check_enabled: bool = True

    # ---- 第三方 AI 生成检测（Sightengine） ----
    # 所有图片先做 AI 生成预检；高分只作线索，需识图模型定位并与诉求比对
    sightengine_enabled: bool = False
    sightengine_api_user: str = ""
    sightengine_api_secret: str = ""
    sightengine_model: str = "genai"
    # ≥ 该分数才纳入“是否为 AI 生成”的考量
    sightengine_ai_threshold: float = 0.90
    # ≥ 该分数才触发“不得判真实，至少疑似欺诈”的裁决硬约束
    sightengine_constraint_threshold: float = 0.95
    sightengine_timeout_s: int = 30

    # ---- 观测 ----
    sse_heartbeat_s: int = 15
    event_retention_days: int = 30
    event_flush_interval_ms: int = 50
    event_flush_batch: int = 20
    obs_thought_token_stream: bool = False
    sse_poll_fallback: bool = False

    # ---- 演示平台 ----
    demo_seed_on_start: bool = True
    callback_timeout_s: int = 10

    # ---- 触发判断 ----
    # 参与判定的最近消息条数（窗口）：文本与图片分开发送时，靠该窗口把二者对上
    trigger_window_messages: int = 5
    # 去重：同样的"证据指纹"在冷却期内不重复建运行；0 表示不因时间而重新触发
    trigger_dedup_enabled: bool = True
    trigger_dedup_ttl_minutes: int = 30

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _resolve_paths(self) -> Settings:
        for name in _PATH_FIELDS:
            p = getattr(self, name)
            if not p.is_absolute():
                setattr(self, name, (BASE_DIR / p).resolve())
        return self

    def ensure_dirs(self) -> None:
        for p in (
            self.data_dir,
            self.upload_dir,
            self.workspace_dir,
            self.report_dir,
            self.chroma_dir,
            self.embedding_cache_dir,
            self.kb_dir,
        ):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
