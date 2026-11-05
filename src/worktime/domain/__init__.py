"""Domain layer package exporting core entities and domain errors."""

from worktime.domain.accounting import (
    SettlementDraft,
    compute_wage,
    prepare_settlement,
)
from worktime.domain.durations import (
    resolve_end,
    session_minutes,
    sessions_overlap,
    total_minutes,
)
from worktime.domain.errors import DomainError, RecordLockedError, ValidationError
from worktime.domain.session import Session
from worktime.domain.settlement import Settlement
from worktime.domain.transaction import Transaction, TransactionKind
from worktime.domain.worker import Worker

__all__ = [
    "DomainError",
    "RecordLockedError",
    "Session",
    "Settlement",
    "SettlementDraft",
    "Transaction",
    "TransactionKind",
    "ValidationError",
    "Worker",
    "compute_wage",
    "prepare_settlement",
    "resolve_end",
    "session_minutes",
    "sessions_overlap",
    "total_minutes",
]
