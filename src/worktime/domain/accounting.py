"""Settlement computation and draft domain logic."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from worktime.domain._validation import require_int
from worktime.domain.durations import total_minutes
from worktime.domain.errors import RecordLockedError, ValidationError
from worktime.domain.session import Session
from worktime.domain.settlement import Settlement
from worktime.domain.transaction import Transaction, TransactionKind


def _div_round_half_up(numerator: int, denominator: int) -> int:
    return (2 * numerator + denominator) // (2 * denominator)


def compute_wage(total_minutes: int, hourly_rate: int) -> int:
    """Return wage in centimes from minutes and hourly rate, rounded to nearest dinar."""
    require_int(total_minutes, "total_minutes", minimum=0)
    require_int(hourly_rate, "hourly_rate", minimum=0)
    return _div_round_half_up(total_minutes * hourly_rate, 6000) * 100


@dataclass(frozen=True, slots=True, kw_only=True)
class SettlementDraft:
    """Settlement draft with amounts in centimes and minutes awaiting final payment."""

    worker_id: int
    total_minutes: int
    wage: int
    advances_total: int
    prepayments_total: int
    deductions_total: int
    previous_balance: int
    payable: int

    def __post_init__(self) -> None:
        require_int(self.worker_id, "worker_id", minimum=1)
        require_int(self.total_minutes, "total_minutes", minimum=0)
        require_int(self.wage, "wage", minimum=0)
        require_int(self.advances_total, "advances_total", minimum=0)
        require_int(self.prepayments_total, "prepayments_total", minimum=0)
        require_int(self.deductions_total, "deductions_total", minimum=0)
        require_int(self.previous_balance, "previous_balance")
        require_int(self.payable, "payable")

        expected_payable = self.previous_balance + self.wage - self.total_deductions
        if self.payable != expected_payable:
            raise ValidationError(
                f"Field 'payable' ({self.payable}) must equal "
                f"previous_balance ({self.previous_balance}) "
                f"+ wage ({self.wage}) - total_deductions ({self.total_deductions})."
            )

    @property
    def total_deductions(self) -> int:
        """Return total deductions in centimes from advances, prepayments, and deductions."""
        return self.advances_total + self.prepayments_total + self.deductions_total

    @property
    def max_paid(self) -> int:
        """Return max payable in centimes that can be paid, or zero if non-positive."""
        return max(self.payable, 0)

    def finalize(self, *, paid: int, settled_on: date, note: str = "") -> Settlement:
        """Finalize draft into a Settlement with paid centimes (0..max_paid) and date."""
        require_int(paid, "paid", minimum=0)
        if paid > self.max_paid:
            raise ValidationError(
                f"Field 'paid' ({paid}) cannot exceed max_paid ({self.max_paid})."
            )
        new_balance = self.payable - paid if self.payable > 0 else self.payable
        return Settlement(
            worker_id=self.worker_id,
            settled_on=settled_on,
            total_minutes=self.total_minutes,
            wage=self.wage,
            advances_total=self.advances_total,
            prepayments_total=self.prepayments_total,
            deductions_total=self.deductions_total,
            previous_balance=self.previous_balance,
            payable=self.payable,
            paid=paid,
            new_balance=new_balance,
            note=note,
        )


def prepare_settlement(
    *,
    worker_id: int,
    sessions: Iterable[Session],
    transactions: Iterable[Transaction],
    previous_balance: int,
    hourly_rate: int,
) -> SettlementDraft:
    """Prepare draft in centimes and minutes from unsettled worker records and rate."""
    session_list = list(sessions)
    tx_list = list(transactions)

    require_int(worker_id, "worker_id", minimum=1)
    require_int(previous_balance, "previous_balance")

    for session in session_list:
        if session.worker_id != worker_id:
            raise ValidationError("Session does not belong to the given worker.")
        if session.is_locked:
            raise RecordLockedError("Session is locked by a settlement and cannot be modified.")
        if session.is_open:
            raise ValidationError("worker has an open session")

    for tx in tx_list:
        if tx.worker_id != worker_id:
            raise ValidationError("Transaction does not belong to the given worker.")
        if tx.is_locked:
            raise RecordLockedError("Transaction is locked by a settlement and cannot be modified.")

    total_mins = total_minutes(session_list)

    advances_total = 0
    prepayments_total = 0
    deductions_total = 0
    for tx in tx_list:
        if tx.kind is TransactionKind.ADVANCE:
            advances_total += tx.amount
        elif tx.kind is TransactionKind.PREPAYMENT:
            prepayments_total += tx.amount
        elif tx.kind is TransactionKind.DEDUCTION:
            deductions_total += tx.amount

    wage = compute_wage(total_mins, hourly_rate)
    payable = previous_balance + wage - (advances_total + prepayments_total + deductions_total)

    return SettlementDraft(
        worker_id=worker_id,
        total_minutes=total_mins,
        wage=wage,
        advances_total=advances_total,
        prepayments_total=prepayments_total,
        deductions_total=deductions_total,
        previous_balance=previous_balance,
        payable=payable,
    )
