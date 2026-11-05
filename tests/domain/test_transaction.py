from datetime import date, datetime

import pytest

from worktime.domain.errors import RecordLockedError, ValidationError
from worktime.domain.transaction import Transaction, TransactionKind


@pytest.mark.parametrize(
    "kind",
    [
        TransactionKind.ADVANCE,
        TransactionKind.PREPAYMENT,
        TransactionKind.DEDUCTION,
    ],
)
def test_transaction_each_kind_valid(kind: TransactionKind) -> None:
    tx = Transaction(
        worker_id=1,
        kind=kind,
        amount=150000,
        occurred_on=date(2026, 11, 5),
        note="  Monthly adjustment  ",
        id=5,
    )
    assert tx.worker_id == 1
    assert tx.kind == kind
    assert tx.amount == 150000
    assert tx.occurred_on == date(2026, 11, 5)
    assert tx.note == "Monthly adjustment"
    assert tx.id == 5
    assert tx.settlement_id is None
    assert tx.is_locked is False


@pytest.mark.parametrize("invalid_amount", [0, -1, -5000, 10.5, True, False, "1000", None])
def test_transaction_invalid_amount_rejected(invalid_amount: object) -> None:
    with pytest.raises(ValidationError):
        Transaction(
            worker_id=1,
            kind=TransactionKind.ADVANCE,
            amount=invalid_amount,  # type: ignore[arg-type]
            occurred_on=date(2026, 11, 5),
        )


def test_transaction_occurred_on_datetime_rejected() -> None:
    with pytest.raises(ValidationError):
        Transaction(
            worker_id=1,
            kind=TransactionKind.ADVANCE,
            amount=5000,
            occurred_on=datetime(2026, 11, 5, 10, 0),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("invalid_kind", ["advance", "prepayment", "deduction", "other", 1, None])
def test_transaction_plain_string_or_invalid_kind_rejected(invalid_kind: object) -> None:
    with pytest.raises(ValidationError):
        Transaction(
            worker_id=1,
            kind=invalid_kind,  # type: ignore[arg-type]
            amount=5000,
            occurred_on=date(2026, 11, 5),
        )


def test_transaction_locking_behavior() -> None:
    tx = Transaction(
        worker_id=1,
        kind=TransactionKind.ADVANCE,
        amount=5000,
        occurred_on=date(2026, 11, 5),
    )
    assert tx.is_locked is False
    tx.ensure_editable()

    locked_tx = tx.with_settlement(9)
    assert locked_tx.is_locked is True
    assert locked_tx.settlement_id == 9

    with pytest.raises(RecordLockedError):
        locked_tx.ensure_editable()

    with pytest.raises(RecordLockedError):
        locked_tx.with_settlement(10)
