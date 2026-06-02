"""Application settings — loaded from environment / .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    gemini_api_key: str = ""
    cors_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000,"
        "https://*.vercel.app"
    )
    enable_analyze_cache: bool = True
    cache_ttl_seconds: int = 3600
    hunter_task_ttl_seconds: int = 3600
    app_env: str = "development"

    # PostgreSQL (Railway / production). Leave empty for local SQLite fallback.
    database_url: str = ""

    # Local SQLite path when DATABASE_URL is unset (relative to api/ root).
    sqlite_database_path: str = "data/app.db"

    # Redis (Railway / production). Leave empty for in-memory cache fallback.
    redis_url: str = ""

    # SQLAlchemy pool tuning (PostgreSQL only)
    db_pool_size: int = 5
    db_max_overflow: int = 10


settings = Settings()
