from functools import lru_cache
from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Application & Server
    PROJECT_NAME: str = "AIStoreAssistant"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "insecure-dev-secret-key-change-in-production"

    # Online Store Backend (hnbpark.com)
    STORE_BASE_URL: str = "https://hnbpark.com"
    STORE_API_KEY: str = ""
    STORE_API_SECRET: str = ""
    STORE_TIMEOUT_SECONDS: float = 5.0
    STORE_CATALOG_SYNC_INTERVAL_HOURS: int = 1

    # Meta Facebook Messenger
    META_APP_SECRET: str = ""
    META_VERIFY_TOKEN: str = "aistore_verify_token_dev"
    META_PAGE_ACCESS_TOKEN: str = ""
    META_GRAPH_API_VERSION: str = "v21.0"

    # LLM & AI Gateway
    LLM_GATEWAY_BASE_URL: str = "http://localhost:8002/api/v1"
    LLM_GATEWAY_API_KEY: str = "gw_live_dev"
    PRIMARY_LLM_MODEL: str = "llama3.1:8b"
    PRIMARY_EMBEDDING_MODEL: str = "nomic-embed-text"

    # Direct Cloud Fallback
    FALLBACK_ENABLED: bool = False
    FALLBACK_LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = ""
    FALLBACK_LLM_MODEL: str = "gpt-4o-mini"
    LLM_TIMEOUT_SECONDS: float = 10.0
    LLM_MAX_TOOL_TURNS: int = 3

    # Vector Store & RAG
    EMBEDDING_DIMENSION: int = 768
    RAG_SIMILARITY_THRESHOLD: float = 0.70
    RAG_TOP_K: int = 4

    # Database & Cache
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/aistore_db"
    POSTGRES_POOL_SIZE: int = 20
    POSTGRES_MAX_OVERFLOW: int = 10

    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # Guardrails & SLAs
    OFF_HOURS_MESSAGE: str = (
        "Our human customer care team is currently offline. "
        "We have recorded your message and will respond as soon as we open (9 AM - 6 PM)."
    )
    HANDOFF_ALERT_WEBHOOK_URL: str = ""


@lru_cache
def get_settings() -> Settings:
    """Cached singleton instance of application settings."""
    return Settings()


settings: Settings = get_settings()