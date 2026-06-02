from __future__ import annotations

from app.schemas.scorecard import AnalyzeResponse, QualityScore, ScorecardResult, ValuationScore
from app.services.cache import (
    MemoryCacheBackend,
    cache_get,
    cache_set,
    get_cache_backend_name,
    reset_cache_backend_for_tests,
)
from app.db.database import (
    check_database_connection,
    get_database_backend,
    normalize_database_url,
    resolve_database_url,
)


def test_sqlite_fallback_when_database_url_empty(monkeypatch) -> None:
    monkeypatch.setattr("app.db.database.settings.database_url", "")
    url, backend = resolve_database_url()
    assert backend == "sqlite"
    assert url.startswith("sqlite:///")


def test_normalize_postgres_url() -> None:
    assert normalize_database_url("postgres://u:p@host:5432/db").startswith(
        "postgresql+psycopg2://"
    )
    assert normalize_database_url("postgresql://u:p@host:5432/db").startswith(
        "postgresql+psycopg2://"
    )


def test_sqlite_database_connection(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("app.db.database.settings.database_url", "")
    monkeypatch.setattr(
        "app.db.database.settings.sqlite_database_path",
        str(tmp_path / "test.db"),
    )
    monkeypatch.setattr("app.db.database._engine", None)
    monkeypatch.setattr("app.db.database._SessionLocal", None)
    assert get_database_backend() == "sqlite"
    assert check_database_connection() is True


def test_memory_cache_roundtrip_analyze_response() -> None:
    reset_cache_backend_for_tests()
    from app.services import cache as cache_module

    cache_module._backend = MemoryCacheBackend()

    sample = AnalyzeResponse(
        scorecard=ScorecardResult(
            symbol="AAPL",
            company_name="Apple Inc.",
            strategy_mode="value",
            quality=QualityScore(value=80.0, grade="A", grade_emoji="🟢"),
            valuation=ValuationScore(value=70.0),
        ),
        red_team_findings=[],
        data_source="live",
    )

    cache_set("analyze:AAPL:value", sample, ttl_seconds=60)
    cached = cache_get("analyze:AAPL:value")
    assert isinstance(cached, AnalyzeResponse)
    assert cached.scorecard.symbol == "AAPL"
    assert get_cache_backend_name() == "memory"
