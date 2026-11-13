"""Transaction service managing worker financial transactions and unsettled totals."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import TYPE_CHECKING

from worktime.data import (
    TransactionRepository,
    WorkerRepository,
    write_transaction,
)
from worktime.domain import (
    Transaction,
    TransactionKind,
    ValidationError,
)
from worktime.services._rules import (
    ensure_date_not_in_future,
    require_worker,
)
from worktime.services.clock import Clock, system_clock
from worktime.services.errors import RecordNotFoundError

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True, kw_only=True)
class TransactionTotals:
    """Totals of unsettled transactions grouped by kind in integer centimes."""

    advances: int
    prepayments: int
    deductions: int

    def __post_init__(self) -> None:
        if (
            isinstance(self.advances, bool)
            or not isinstance(self.advances, int)
            or self.advances < 0
        ):
            raise ValidationError("Field 'advances' must be a non-negative integer.")
        if (
            isinstance(self.prepayments, bool)
            or not isinstance(self.prepayments, int)
            or self.prepayments < 0
        ):
            raise ValidationError("Field 'prepayments' must be a non-negative integer.")
        if (
            isinstance(self.deductions, bool)
            or not isinstance(self.deductions, int)
            or self.deductions < 0
        ):
            raise ValidationError("Field 'deductions' must be a non-negative integer.")

    @property
    def total(self) -> int:
        """Return sum of all transaction totals in integer centimes."""
        return self.advances + self.prepayments + self.deductions


class TransactionService:
    """Service managing financial transactions including advances, prepayments, and deductions."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock = system_clock) -> None:
        """Initialize transaction service with database connection and injected clock."""
        self._conn = conn
        self._clock = clock
        self._workers = WorkerRepository(conn)
        self._transactions = TransactionRepository(conn)

    def add_transaction(
        self,
        worker_id: int,
        *,
        kind: TransactionKind,
        amount: int,
        occurred_on: date,
        note: str = "",
    ) -> Transaction:
        """Record and persist a new financial transaction for an active worker."""
        with write_transaction(self._conn):
            require_worker(self._workers, worker_id, allow_archived=False)
            ensure_date_not_in_future(occurred_on, self._clock())
            candidate = Transaction(
                worker_id=worker_id,
                kind=kind,
                amount=amount,
                occurred_on=occurred_on,
                note=note,
            )
            return self._transactions.add(candidate)

    def update_transaction(
        self,
        transaction_id: int,
        *,
        kind: TransactionKind,
        amount: int,
        occurred_on: date,
        note: str = "",
    ) -> Transaction:
        """Update an unlocked transaction or raise error if missing or locked."""
        with write_transaction(self._conn):
            existing = self._transactions.get(transaction_id)
            if existing is None:
                raise RecordNotFoundError("transaction not found")
            existing.ensure_editable()
            ensure_date_not_in_future(occurred_on, self._clock())
            updated = replace(
                existing,
                kind=kind,
                amount=amount,
                occurred_on=occurred_on,
                note=note,
            )
            return self._transactions.update(updated)

    def delete_transaction(self, transaction_id: int) -> None:
        """Delete an unlocked transaction by ID or raise error if missing or locked."""
        with write_transaction(self._conn):
            existing = self._transactions.get(transaction_id)
            if existing is None:
                raise RecordNotFoundError("transaction not found")
            existing.ensure_editable()
            self._transactions.delete(transaction_id)

    def get_transaction(self, transaction_id: int) -> Transaction | None:
        """Retrieve a transaction by ID, or None if not found."""
        return self._transactions.get(transaction_id)

    def list_transactions(
        self,
        worker_id: int,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        unsettled_only: bool = False,
    ) -> list[Transaction]:
        """List worker transactions filtered by optional date bounds and settlement status."""
        return self._transactions.list_for_worker(
            worker_id,
            from_date=from_date,
            to_date=to_date,
            unsettled_only=unsettled_only,
        )

    def unsettled_totals(self, worker_id: int) -> TransactionTotals:
        """Return sums of unsettled transactions per kind in centimes for a worker."""
        transactions = self._transactions.list_for_worker(worker_id, unsettled_only=True)
        advances = 0
        prepayments = 0
        deductions = 0
        for tx in transactions:
            if tx.kind == TransactionKind.ADVANCE:
                advances += tx.amount
            elif tx.kind == TransactionKind.PREPAYMENT:
                prepayments += tx.amount
            elif tx.kind == TransactionKind.DEDUCTION:
                deductions += tx.amount
        return TransactionTotals(
            advances=advances,
            prepayments=prepayments,
            deductions=deductions,
        )
