"""Settlement domain entity."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from worktime.domain._validation import (
    require_date,
    require_int,
    require_optional_id,
    require_text,
)
from worktime.domain.errors import ValidationError


@dataclass(frozen=True, slots=True, kw_only=True)
class Settlement:
    """Settlement record entity with amounts in centimes and time in minutes."""

    worker_id: int
    settled_on: date
    total_minutes: int
    wage: int
    advances_total: int
    prepayments_total: int
    deductions_total: int
    previous_balance: int
    payable: int
    paid: int
    new_balance: int
    note: str = ""
    id: int | None = None

    def __post_init__(self) -> None:
        require_int(self.worker_id, "worker_id", minimum=1)
        require_date(self.settled_on, "settled_on")
        require_int(self.total_minutes, "total_minutes", minimum=0)
        require_int(self.wage, "wage", minimum=0)
        require_int(self.advances_total, "advances_total", minimum=0)
        require_int(self.prepayments_total, "prepayments_total", minimum=0)
        require_int(self.deductions_total, "deductions_total", minimum=0)
        require_int(self.previous_balance, "previous_balance")
        require_int(self.payable, "payable")
        require_int(self.paid, "paid", minimum=0)
        require_int(self.new_balance, "new_balance")
        object.__setattr__(
            self,
            "note",
            require_text(self.note, "note", max_length=500, allow_empty=True),
        )
        require_optional_id(self.id, "id")

        expected_payable = self.previous_balance + self.wage - self.total_deductions
        if self.payable != expected_payable:
            raise ValidationError(
                f"Field 'payable' ({self.payable}) must equal "
                f"previous_balance ({self.previous_balance}) "
                f"+ wage ({self.wage}) - total_deductions ({self.total_deductions})."
            )

        if self.payable > 0:
            if self.paid > self.payable:
                raise ValidationError(
                    f"Field 'paid' ({self.paid}) cannot exceed positive payable ({self.payable})."
                )
            if self.new_balance != self.payable - self.paid:
                raise ValidationError(
                    f"Field 'new_balance' ({self.new_balance}) must equal "
                    f"payable ({self.payable}) - paid ({self.paid})."
                )
        else:
            if self.paid != 0:
                raise ValidationError(
                    f"Field 'paid' ({self.paid}) must be 0 when payable is non-positive."
                )
            if self.new_balance != self.payable:
                raise ValidationError(
                    f"Field 'new_balance' ({self.new_balance}) must equal payable ({self.payable}) "
                    "when payable is non-positive."
                )

    @property
    def total_deductions(self) -> int:
        """Return total deductions in centimes from advances, prepayments, and deductions."""
        return self.advances_total + self.prepayments_total + self.deductions_total
