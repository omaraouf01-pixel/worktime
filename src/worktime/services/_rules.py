"""Private shared validation rules for service operations."""

from datetime import date, datetime

from worktime.data import SessionRepository, WorkerRepository
from worktime.domain import (
    Session,
    ValidationError,
    Worker,
    sessions_overlap,
)
from worktime.services.errors import (
    RecordNotFoundError,
    SessionOverlapError,
    WorkerArchivedError,
    WorkerHasOpenSessionError,
)


def ensure_no_overlap(
    sessions: SessionRepository,
    candidate: Session,
    *,
    ignore_id: int | None = None,
) -> None:
    """Raise SessionOverlapError if candidate interval overlaps any other worker session."""
    worker_sessions = sessions.list_for_worker(candidate.worker_id)
    for other in worker_sessions:
        if ignore_id is not None and other.id == ignore_id:
            continue
        if sessions_overlap(candidate, other):
            raise SessionOverlapError("Session interval overlaps with an existing session.")


def ensure_not_in_future(end: datetime, now: datetime) -> None:
    """Raise ValidationError if session end datetime is strictly after current time."""
    if end > now:
        raise ValidationError("session ends in the future")


def ensure_date_not_in_future(day: date, now: datetime) -> None:
    """Raise ValidationError if date is strictly after current date."""
    if isinstance(day, datetime) or not isinstance(day, date):
        raise ValidationError("Field 'occurred_on' must be a date.")
    if day > now.date():
        raise ValidationError("date is in the future")


def require_worker(
    workers: WorkerRepository,
    worker_id: int,
    *,
    allow_archived: bool,
) -> Worker:
    """Return existing worker or raise RecordNotFoundError or WorkerArchivedError."""
    worker = workers.get(worker_id)
    if worker is None:
        raise RecordNotFoundError("worker not found")
    if not allow_archived and worker.archived:
        raise WorkerArchivedError("Worker is archived.")
    return worker


def ensure_no_open_session(sessions: SessionRepository, worker_id: int) -> None:
    """Raise WorkerHasOpenSessionError if the worker currently has an active open session."""
    if sessions.get_open(worker_id) is not None:
        raise WorkerHasOpenSessionError("Worker has an active open session.")
