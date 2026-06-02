from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import analyze, narrative

API_PREFIX = "/api/v1"

_cors_origins = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app = FastAPI(
    title="Dividend Analyzer API",
    description="FastAPI wrapper around analyzer_core.py for Next.js frontend",
    version="0.2.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analyze.router, prefix=API_PREFIX)
app.include_router(narrative.router, prefix=API_PREFIX)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "service": "dividend-analyzer-api"}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "Dividend Analyzer API",
        "docs": "/docs",
        "health": "/health",
    }
