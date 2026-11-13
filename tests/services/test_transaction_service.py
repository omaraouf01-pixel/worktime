"""Unit tests for TransactionService and TransactionTotals."""

import sqlite3
from collections.abc import Callable
from datetime import date, datetime

import pytest

from tests.services.conftest import FakeClock
from worktime.data import (
    DatabaseError,
    RecordNotFoundError,
    SettlementRepository,
    TransactionRepository,
    write_transaction,
)
from worktime.domain import (
    RecordLockedError,
    Settlement,
    Transaction,
    TransactionKind,
    ValidationError,
    Worker,
    prepare_settlement,
)
from worktime.services import (
    AttendanceService,
    TransactionService,
    TransactionTotals,
    WorkerArchivedError,
    WorkerService,
)


@pytest.fixture
def service(conn: sqlite3.Connection, clock: FakeClock) -> TransactionService:
    return TransactionService(conn, clock=clock)


def lock_transaction(
    conn: sqlite3.Connection,
    worker_id: int,
    tx_id: int,
    *,
    kind: TransactionKind = TransactionKind.ADVANCE,
    amount: int = 1000,
) -> Settlement:
    settlements = SettlementRepository(conn)
    advances = amount if kind == TransactionKind.ADVANCE else 0
    prepayments = amount if kind == TransactionKind.PREPAYMENT else 0
    deductions = amount if kind == TransactionKind.DEDUCTION else 0
    payable = -(advances + prepayments + deductions)
    with write_transaction(conn):
        settlement = settlements.add(
            Settlement(
                worker_id=worker_id,
                settled_on=date(2026, 11, 12),
                total_minutes=0,
                wage=0,
                advances_total=advances,
                prepayments_total=prepayments,
                deductions_total=deductions,
                previous_balance=0,
                payable=payable,
                paid=0,
                new_balance=payable,
            )
        )
        assert settlement.id is not None
        settlements.attach_records(
            settlement.id,
            session_ids=[],
            transaction_ids=[tx_id],
        )
        return settlement


def test_transaction_totals_validation_and_property() -> None:
    totals = TransactionTotals(advances=5000, prepayments=2000, deductions=1000)
    assert totals.advances == 5000
    assert totals.prepayments == 2000
    assert totals.deductions == 1000
    assert totals.total == 8000

    with pytest.raises(ValidationError):
        TransactionTotals(advances=-1, prepayments=0, deductions=0)

    with pytest.raises(ValidationError):
        TransactionTotals(advances=0, prepayments=True, deductions=0)  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        TransactionTotals(advances=0, prepayments=0, deductions="100")  # type: ignore[arg-type]


def test_default_clock_initialization(
    conn: sqlite3.Connection,
    make_worker: Callable[..., Worker],
) -> None:
    default_svc = TransactionService(conn)
    worker = make_worker(name="عامل افتراضي")
    assert worker.id is not None

    tx = default_svc.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=1000,
        occurred_on=date(2026, 11, 1),
    )
    assert tx.id is not None


@pytest.mark.parametrize(
    "kind",
    [
        TransactionKind.ADVANCE,
        TransactionKind.PREPAYMENT,
        TransactionKind.DEDUCTION,
    ],
)
def test_add_transaction_round_trip(
    service: TransactionService,
    make_worker: Callable[..., Worker],
    kind: TransactionKind,
) -> None:
    worker = make_worker()
    assert worker.id is not None

    tx = service.add_transaction(
        worker.id,
        kind=kind,
        amount=250000,
        occurred_on=date(2026, 11, 10),
        note="سلفة نقدية بالعربية",
    )
    assert tx.id is not None
    assert tx.worker_id == worker.id
    assert tx.kind == kind
    assert tx.amount == 250000
    assert tx.occurred_on == date(2026, 11, 10)
    assert tx.note == "سلفة نقدية بالعربية"
    assert tx.settlement_id is None
    assert not tx.is_locked

    fetched = service.get_transaction(tx.id)
    assert fetched == tx


def test_add_transaction_unknown_worker_raises_record_not_found(
    service: TransactionService,
) -> None:
    with pytest.raises(RecordNotFoundError):
        service.add_transaction(
            999,
            kind=TransactionKind.ADVANCE,
            amount=50000,
            occurred_on=date(2026, 11, 10),
        )


def test_add_transaction_archived_worker_raises_worker_archived(
    workers: WorkerService,
    service: TransactionService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None
    workers.archive_worker(worker.id)

    with pytest.raises(WorkerArchivedError):
        service.add_transaction(
            worker.id,
            kind=TransactionKind.ADVANCE,
            amount=50000,
            occurred_on=date(2026, 11, 10),
        )


@pytest.mark.parametrize(
    "bad_amount",
    [
        0,
        -500,
        10.5,
        True,
        False,
        "1000",
    ],
)
def test_add_transaction_invalid_amount_raises_validation_error(
    service: TransactionService,
    make_worker: Callable[..., Worker],
    bad_amount: int,
) -> None:
    worker = make_worker()
    assert worker.id is not None
    with pytest.raises(ValidationError):
        service.add_transaction(
            worker.id,
            kind=TransactionKind.ADVANCE,
            amount=bad_amount,
            occurred_on=date(2026, 11, 10),
        )


def test_add_transaction_string_kind_raises_validation_error(
    service: TransactionService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None
    with pytest.raises(ValidationError):
        service.add_transaction(
            worker.id,
            kind="advance",  # type: ignore[arg-type]
            amount=5000,
            occurred_on=date(2026, 11, 10),
        )


def test_add_transaction_datetime_date_raises_validation_error(
    service: TransactionService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None
    with pytest.raises(ValidationError):
        service.add_transaction(
            worker.id,
            kind=TransactionKind.ADVANCE,
            amount=5000,
            occurred_on=datetime(2026, 11, 10, 12, 0, 0),  # type: ignore[arg-type]
        )


def test_add_transaction_date_rules(
    service: TransactionService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)

    # Older date accepted
    t1 = service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=10000,
        occurred_on=date(2026, 11, 1),
    )
    assert t1.id is not None

    # Today's date accepted
    t2 = service.add_transaction(
        worker.id,
        kind=TransactionKind.PREPAYMENT,
        amount=20000,
        occurred_on=date(2026, 11, 12),
    )
    assert t2.id is not None

    # Future date rejected
    with pytest.raises(ValidationError, match="date is in the future"):
        service.add_transaction(
            worker.id,
            kind=TransactionKind.DEDUCTION,
            amount=30000,
            occurred_on=date(2026, 11, 13),
        )


def test_update_transaction_modifies_fields(
    service: TransactionService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    tx = service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=10000,
        occurred_on=date(2026, 11, 10),
        note="أصلية",
    )
    assert tx.id is not None

    updated = service.update_transaction(
        tx.id,
        kind=TransactionKind.PREPAYMENT,
        amount=15000,
        occurred_on=date(2026, 11, 11),
        note="معدلة",
    )
    assert updated.id == tx.id
    assert updated.worker_id == worker.id
    assert updated.kind == TransactionKind.PREPAYMENT
    assert updated.amount == 15000
    assert updated.occurred_on == date(2026, 11, 11)
    assert updated.note == "معدلة"

    reloaded = service.get_transaction(tx.id)
    assert reloaded == updated


def test_update_unlocked_transaction_of_archived_worker_allowed(
    workers: WorkerService,
    service: TransactionService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    tx = service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=10000,
        occurred_on=date(2026, 11, 10),
    )
    assert tx.id is not None

    workers.archive_worker(worker.id)
    assert workers.get_worker(worker.id).archived  # type: ignore[union-attr]

    updated = service.update_transaction(
        tx.id,
        kind=TransactionKind.ADVANCE,
        amount=12000,
        occurred_on=date(2026, 11, 10),
        note="تعديل بعد الأرشفة",
    )
    assert updated.amount == 12000


def test_update_transaction_missing_raises_record_not_found(
    service: TransactionService,
) -> None:
    with pytest.raises(RecordNotFoundError, match="transaction not found"):
        service.update_transaction(
            999,
            kind=TransactionKind.ADVANCE,
            amount=5000,
            occurred_on=date(2026, 11, 10),
        )


def test_update_transaction_locked_raises_record_locked(
    conn: sqlite3.Connection,
    service: TransactionService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    tx = service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=10000,
        occurred_on=date(2026, 11, 10),
    )
    assert tx.id is not None

    lock_transaction(conn, worker.id, tx.id)

    with pytest.raises(RecordLockedError):
        service.update_transaction(
            tx.id,
            kind=TransactionKind.PREPAYMENT,
            amount=20000,
            occurred_on=date(2026, 11, 10),
        )

    stored = service.get_transaction(tx.id)
    assert stored is not None
    assert stored.amount == 10000


def test_update_transaction_future_date_rejected_and_unchanged(
    service: TransactionService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    tx = service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=10000,
        occurred_on=date(2026, 11, 10),
    )
    assert tx.id is not None

    with pytest.raises(ValidationError, match="date is in the future"):
        service.update_transaction(
            tx.id,
            kind=TransactionKind.ADVANCE,
            amount=10000,
            occurred_on=date(2026, 11, 15),
        )

    stored = service.get_transaction(tx.id)
    assert stored is not None
    assert stored.occurred_on == date(2026, 11, 10)


def test_delete_transaction_unlocked_and_locked(
    conn: sqlite3.Connection,
    service: TransactionService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    tx1 = service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=5000,
        occurred_on=date(2026, 11, 10),
    )
    assert tx1.id is not None
    service.delete_transaction(tx1.id)
    assert service.get_transaction(tx1.id) is None

    # Deleting missing raises RecordNotFoundError
    with pytest.raises(RecordNotFoundError, match="transaction not found"):
        service.delete_transaction(tx1.id)

    # Deleting locked raises RecordLockedError and row remains
    tx2 = service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=10000,
        occurred_on=date(2026, 11, 10),
    )
    assert tx2.id is not None
    lock_transaction(conn, worker.id, tx2.id)

    with pytest.raises(RecordLockedError):
        service.delete_transaction(tx2.id)

    assert service.get_transaction(tx2.id) is not None


def test_reads_and_filtering(
    conn: sqlite3.Connection,
    service: TransactionService,
    make_worker: Callable[..., Worker],
) -> None:
    w1 = make_worker(name="عامل 1")
    w2 = make_worker(name="عامل 2")
    assert w1.id is not None and w2.id is not None

    # Unknown worker returns []
    assert service.list_transactions(999) == []

    # w1 transactions
    t1 = service.add_transaction(
        w1.id,
        kind=TransactionKind.ADVANCE,
        amount=1000,
        occurred_on=date(2026, 11, 8),
    )
    t2 = service.add_transaction(
        w1.id,
        kind=TransactionKind.PREPAYMENT,
        amount=2000,
        occurred_on=date(2026, 11, 10),
    )
    t3 = service.add_transaction(
        w1.id,
        kind=TransactionKind.DEDUCTION,
        amount=3000,
        occurred_on=date(2026, 11, 12),
    )
    assert t1.id is not None and t2.id is not None and t3.id is not None

    # w2 transaction
    t_other = service.add_transaction(
        w2.id,
        kind=TransactionKind.ADVANCE,
        amount=9999,
        occurred_on=date(2026, 11, 10),
    )
    assert t_other.id is not None

    # List all for w1 (excludes w2, ordered by date then id)
    all_w1 = service.list_transactions(w1.id)
    assert [t.id for t in all_w1] == [t1.id, t2.id, t3.id]

    # Date range inclusive
    range_w1 = service.list_transactions(
        w1.id,
        from_date=date(2026, 11, 10),
        to_date=date(2026, 11, 12),
    )
    assert [t.id for t in range_w1] == [t2.id, t3.id]

    # Lock t1
    lock_transaction(conn, w1.id, t1.id)

    unsettled_w1 = service.list_transactions(w1.id, unsettled_only=True)
    assert [t.id for t in unsettled_w1] == [t2.id, t3.id]


def test_unsettled_totals(
    conn: sqlite3.Connection,
    service: TransactionService,
    make_worker: Callable[..., Worker],
) -> None:
    w1 = make_worker(name="عامل أ")
    w2 = make_worker(name="عامل ب")
    assert w1.id is not None and w2.id is not None

    # Unknown worker totals are all zero
    zeros = service.unsettled_totals(999)
    assert zeros == TransactionTotals(advances=0, prepayments=0, deductions=0)
    assert zeros.total == 0

    # Add transactions for w1
    t1 = service.add_transaction(
        w1.id,
        kind=TransactionKind.ADVANCE,
        amount=3000,
        occurred_on=date(2026, 11, 10),
    )
    t2 = service.add_transaction(
        w1.id,
        kind=TransactionKind.ADVANCE,
        amount=2000,
        occurred_on=date(2026, 11, 10),
    )
    service.add_transaction(
        w1.id,
        kind=TransactionKind.PREPAYMENT,
        amount=4000,
        occurred_on=date(2026, 11, 10),
    )
    service.add_transaction(
        w1.id,
        kind=TransactionKind.DEDUCTION,
        amount=1500,
        occurred_on=date(2026, 11, 10),
    )

    # Add transaction for w2 (should not mix)
    service.add_transaction(
        w2.id,
        kind=TransactionKind.ADVANCE,
        amount=50000,
        occurred_on=date(2026, 11, 10),
    )

    totals = service.unsettled_totals(w1.id)
    assert totals.advances == 5000
    assert totals.prepayments == 4000
    assert totals.deductions == 1500
    assert totals.total == 10500

    w2_totals = service.unsettled_totals(w2.id)
    assert w2_totals.advances == 50000
    assert w2_totals.total == 50000

    # Lock t1 and t2: advances drop to 0
    assert t1.id is not None and t2.id is not None
    settlements = SettlementRepository(conn)
    with write_transaction(conn):
        s = settlements.add(
            Settlement(
                worker_id=w1.id,
                settled_on=date(2026, 11, 12),
                total_minutes=0,
                wage=0,
                advances_total=5000,
                prepayments_total=0,
                deductions_total=0,
                previous_balance=0,
                payable=-5000,
                paid=0,
                new_balance=-5000,
            )
        )
        assert s.id is not None
        settlements.attach_records(s.id, session_ids=[], transaction_ids=[t1.id, t2.id])

    new_totals = service.unsettled_totals(w1.id)
    assert new_totals.advances == 0
    assert new_totals.prepayments == 4000
    assert new_totals.deductions == 1500
    assert new_totals.total == 5500


def test_integration_domain_example1(
    attendance: AttendanceService,
    service: TransactionService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    # Brief Example 1:
    # 100 h at 50 DA = 5000 DA wage; advances 7000 DA; previous balance 0
    # -> payable -2000 DA (-200000 centimes); paid 0; new balance -2000 DA (-200000 centimes)
    worker = make_worker(name="طارق")
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)

    # 100 hours = 6000 minutes. We can record two 50-hour manual sessions (or one manual session).
    # Day 1: 08:00 to 18:00 (10 hours = 600 minutes) x 10 days
    for day_offset in range(1, 11):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, day_offset),
            start_clock=datetime.strptime("08:00", "%H:%M").time(),
            end_clock=datetime.strptime("18:00", "%H:%M").time(),
        )

    # Advance 7000 DA = 700000 centimes
    service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=700000,
        occurred_on=date(2026, 11, 5),
    )

    unsettled_sessions = attendance.list_sessions(worker.id, unsettled_only=True)
    unsettled_txs = service.list_transactions(worker.id, unsettled_only=True)

    draft = prepare_settlement(
        worker_id=worker.id,
        sessions=unsettled_sessions,
        transactions=unsettled_txs,
        previous_balance=0,
        hourly_rate=5000,  # 50 DA/h = 5000 centimes/h
    )

    assert draft.total_minutes == 6000
    assert draft.wage == 500000  # 5000 DA
    assert draft.advances_total == 700000  # 7000 DA
    assert draft.payable == -200000  # -2000 DA
    assert draft.max_paid == 0

    settlement = draft.finalize(paid=0, settled_on=date(2026, 11, 12))
    assert settlement.new_balance == -200000


@pytest.mark.parametrize(
    "operation",
    [
        lambda s: s.get_transaction(999),
        lambda s: s.list_transactions(999),
        lambda s: s.unsettled_totals(999),
    ],
)
def test_transaction_hygiene_success(
    conn: sqlite3.Connection,
    service: TransactionService,
    operation: Callable[[TransactionService], object],
) -> None:
    operation(service)
    assert not conn.in_transaction


@pytest.mark.parametrize(
    "operation, expected_error",
    [
        (
            lambda s: s.add_transaction(
                999,
                kind=TransactionKind.ADVANCE,
                amount=1000,
                occurred_on=date(2026, 11, 1),
            ),
            RecordNotFoundError,
        ),
        (
            lambda s: s.update_transaction(
                999,
                kind=TransactionKind.ADVANCE,
                amount=1000,
                occurred_on=date(2026, 11, 1),
            ),
            RecordNotFoundError,
        ),
        (lambda s: s.delete_transaction(999), RecordNotFoundError),
    ],
)
def test_transaction_hygiene_failure(
    conn: sqlite3.Connection,
    service: TransactionService,
    operation: Callable[[TransactionService], object],
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        operation(service)
    assert not conn.in_transaction


def test_rollback_on_add_error(
    conn: sqlite3.Connection,
    service: TransactionService,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = make_worker()
    assert worker.id is not None

    def fake_add(self: TransactionRepository, tx: Transaction) -> Transaction:
        raise DatabaseError("simulated database failure on add")

    monkeypatch.setattr(TransactionRepository, "add", fake_add)

    with pytest.raises(DatabaseError, match="simulated database failure on add"):
        service.add_transaction(
            worker.id,
            kind=TransactionKind.ADVANCE,
            amount=5000,
            occurred_on=date(2026, 11, 10),
        )

    assert not conn.in_transaction
    assert service.list_transactions(worker.id) == []


def test_rollback_on_update_error(
    conn: sqlite3.Connection,
    service: TransactionService,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = make_worker()
    assert worker.id is not None

    tx = service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=5000,
        occurred_on=date(2026, 11, 10),
    )
    assert tx.id is not None

    def fake_update(self: TransactionRepository, t: Transaction) -> Transaction:
        raise DatabaseError("simulated database failure on update")

    monkeypatch.setattr(TransactionRepository, "update", fake_update)

    with pytest.raises(DatabaseError, match="simulated database failure on update"):
        service.update_transaction(
            tx.id,
            kind=TransactionKind.ADVANCE,
            amount=9999,
            occurred_on=date(2026, 11, 10),
        )

    assert not conn.in_transaction
    reloaded = service.get_transaction(tx.id)
    assert reloaded is not None
    assert reloaded.amount == 5000


def test_rollback_on_delete_error(
    conn: sqlite3.Connection,
    service: TransactionService,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = make_worker()
    assert worker.id is not None

    tx = service.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=5000,
        occurred_on=date(2026, 11, 10),
    )
    assert tx.id is not None

    def fake_delete(self: TransactionRepository, transaction_id: int) -> None:
        raise DatabaseError("simulated database failure on delete")

    monkeypatch.setattr(TransactionRepository, "delete", fake_delete)

    with pytest.raises(DatabaseError, match="simulated database failure on delete"):
        service.delete_transaction(tx.id)

    assert not conn.in_transaction
    assert service.get_transaction(tx.id) is not None
