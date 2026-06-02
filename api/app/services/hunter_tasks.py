"""In-memory Hunter Scan background tasks with polling support."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Optional

from app.schemas.hunter import HunterScanRequest, HunterScanResponse, HunterTaskStatus
from app.services.analyzer import AnalyzerServiceError
from app.services.hunter import run_hunter_scan


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class _HunterTaskRecord:
    task_id: str
    status: TaskState
    progress: int = 0
    message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request: Optional[HunterScanRequest] = None
    result: Optional[HunterScanResponse] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    cancel_requested: bool = False


_store: dict[str, _HunterTaskRecord] = {}
_lock = Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _touch(record: _HunterTaskRecord, **kwargs: object) -> None:
    for key, value in kwargs.items():
        setattr(record, key, value)
    record.updated_at = _now()


def create_hunter_task(request: HunterScanRequest) -> str:
    task_id = str(uuid.uuid4())
    record = _HunterTaskRecord(
        task_id=task_id,
        status=TaskState.PENDING,
        progress=0,
        message="任務已建立，等待執行…",
        request=request,
    )
    with _lock:
        _store[task_id] = record
    return task_id


def cancel_hunter_task(task_id: str) -> bool:
    with _lock:
        record = _store.get(task_id)
        if record is None:
            return False
        if record.status in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
            return False
        record.cancel_requested = True
        _touch(record, status=TaskState.CANCELLED, message="使用者已取消掃描。")
        return True


def get_hunter_task(task_id: str) -> Optional[_HunterTaskRecord]:
    with _lock:
        return _store.get(task_id)


def task_to_status(record: _HunterTaskRecord) -> HunterTaskStatus:
    return HunterTaskStatus(
        task_id=record.task_id,
        status=record.status.value,
        progress=record.progress,
        message=record.message,
        result=record.result,
        error=record.error,
        error_code=record.error_code,
        updated_at=record.updated_at.isoformat(),
    )


def execute_hunter_task(task_id: str) -> None:
    with _lock:
        record = _store.get(task_id)
        if record is None or record.cancel_requested:
            return
        _touch(
            record,
            status=TaskState.RUNNING,
            progress=10,
            message="解析 Universe 成分股…",
        )

    request = record.request
    if request is None:
        with _lock:
            rec = _store.get(task_id)
            if rec:
                _touch(
                    rec,
                    status=TaskState.FAILED,
                    progress=100,
                    error="任務設定遺失。",
                    error_code="invalid_task",
                    message="掃描失敗",
                )
        return

    with _lock:
        rec = _store.get(task_id)
        if rec and not rec.cancel_requested:
            _touch(rec, progress=35, message="執行逆向轉機篩選（可能需要數分鐘）…")

    try:
        result = run_hunter_scan(request)
    except AnalyzerServiceError as exc:
        with _lock:
            rec = _store.get(task_id)
            if rec and not rec.cancel_requested:
                _touch(
                    rec,
                    status=TaskState.FAILED,
                    progress=100,
                    error=str(exc),
                    error_code=exc.code,
                    message="掃描失敗",
                )
        return
    except Exception as exc:
        with _lock:
            rec = _store.get(task_id)
            if rec and not rec.cancel_requested:
                _touch(
                    rec,
                    status=TaskState.FAILED,
                    progress=100,
                    error=str(exc),
                    error_code="analyzer_error",
                    message="掃描失敗",
                )
        return

    with _lock:
        rec = _store.get(task_id)
        if rec is None:
            return
        if rec.cancel_requested:
            return
        _touch(
            rec,
            status=TaskState.COMPLETED,
            progress=100,
            message=f"完成 · 命中 {result.hit_count} 檔",
            result=result,
        )
