"""SQLAlchemy database engine — PostgreSQL (production) or SQLite (local dev)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

Base = declarative_base()

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _api_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sqlite_default_url() -> str:
    db_path = _api_root() / settings.sqlite_database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


def normalize_database_url(url: str) -> str:
    """Normalize Railway/Heroku postgres URLs for SQLAlchemy + psycopg2."""
    normalized = url.strip()
    if normalized.startswith("postgres://"):
        normalized = "postgresql+psycopg2://" + normalized[len("postgres://") :]
    elif normalized.startswith("postgresql://") and "+psycopg2" not in normalized:
        normalized = "postgresql+psycopg2://" + normalized[len("postgresql://") :]
    return normalized


def resolve_database_url() -> tuple[str, Literal["postgresql", "sqlite"]]:
    """Return SQLAlchemy URL and backend kind."""
    if settings.database_url.strip():
        return normalize_database_url(settings.database_url), "postgresql"
    return _sqlite_default_url(), "sqlite"


def create_database_engine() -> Engine:
    """Build SQLAlchemy engine with backend-appropriate options."""
    url, backend = resolve_database_url()

    if backend == "sqlite":
        logger.info("Database backend: SQLite (%s)", url)
        return create_engine(
            url,
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )

    logger.info("Database backend: PostgreSQL")
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
    )


def get_engine() -> Engine:
    """Lazy singleton engine."""
    global _engine
    if _engine is None:
        _engine = create_database_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Lazy singleton session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(),
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )
    return _SessionLocal


def get_db_session() -> Session:
    """Create a new ORM session (caller must close)."""
    return get_session_factory()()


def init_db() -> None:
    """Create tables from SQLAlchemy models (idempotent)."""
    Base.metadata.create_all(bind=get_engine())


def check_database_connection() -> bool:
    """Lightweight connectivity probe for health checks."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("Database connectivity check failed: %s", exc)
        return False


def get_database_backend() -> Literal["postgresql", "sqlite"]:
    _, backend = resolve_database_url()
    return backend
