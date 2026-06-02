from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.hunter_tasks import create_hunter_task, get_hunter_task, task_to_status
from app.schemas.hunter import HunterScanRequest


client = TestClient(app)


def test_health_check() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "dividend-analyzer-api"


def test_root_docs_link() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "docs" in response.json()


def test_hunter_scan_returns_task_id() -> None:
    response = client.post(
        "/api/v1/hunter/scan",
        json={
            "universe": "custom",
            "tickers": ["AAPL"],
            "mode": "value",
            "minDropPercent": 15,
            "enrichScores": False,
            "enrichTags": False,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert "taskId" in body
    assert body["taskId"]


def test_hunter_task_status_not_found() -> None:
    response = client.get("/api/v1/hunter/status/nonexistent-task")
    assert response.status_code == 404


def test_create_hunter_task_record() -> None:
    request = HunterScanRequest(universe="custom", tickers=["KO"], min_drop_percent=10.0)
    task_id = create_hunter_task(request)
    record = get_hunter_task(task_id)
    assert record is not None
    status = task_to_status(record)
    assert status.task_id == task_id
    assert status.status == "pending"
