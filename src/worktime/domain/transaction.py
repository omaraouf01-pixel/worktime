"""Transaction domain entity and transaction kinds."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from worktime.domain._validation import (
    require_date,
    require_int,
    require_optional_id,
    require_text,
)
from worktime.domain.errors import RecordLockedError, ValidationError


class TransactionKind(StrEnum):
    """Kind of financial transaction recorded for a worker."""

    ADVANCE = "advance"
    PREPAYMENT = "prepayment"
    DEDUCTION = "deduction"


@dataclass(frozen=True, slots=True, kw_only=True)
class Transaction:
    """Financial transaction entity in centimes."""

    worker_id: int
    kind: TransactionKind
    amount: int
    occurred_on: date
    note: str = ""
    id: int | None = None
    settlement_id: int | None = None

    def __post_init__(self) -> None:
        require_int(self.worker_id, "worker_id", minimum=1)
        if not isinstance(self.kind, TransactionKind):
            raise ValidationError("Field 'kind' must be an instance of TransactionKind.")
        require_int(self.amount, "amount", minimum=1)
        require_date(self.occurred_on, "occurred_on")
        object.__setattr__(
            self,
            "note",
            require_text(self.note, "note", max_length=500, allow_empty=True),
        )
        require_optional_id(self.id, "id")
        require_optional_id(self.settlement_id, "settlement_id")

    @property
    def is_locked(self) -> bool:
        """Return True if transaction is locked by a settlement."""
        return self.settlement_id is not None

    def ensure_editable(self) -> None:
        """Raise RecordLockedError if transaction is locked by a settlement."""
        if self.is_locked:
            raise RecordLockedError("Transaction is locked by a settlement and cannot be modified.")

    def with_settlement(self, settlement_id: int) -> Transaction:
        """Return a copy of transaction locked to the given settlement ID."""
        if self.is_locked:
            raise RecordLockedError("Transaction is already locked by a settlement.")
        require_int(settlement_id, "settlement_id", minimum=1)
        return replace(self, settlement_id=settlement_id)
