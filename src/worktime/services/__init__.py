"""Service layer package coordinating domain logic, persistence, and transactions."""

from worktime.services.attendance import AttendanceService, ManualEntry
from worktime.services.clock import Clock, system_clock
from worktime.services.errors import (
    DatabaseError,
    DuplicateWorkerError,
    NoOpenSessionError,
    OpenSessionExistsError,
    RecordNotFoundError,
    ServiceError,
    SessionOverlapError,
    WorkerArchivedError,
    WorkerHasOpenSessionError,
)
from worktime.services.transactions import TransactionService, TransactionTotals
from worktime.services.workers import WorkerService, WorkerSummary

__all__ = [
    "AttendanceService",
    "Clock",
    "DatabaseError",
    "DuplicateWorkerError",
    "ManualEntry",
    "NoOpenSessionError",
    "OpenSessionExistsError",
    "RecordNotFoundError",
    "ServiceError",
    "SessionOverlapError",
    "TransactionService",
    "TransactionTotals",
    "WorkerArchivedError",
    "WorkerHasOpenSessionError",
    "WorkerService",
    "WorkerSummary",
    "system_clock",
]
