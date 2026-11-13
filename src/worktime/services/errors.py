"""Service layer error definitions and re-exported data errors."""

from worktime.data.errors import (
    DatabaseError,
    DuplicateWorkerError,
    OpenSessionExistsError,
    RecordNotFoundError,
)


class ServiceError(Exception):
    """Base exception for all service layer business rule violations."""


class NoOpenSessionError(ServiceError):
    """Raised when an operation requires an open session but none exists."""


class SessionOverlapError(ServiceError):
    """Raised when a session interval overlaps with another session of the worker."""


class WorkerArchivedError(ServiceError):
    """Raised when an active operation is attempted on an archived worker."""


class WorkerHasOpenSessionError(ServiceError):
    """Raised when attempting to archive a worker who currently has an open session."""


__all__ = [
    "DatabaseError",
    "DuplicateWorkerError",
    "NoOpenSessionError",
    "OpenSessionExistsError",
    "RecordNotFoundError",
    "ServiceError",
    "SessionOverlapError",
    "WorkerArchivedError",
    "WorkerHasOpenSessionError",
]
