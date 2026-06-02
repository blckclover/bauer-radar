from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import analyze, hunter, narrative

API_PREFIX = "/api/v1"


def _parse_cors_origins(raw: str) -> list[str]:
    origins: list[str] = []
    for part in raw.split(","):
        token = part.strip()
        if token:
            origins.append(token)
    # Allow all Vercel preview/production subdomains when configured with wildcard
    if any(o.startswith("https://*.vercel.app") for o in origins):
        origins = [o for o in origins if not o.startswith("https://*.")]
    return origins or ["http://localhost:3000"]


def _cors_origin_regex(origins: list[str]) -> str | None:
    if os.environ.get("CORS_ORIGINS", settings.cors_origins).find("*.vercel.app") >= 0:
        return r"https://.*\.vercel\.app"
    return None


_cors_list = _parse_cors_origins(os.environ.get("CORS_ORIGINS", settings.cors_origins))
_origin_regex = _cors_origin_regex(_parse_cors_origins(os.environ.get("CORS_ORIGINS", settings.cors_origins)))

app = FastAPI(
    title="Dividend Analyzer API",
    description="FastAPI wrapper around analyzer_core.py for Next.js frontend",
    version="0.3.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_list,
    allow_origin_regex=_origin_regex,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(analyze.router, prefix=API_PREFIX)
app.include_router(narrative.router, prefix=API_PREFIX)
app.include_router(hunter.router, prefix=API_PREFIX)


@app.get("/health")
def health_check() -> dict[str, str | bool]:
    from app.db.database import check_database_connection, get_database_backend
    from app.services.cache import get_cache_backend_name

    return {
        "status": "ok",
        "service": "dividend-analyzer-api",
        "env": settings.app_env,
        "database": get_database_backend(),
        "database_ok": check_database_connection(),
        "cache": get_cache_backend_name(),
    }


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Dividend Analyzer API",
        "docs": "/docs",
        "health": "/health",
    }
