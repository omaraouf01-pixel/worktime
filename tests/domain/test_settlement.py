from dataclasses import fields
from datetime import date

import pytest

from worktime.domain.errors import ValidationError
from worktime.domain.settlement import Settlement


def test_settlement_example_1_valid() -> None:
    settlement = Settlement(
        worker_id=1,
        settled_on=date(2026, 11, 5),
        total_minutes=6000,
        wage=500000,
        advances_total=700000,
        prepayments_total=0,
        deductions_total=0,
        previous_balance=0,
        payable=-200000,
        paid=0,
        new_balance=-200000,
        note="  Settlement 1  ",
        id=1,
    )
    assert settlement.total_deductions == 700000
    assert settlement.payable == -200000
    assert settlement.paid == 0
    assert settlement.new_balance == -200000
    assert settlement.note == "Settlement 1"


def test_settlement_example_2_valid() -> None:
    settlement = Settlement(
        worker_id=1,
        settled_on=date(2026, 11, 30),
        total_minutes=7200,
        wage=600000,
        advances_total=0,
        prepayments_total=0,
        deductions_total=0,
        previous_balance=-200000,
        payable=400000,
        paid=300000,
        new_balance=100000,
    )
    assert settlement.payable == 400000
    assert settlement.paid == 300000
    assert settlement.new_balance == 100000


def test_settlement_fully_paid_valid() -> None:
    settlement = Settlement(
        worker_id=2,
        settled_on=date(2026, 11, 5),
        total_minutes=1200,
        wage=150000,
        advances_total=50000,
        prepayments_total=0,
        deductions_total=0,
        previous_balance=0,
        payable=100000,
        paid=100000,
        new_balance=0,
    )
    assert settlement.payable == 100000
    assert settlement.paid == 100000
    assert settlement.new_balance == 0


def test_settlement_nothing_paid_with_positive_payable_valid() -> None:
    settlement = Settlement(
        worker_id=2,
        settled_on=date(2026, 11, 5),
        total_minutes=1200,
        wage=150000,
        advances_total=0,
        prepayments_total=0,
        deductions_total=0,
        previous_balance=0,
        payable=150000,
        paid=0,
        new_balance=150000,
    )
    assert settlement.payable == 150000
    assert settlement.paid == 0
    assert settlement.new_balance == 150000


def test_settlement_payable_zero_valid() -> None:
    settlement = Settlement(
        worker_id=2,
        settled_on=date(2026, 11, 5),
        total_minutes=600,
        wage=50000,
        advances_total=50000,
        prepayments_total=0,
        deductions_total=0,
        previous_balance=0,
        payable=0,
        paid=0,
        new_balance=0,
    )
    assert settlement.payable == 0
    assert settlement.paid == 0
    assert settlement.new_balance == 0


def test_settlement_wrong_payable_arithmetic_rejected() -> None:
    with pytest.raises(ValidationError):
        Settlement(
            worker_id=1,
            settled_on=date(2026, 11, 5),
            total_minutes=600,
            wage=50000,
            advances_total=10000,
            prepayments_total=0,
            deductions_total=0,
            previous_balance=0,
            payable=45000,
            paid=0,
            new_balance=45000,
        )


def test_settlement_paid_exceeds_payable_rejected() -> None:
    with pytest.raises(ValidationError):
        Settlement(
            worker_id=1,
            settled_on=date(2026, 11, 5),
            total_minutes=600,
            wage=50000,
            advances_total=0,
            prepayments_total=0,
            deductions_total=0,
            previous_balance=0,
            payable=50000,
            paid=60000,
            new_balance=-10000,
        )


@pytest.mark.parametrize("invalid_paid", [1, 500, 10000])
def test_settlement_paid_greater_than_zero_when_payable_non_positive_rejected(
    invalid_paid: int,
) -> None:
    with pytest.raises(ValidationError):
        Settlement(
            worker_id=1,
            settled_on=date(2026, 11, 5),
            total_minutes=600,
            wage=50000,
            advances_total=70000,
            prepayments_total=0,
            deductions_total=0,
            previous_balance=0,
            payable=-20000,
            paid=invalid_paid,
            new_balance=-20000 - invalid_paid,
        )


def test_settlement_wrong_new_balance_rejected() -> None:
    with pytest.raises(ValidationError):
        Settlement(
            worker_id=1,
            settled_on=date(2026, 11, 5),
            total_minutes=600,
            wage=50000,
            advances_total=0,
            prepayments_total=0,
            deductions_total=0,
            previous_balance=0,
            payable=50000,
            paid=20000,
            new_balance=25000,
        )


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("total_minutes", -1),
        ("wage", -1),
        ("advances_total", -1),
        ("prepayments_total", -1),
        ("deductions_total", -1),
        ("paid", -1),
    ],
)
def test_settlement_negative_values_rejected(field_name: str, invalid_value: int) -> None:
    data = {
        "worker_id": 1,
        "settled_on": date(2026, 11, 5),
        "total_minutes": 600,
        "wage": 50000,
        "advances_total": 0,
        "prepayments_total": 0,
        "deductions_total": 0,
        "previous_balance": 0,
        "payable": 50000,
        "paid": 0,
        "new_balance": 50000,
    }
    data[field_name] = invalid_value
    with pytest.raises(ValidationError):
        Settlement(**data)


def test_settlement_has_no_rate_field() -> None:
    field_names = {f.name for f in fields(Settlement)}
    assert "rate" not in field_names
    assert "hourly_rate" not in field_names
