import ast
import dataclasses
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from worktime.domain.accounting import SettlementDraft, compute_wage, prepare_settlement
from worktime.domain.errors import RecordLockedError, ValidationError
from worktime.domain.session import Session
from worktime.domain.settlement import Settlement
from worktime.domain.transaction import Transaction, TransactionKind


def _make_session(
    worker_id: int = 1,
    start: datetime | None = None,
    duration_minutes: int = 60,
    *,
    is_open: bool = False,
    settlement_id: int | None = None,
) -> Session:
    start_dt = start if start is not None else datetime(2026, 11, 1, 8, 0)
    end_dt = None if is_open else start_dt + timedelta(minutes=duration_minutes)
    return Session(
        worker_id=worker_id,
        start=start_dt,
        end=end_dt,
        settlement_id=settlement_id,
    )


def _make_transaction(
    worker_id: int = 1,
    kind: TransactionKind = TransactionKind.ADVANCE,
    amount: int = 10000,
    *,
    occurred_on: date | None = None,
    settlement_id: int | None = None,
) -> Transaction:
    return Transaction(
        worker_id=worker_id,
        kind=kind,
        amount=amount,
        occurred_on=occurred_on if occurred_on is not None else date(2026, 11, 1),
        settlement_id=settlement_id,
    )


@pytest.mark.parametrize(
    ("minutes", "rate", "expected_wage"),
    [
        (0, 10000, 0),
        (60, 10000, 10000),
        (95, 10000, 15800),
        (4620, 10000, 770000),
        (6000, 5000, 500000),
        (7200, 5000, 600000),
        (1, 3000, 100),
        (1, 2999, 0),
        (1, 3001, 100),
        (2, 3000, 100),
        (3, 3000, 200),
        (1, 2970, 0),
        (100, 0, 0),
        (0, 0, 0),
    ],
)
def test_compute_wage_table(minutes: int, rate: int, expected_wage: int) -> None:
    wage = compute_wage(minutes, rate)
    assert wage == expected_wage
    assert wage % 100 == 0
    assert type(wage) is int


@pytest.mark.parametrize(
    ("minutes", "rate"),
    [
        (-1, 10000),
        (60, -1),
        (True, 10000),
        (60, True),
        (10.5, 10000),
        (60, 10.5),
        ("60", 10000),
        (60, "10000"),
    ],
)
def test_compute_wage_invalid_arguments(minutes: Any, rate: Any) -> None:
    with pytest.raises(ValidationError):
        compute_wage(minutes, rate)


def test_example_1_scenario() -> None:
    sessions = [_make_session(duration_minutes=6000)]
    transactions = [_make_transaction(kind=TransactionKind.ADVANCE, amount=700000)]
    draft = prepare_settlement(
        worker_id=1,
        sessions=sessions,
        transactions=transactions,
        previous_balance=0,
        hourly_rate=5000,
    )
    assert draft.wage == 500000
    assert draft.payable == -200000
    assert draft.max_paid == 0

    settlement = draft.finalize(paid=0, settled_on=date(2026, 11, 30))
    assert settlement.new_balance == -200000
    assert settlement.paid == 0

    with pytest.raises(ValidationError):
        draft.finalize(paid=1, settled_on=date(2026, 11, 30))


def test_example_2_scenario() -> None:
    sessions = [_make_session(duration_minutes=7200)]
    draft = prepare_settlement(
        worker_id=1,
        sessions=sessions,
        transactions=[],
        previous_balance=-200000,
        hourly_rate=5000,
    )
    assert draft.wage == 600000
    assert draft.payable == 400000
    assert draft.max_paid == 400000

    s1 = draft.finalize(paid=300000, settled_on=date(2026, 11, 30))
    assert s1.new_balance == 100000

    s2 = draft.finalize(paid=400000, settled_on=date(2026, 11, 30))
    assert s2.new_balance == 0

    s3 = draft.finalize(paid=0, settled_on=date(2026, 11, 30))
    assert s3.new_balance == 400000

    for invalid_paid in (400001, -1, True, 1.5):
        with pytest.raises(ValidationError):
            draft.finalize(paid=invalid_paid, settled_on=date(2026, 11, 30))  # type: ignore[arg-type]


def test_november_file_scenario() -> None:
    sessions = [
        _make_session(
            start=datetime(2026, 11, day + 1, 8, 0),
            duration_minutes=210,
        )
        for day in range(22)
    ]
    transactions = [
        _make_transaction(kind=TransactionKind.ADVANCE, amount=100000),
        _make_transaction(kind=TransactionKind.ADVANCE, amount=150000),
        _make_transaction(kind=TransactionKind.ADVANCE, amount=100000),
        _make_transaction(kind=TransactionKind.ADVANCE, amount=100000),
    ]
    draft = prepare_settlement(
        worker_id=1,
        sessions=sessions,
        transactions=transactions,
        previous_balance=0,
        hourly_rate=10000,
    )
    assert draft.total_minutes == 4620
    assert draft.wage == 770000
    assert draft.advances_total == 450000
    assert draft.payable == 320000


def test_all_three_transaction_kinds() -> None:
    sessions = [_make_session(duration_minutes=600)]
    transactions = [
        _make_transaction(kind=TransactionKind.ADVANCE, amount=10000),
        _make_transaction(kind=TransactionKind.PREPAYMENT, amount=20000),
        _make_transaction(kind=TransactionKind.DEDUCTION, amount=30000),
    ]
    draft = prepare_settlement(
        worker_id=1,
        sessions=sessions,
        transactions=transactions,
        previous_balance=0,
        hourly_rate=10000,
    )
    assert draft.wage == 100000
    assert draft.advances_total == 10000
    assert draft.prepayments_total == 20000
    assert draft.deductions_total == 30000
    assert draft.total_deductions == 60000
    assert draft.payable == 40000


def test_previous_balance_effect() -> None:
    sessions = [_make_session(duration_minutes=600)]
    draft_positive = prepare_settlement(
        worker_id=1,
        sessions=sessions,
        transactions=[],
        previous_balance=50000,
        hourly_rate=10000,
    )
    assert draft_positive.wage == 100000
    assert draft_positive.payable == 150000

    draft_negative = prepare_settlement(
        worker_id=1,
        sessions=sessions,
        transactions=[],
        previous_balance=-50000,
        hourly_rate=10000,
    )
    assert draft_negative.payable == 50000


def test_empty_input_and_generator_support() -> None:
    def session_gen() -> Iterator[Session]:
        if False:
            yield _make_session()

    def transaction_gen() -> Iterator[Transaction]:
        if False:
            yield _make_transaction()

    draft = prepare_settlement(
        worker_id=1,
        sessions=session_gen(),
        transactions=transaction_gen(),
        previous_balance=0,
        hourly_rate=10000,
    )
    assert draft.total_minutes == 0
    assert draft.wage == 0
    assert draft.payable == 0
    assert draft.max_paid == 0

    settlement = draft.finalize(paid=0, settled_on=date(2026, 11, 30))
    assert settlement.paid == 0
    assert settlement.new_balance == 0


def test_rejections() -> None:
    open_session = _make_session(is_open=True)
    with pytest.raises(ValidationError, match="worker has an open session"):
        prepare_settlement(
            worker_id=1,
            sessions=[open_session],
            transactions=[],
            previous_balance=0,
            hourly_rate=10000,
        )

    locked_session = _make_session(settlement_id=9)
    with pytest.raises(RecordLockedError):
        prepare_settlement(
            worker_id=1,
            sessions=[locked_session],
            transactions=[],
            previous_balance=0,
            hourly_rate=10000,
        )

    locked_tx = _make_transaction(settlement_id=9)
    with pytest.raises(RecordLockedError):
        prepare_settlement(
            worker_id=1,
            sessions=[],
            transactions=[locked_tx],
            previous_balance=0,
            hourly_rate=10000,
        )

    other_worker_session = _make_session(worker_id=2)
    with pytest.raises(ValidationError):
        prepare_settlement(
            worker_id=1,
            sessions=[other_worker_session],
            transactions=[],
            previous_balance=0,
            hourly_rate=10000,
        )

    other_worker_tx = _make_transaction(worker_id=2)
    with pytest.raises(ValidationError):
        prepare_settlement(
            worker_id=1,
            sessions=[],
            transactions=[other_worker_tx],
            previous_balance=0,
            hourly_rate=10000,
        )

    with pytest.raises(ValidationError):
        prepare_settlement(
            worker_id=0,
            sessions=[],
            transactions=[],
            previous_balance=0,
            hourly_rate=10000,
        )

    for invalid_prev in (1.5, True, "0"):
        with pytest.raises(ValidationError):
            prepare_settlement(
                worker_id=1,
                sessions=[],
                transactions=[],
                previous_balance=invalid_prev,  # type: ignore[arg-type]
                hourly_rate=10000,
            )


def test_draft_integrity() -> None:
    with pytest.raises(ValidationError):
        SettlementDraft(
            worker_id=1,
            total_minutes=60,
            wage=10000,
            advances_total=0,
            prepayments_total=0,
            deductions_total=0,
            previous_balance=0,
            payable=9999,
        )

    draft = SettlementDraft(
        worker_id=1,
        total_minutes=60,
        wage=10000,
        advances_total=1000,
        prepayments_total=2000,
        deductions_total=3000,
        previous_balance=5000,
        payable=9000,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.wage = 20000  # type: ignore[misc]

    draft_field_names = {f.name for f in dataclasses.fields(SettlementDraft)}
    assert "rate" not in draft_field_names
    assert "hourly_rate" not in draft_field_names

    settlement = draft.finalize(
        paid=5000,
        settled_on=date(2026, 11, 30),
        note="settled in cash",
    )
    assert settlement.settled_on == date(2026, 11, 30)
    assert settlement.note == "settled in cash"
    assert settlement.paid == 5000
    assert settlement.new_balance == 4000

    settlement_field_names = {f.name for f in dataclasses.fields(Settlement)}
    assert "rate" not in settlement_field_names
    assert "hourly_rate" not in settlement_field_names


def test_invariant_grid() -> None:
    previous_balances = [-50000, 0, 50000]
    minutes_options = [0, 60, 180]
    rates = [0, 5000, 10000]
    deductions = [0, 20000]

    for prev in previous_balances:
        for mins in minutes_options:
            for rate in rates:
                for ded in deductions:
                    wage = compute_wage(mins, rate)
                    payable = prev + wage - ded
                    draft = SettlementDraft(
                        worker_id=1,
                        total_minutes=mins,
                        wage=wage,
                        advances_total=ded,
                        prepayments_total=0,
                        deductions_total=0,
                        previous_balance=prev,
                        payable=payable,
                    )
                    if payable > 0:
                        paid_candidates = [0, payable // 2, payable]
                    else:
                        paid_candidates = [0]

                    for paid in paid_candidates:
                        settlement = draft.finalize(
                            paid=paid,
                            settled_on=date(2026, 11, 30),
                        )
                        if payable > 0:
                            assert paid + settlement.new_balance == payable
                        else:
                            assert settlement.new_balance == payable


def test_no_float_guard() -> None:
    source_path = Path("src/worktime/domain/accounting.py").resolve()
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(source_path))

    for node in ast.walk(tree):
        assert not isinstance(node, ast.Div), "Found ast.Div (/) in accounting.py"
        if isinstance(node, ast.Name):
            assert node.id != "float", "Found reference to 'float' in accounting.py"
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id != "round", "Found call to 'round()' in accounting.py"
        if isinstance(node, ast.Attribute):
            assert node.attr != "total_seconds", (
                "Found attribute access to 'total_seconds' in accounting.py"
            )


def test_package_exports() -> None:
    import worktime.domain

    assert "compute_wage" in worktime.domain.__all__
    assert "prepare_settlement" in worktime.domain.__all__
    assert "SettlementDraft" in worktime.domain.__all__
