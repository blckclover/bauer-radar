from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.hunter import (
    HunterScanRequest,
    HunterScanTaskCreated,
    HunterTaskStatus,
)
from app.schemas.scorecard import ErrorResponse
from app.services.analyzer import AnalyzerServiceError
from app.services.hunter_tasks import (
    cancel_hunter_task,
    create_hunter_task,
    execute_hunter_task,
    get_hunter_task,
    task_to_status,
)

router = APIRouter(prefix="/hunter", tags=["hunter"])


@router.post(
    "/scan",
    response_model=HunterScanTaskCreated,
    responses={
        400: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    summary="Start Reversal Scan (async background task)",
    description=(
        "Enqueue a turnaround scan and return task_id immediately. "
        "Poll GET /hunter/status/{task_id} for progress and results."
    ),
)
def hunter_scan_start(
    body: HunterScanRequest,
    background_tasks: BackgroundTasks,
) -> HunterScanTaskCreated:
    try:
        task_id = create_hunter_task(body)
    except AnalyzerServiceError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"detail": str(exc), "code": exc.code},
        ) from exc

    background_tasks.add_task(execute_hunter_task, task_id)
    return HunterScanTaskCreated(task_id=task_id)


@router.get(
    "/status/{task_id}",
    response_model=HunterTaskStatus,
    responses={404: {"model": ErrorResponse}},
    summary="Poll Hunter Scan task status",
)
def hunter_scan_status(task_id: str) -> HunterTaskStatus:
    record = get_hunter_task(task_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": "找不到掃描任務。", "code": "task_not_found"},
        )
    return task_to_status(record)


@router.delete(
    "/status/{task_id}",
    response_model=HunterTaskStatus,
    responses={404: {"model": ErrorResponse}},
    summary="Cancel a running Hunter Scan task",
)
def hunter_scan_cancel(task_id: str) -> HunterTaskStatus:
    record = get_hunter_task(task_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"detail": "找不到掃描任務。", "code": "task_not_found"},
        )
    cancel_hunter_task(task_id)
    record = get_hunter_task(task_id)
    assert record is not None
    return task_to_status(record)
