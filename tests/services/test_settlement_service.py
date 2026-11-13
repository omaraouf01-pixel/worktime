"""Comprehensive tests for SettlementService: preview, atomic settlements, reads, and atomicity."""

import ast
import dataclasses
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

import pytest

from tests.services.conftest import FakeClock
from worktime.data import (
    DatabaseError,
    RecordNotFoundError,
    SessionRepository,
    SettlementRepository,
    TransactionRepository,
)
from worktime.domain import (
    Settlement,
    SettlementDraft,
    TransactionKind,
    ValidationError,
    Worker,
)
from worktime.services import (
    AttendanceService,
    NothingToSettleError,
    SettlementChangedError,
    SettlementDetails,
    SettlementPreview,
    SettlementService,
    TransactionService,
    WorkerHasOpenSessionError,
    WorkerService,
)


@pytest.fixture
def transactions(conn: sqlite3.Connection, clock: FakeClock) -> TransactionService:
    """Fixture providing TransactionService with injected clock."""
    return TransactionService(conn, clock=clock)


@pytest.fixture
def settlements(conn: sqlite3.Connection, clock: FakeClock) -> SettlementService:
    """Fixture providing SettlementService with injected clock."""
    return SettlementService(conn, clock=clock)


# ---------------------------------------------------------------------------
# End-to-end scenarios
# ---------------------------------------------------------------------------


def test_example_1_settlement(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    transactions: TransactionService,
    settlements: SettlementService,
    clock: FakeClock,
    conn: sqlite3.Connection,
) -> None:
    """Verify Example 1: 10 sessions, 1 advance, preview, settle, and details."""
    worker = make_worker(name="عمر بن الخطاب")
    assert worker.id is not None

    # 10 sessions of 600 minutes each (08:00 - 18:00 on 2026-11-01..2026-11-10)
    for day_num in range(1, 11):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, day_num),
            start_clock=time(8, 0),
            end_clock=time(18, 0),
        )

    clock.now = datetime(2026, 11, 12, 18, 0, 0)

    # One advance of 700000 centimes on 2026-11-05
    transactions.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=700000,
        occurred_on=date(2026, 11, 5),
    )

    preview = settlements.preview_settlement(worker.id, hourly_rate=5000)
    assert preview.draft.total_minutes == 6000
    assert preview.draft.wage == 500000
    assert preview.draft.payable == -200000
    assert preview.draft.max_paid == 0
    assert preview.session_count == 10
    assert preview.transaction_count == 1

    settlement = settlements.settle(
        worker.id,
        hourly_rate=5000,
        paid=0,
        expected_payable=-200000,
    )
    assert settlement.id is not None
    assert settlement.new_balance == -200000
    assert settlement.settled_on == date(2026, 11, 12)
    assert settlements.current_balance(worker.id) == -200000

    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)
    assert session_repo.list_for_worker(worker.id, unsettled_only=True) == []
    assert tx_repo.list_for_worker(worker.id, unsettled_only=True) == []

    details = settlements.get_details(settlement.id)
    assert details is not None
    assert len(details.sessions) == 10
    assert len(details.transactions) == 1
    assert details.sessions[0].start == datetime(2026, 11, 1, 8, 0)
    assert details.transactions[0].amount == 700000


def test_example_2_continuation(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    transactions: TransactionService,
    settlements: SettlementService,
    clock: FakeClock,
) -> None:
    """Verify Example 2: continuation with negative previous balance to positive new balance."""
    worker = make_worker(name="علي بن أبي طالب")
    assert worker.id is not None

    # Step 1: Same as Example 1 -> leaves balance -200000
    for day_num in range(1, 11):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, day_num),
            start_clock=time(8, 0),
            end_clock=time(18, 0),
        )
    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    transactions.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=700000,
        occurred_on=date(2026, 11, 5),
    )
    s1 = settlements.settle(worker.id, hourly_rate=5000, paid=0, expected_payable=-200000)
    assert s1.id is not None

    # Step 2: Set clock to 2026-12-31 18:00:00
    clock.now = datetime(2026, 12, 31, 18, 0, 0)

    # 12 sessions of 600 minutes on 2026-12-01..2026-12-12
    for day_num in range(1, 13):
        attendance.add_manual(
            worker.id,
            day=date(2026, 12, day_num),
            start_clock=time(8, 0),
            end_clock=time(18, 0),
        )

    preview = settlements.preview_settlement(worker.id, hourly_rate=5000)
    assert preview.draft.previous_balance == -200000
    assert preview.draft.wage == 600000
    assert preview.draft.payable == 400000
    assert preview.draft.max_paid == 400000
    assert preview.session_count == 12
    assert preview.transaction_count == 0

    s2 = settlements.settle(worker.id, hourly_rate=5000, paid=300000)
    assert s2.id is not None
    assert s2.new_balance == 100000
    assert settlements.current_balance(worker.id) == 100000

    details_2 = settlements.get_details(s2.id)
    assert details_2 is not None
    assert len(details_2.sessions) == 12
    assert len(details_2.transactions) == 0

    details_1 = settlements.get_details(s1.id)
    assert details_1 is not None
    assert len(details_1.sessions) == 10
    assert len(details_1.transactions) == 1


def test_november_file_scenario(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    transactions: TransactionService,
    settlements: SettlementService,
    clock: FakeClock,
) -> None:
    """Verify November scenario: 22 sessions of 210m (4620m), 4 advances (450000), rate 10000."""
    worker = make_worker(name="طارق بن زياد")
    assert worker.id is not None

    clock.now = datetime(2026, 11, 30, 20, 0, 0)

    # 22 sessions of 210 minutes (09:00 - 12:30 on distinct days)
    for day_num in range(1, 23):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, day_num),
            start_clock=time(9, 0),
            end_clock=time(12, 30),
        )

    # 4 advances totaling 450000 (100000 + 100000 + 150000 + 100000)
    advances = [100000, 100000, 150000, 100000]
    for i, amount in enumerate(advances, start=1):
        transactions.add_transaction(
            worker.id,
            kind=TransactionKind.ADVANCE,
            amount=amount,
            occurred_on=date(2026, 11, i),
        )

    preview = settlements.preview_settlement(worker.id, hourly_rate=10000)
    assert preview.draft.total_minutes == 4620
    assert preview.draft.wage == 770000
    assert preview.draft.advances_total == 450000
    assert preview.draft.payable == 320000

    settlement = settlements.settle(
        worker.id,
        hourly_rate=10000,
        paid=320000,
        expected_payable=320000,
    )
    assert settlement.new_balance == 0
    assert settlements.current_balance(worker.id) == 0


def test_debt_only_settlement(
    make_worker: Callable[..., Worker],
    transactions: TransactionService,
    settlements: SettlementService,
) -> None:
    """Verify debt-only settlement: no sessions, 1 deduction of 30000, payable == -30000."""
    worker = make_worker(name="سعد بن أبي وقاص")
    assert worker.id is not None

    transactions.add_transaction(
        worker.id,
        kind=TransactionKind.DEDUCTION,
        amount=30000,
        occurred_on=date(2026, 11, 10),
    )

    preview = settlements.preview_settlement(worker.id, hourly_rate=0)
    assert preview.draft.payable == -30000
    assert preview.draft.total_minutes == 0
    assert preview.draft.wage == 0

    settlement = settlements.settle(worker.id, hourly_rate=0, paid=0)
    assert settlement.new_balance == -30000
    assert settlements.current_balance(worker.id) == -30000


@pytest.mark.parametrize(
    ("paid", "expected_balance"),
    [
        (100000, 0),
        (40000, 60000),
    ],
)
def test_positive_balance_settlement(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
    paid: int,
    expected_balance: int,
) -> None:
    """Verify settling a positive balance with no new records and rate=0."""
    worker = make_worker(name="خالد بن الوليد")
    assert worker.id is not None

    # Step 1: Create a settlement that leaves +100000 balance
    # 600 minutes at 10000 centimes/hr = 100000 centimes wage; paid 0 -> balance +100000
    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(18, 0),
    )
    s1 = settlements.settle(worker.id, hourly_rate=10000, paid=0)
    assert s1.new_balance == 100000

    # Step 2: Settle again with no new records and rate=0
    preview = settlements.preview_settlement(worker.id, hourly_rate=0)
    assert preview.draft.previous_balance == 100000
    assert preview.draft.payable == 100000
    assert preview.draft.max_paid == 100000
    assert preview.session_count == 0
    assert preview.transaction_count == 0

    s2 = settlements.settle(worker.id, hourly_rate=0, paid=paid)
    assert s2.new_balance == expected_balance
    assert settlements.current_balance(worker.id) == expected_balance


# ---------------------------------------------------------------------------
# Rules and rejections
# ---------------------------------------------------------------------------


def test_open_session_rejected_on_preview_and_settle(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
) -> None:
    """Verify WorkerHasOpenSessionError is raised when worker has an active open session."""
    worker = make_worker()
    assert worker.id is not None

    attendance.start_work(worker.id)

    with pytest.raises(WorkerHasOpenSessionError):
        settlements.preview_settlement(worker.id, hourly_rate=5000)
    assert not conn.in_transaction

    with pytest.raises(WorkerHasOpenSessionError):
        settlements.settle(worker.id, hourly_rate=5000, paid=0)
    assert not conn.in_transaction

    settlement_repo = SettlementRepository(conn)
    assert settlement_repo.list_for_worker(worker.id) == []


def test_nothing_to_settle_zero_and_negative_balance(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    transactions: TransactionService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
) -> None:
    """Verify NothingToSettleError on zero balance and on negative balance with no records."""
    worker = make_worker()
    assert worker.id is not None

    # Case A: 0 balance, no records
    with pytest.raises(NothingToSettleError):
        settlements.preview_settlement(worker.id, hourly_rate=5000)
    assert not conn.in_transaction

    with pytest.raises(NothingToSettleError):
        settlements.settle(worker.id, hourly_rate=5000, paid=0)
    assert not conn.in_transaction

    # Case B: Create a debt settlement (-200000)
    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(18, 0),
    )
    transactions.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=300000,
        occurred_on=date(2026, 11, 1),
    )
    settlements.settle(worker.id, hourly_rate=10000, paid=0)
    assert settlements.current_balance(worker.id) == -200000

    # Now no new records and previous balance is -200000
    with pytest.raises(NothingToSettleError):
        settlements.preview_settlement(worker.id, hourly_rate=5000)
    assert not conn.in_transaction

    with pytest.raises(NothingToSettleError):
        settlements.settle(worker.id, hourly_rate=5000, paid=0)
    assert not conn.in_transaction


def test_unknown_worker_and_archived_worker(
    make_worker: Callable[..., Worker],
    workers: WorkerService,
    attendance: AttendanceService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
) -> None:
    """Verify RecordNotFoundError for unknown worker, and archived workers can be settled."""
    with pytest.raises(RecordNotFoundError):
        settlements.preview_settlement(99999, hourly_rate=5000)
    assert not conn.in_transaction

    with pytest.raises(RecordNotFoundError):
        settlements.settle(99999, hourly_rate=5000, paid=0)
    assert not conn.in_transaction

    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(12, 0),
    )
    workers.archive_worker(worker.id)

    # Archived worker can be previewed and settled
    preview = settlements.preview_settlement(worker.id, hourly_rate=5000)
    assert preview.session_count == 1
    settlement = settlements.settle(worker.id, hourly_rate=5000, paid=0)
    assert settlement.id is not None


@pytest.mark.parametrize(
    "invalid_paid",
    [
        500001,  # exceeds max_paid
        -1,  # negative
        True,  # bool
        10.5,  # float
    ],
)
def test_paid_validation_rejections(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
    invalid_paid: Any,
) -> None:
    """Verify ValidationError on invalid paid amount and database left unchanged."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(13, 0),
    )

    with pytest.raises(ValidationError):
        settlements.settle(worker.id, hourly_rate=100000, paid=invalid_paid)

    assert not conn.in_transaction
    settlement_repo = SettlementRepository(conn)
    assert settlement_repo.list_for_worker(worker.id) == []


def test_paid_greater_than_zero_when_payable_non_positive(
    make_worker: Callable[..., Worker],
    transactions: TransactionService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
) -> None:
    """Verify ValidationError when paid > 0 and payable <= 0."""
    worker = make_worker()
    assert worker.id is not None

    transactions.add_transaction(
        worker.id,
        kind=TransactionKind.DEDUCTION,
        amount=10000,
        occurred_on=date(2026, 11, 1),
    )

    with pytest.raises(ValidationError):
        settlements.settle(worker.id, hourly_rate=0, paid=5000)

    assert not conn.in_transaction
    settlement_repo = SettlementRepository(conn)
    assert settlement_repo.list_for_worker(worker.id) == []


@pytest.mark.parametrize(
    "invalid_rate",
    [
        -1,
        True,
        10.5,
        "50",
    ],
)
def test_hourly_rate_validation_rejections(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
    invalid_rate: Any,
) -> None:
    """Verify ValidationError on invalid hourly rate on preview and settle."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(12, 0),
    )

    with pytest.raises(ValidationError):
        settlements.preview_settlement(worker.id, hourly_rate=invalid_rate)
    assert not conn.in_transaction

    with pytest.raises(ValidationError):
        settlements.settle(worker.id, hourly_rate=invalid_rate, paid=0)
    assert not conn.in_transaction

    settlement_repo = SettlementRepository(conn)
    assert settlement_repo.list_for_worker(worker.id) == []


def test_expected_payable_matching_and_mismatching(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
) -> None:
    """Verify expected_payable matches or raises SettlementChangedError leaving DB clean."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(14, 0),
    )

    # Hourly rate 5000 centimes, 360 min -> 30000 centimes payable
    preview = settlements.preview_settlement(worker.id, hourly_rate=5000)
    assert preview.draft.payable == 30000

    # Mismatching raises SettlementChangedError
    with pytest.raises(SettlementChangedError):
        settlements.settle(
            worker.id,
            hourly_rate=5000,
            paid=0,
            expected_payable=35000,
        )
    assert not conn.in_transaction
    settlement_repo = SettlementRepository(conn)
    assert settlement_repo.list_for_worker(worker.id) == []

    # Matching passes
    settlement = settlements.settle(
        worker.id,
        hourly_rate=5000,
        paid=0,
        expected_payable=30000,
    )
    assert settlement.id is not None


def test_stale_preview_scenario(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
) -> None:
    """Verify stale preview detection and fresh data recomputation."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(14, 0),
    )

    preview = settlements.preview_settlement(worker.id, hourly_rate=5000)
    old_payable = preview.draft.payable
    assert old_payable == 30000

    # Another session is added after preview
    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 2),
        start_clock=time(8, 0),
        end_clock=time(14, 0),
    )

    # Settle with stale expected payable raises SettlementChangedError
    with pytest.raises(SettlementChangedError):
        settlements.settle(
            worker.id,
            hourly_rate=5000,
            paid=0,
            expected_payable=old_payable,
        )

    # Settle without expected_payable succeeds and recomputes with BOTH sessions
    settlement = settlements.settle(worker.id, hourly_rate=5000, paid=0)
    assert settlement.total_minutes == 720
    assert settlement.wage == 60000


def test_locked_records_never_counted_again(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
) -> None:
    """Verify that settled records are locked and never counted in subsequent settlements."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(18, 0),
    )

    settlements.settle(worker.id, hourly_rate=5000, paid=50000)

    # Next preview with balance == 0 raises NothingToSettleError
    with pytest.raises(NothingToSettleError):
        settlements.preview_settlement(worker.id, hourly_rate=5000)


def test_two_workers_isolation(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    transactions: TransactionService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
) -> None:
    """Verify that settling worker A does not affect worker B's records or balance."""
    worker_a = make_worker(name="عامل أ")
    worker_b = make_worker(name="عامل ب")
    assert worker_a.id is not None
    assert worker_b.id is not None

    attendance.add_manual(
        worker_a.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(18, 0),
    )
    attendance.add_manual(
        worker_b.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(18, 0),
    )
    transactions.add_transaction(
        worker_b.id,
        kind=TransactionKind.ADVANCE,
        amount=50000,
        occurred_on=date(2026, 11, 1),
    )

    settlements.settle(worker_a.id, hourly_rate=5000, paid=50000)

    # Worker B's records are completely unlocked
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)
    assert len(session_repo.list_for_worker(worker_b.id, unsettled_only=True)) == 1
    assert len(tx_repo.list_for_worker(worker_b.id, unsettled_only=True)) == 1
    assert settlements.current_balance(worker_b.id) == 0

    # current_balances only contains worker_a until worker_b is settled
    assert settlements.current_balances() == {worker_a.id: 0}

    settlements.settle(worker_b.id, hourly_rate=5000, paid=0)
    assert settlements.current_balances() == {worker_a.id: 0, worker_b.id: 0}


def test_hourly_rate_never_stored(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
    clock: FakeClock,
) -> None:
    """Verify that hourly rate is never stored in DB and does not exist as a dataclass field."""
    # 1. Database table schema check
    cursor = conn.execute("PRAGMA table_info(settlements)")
    columns = [row[1] for row in cursor.fetchall()]
    for col in columns:
        assert "rate" not in col.lower(), f"Found rate in column name: {col}"

    # 2. Dataclass fields check
    for cls in (Settlement, SettlementDraft, SettlementPreview, SettlementDetails):
        for field in dataclasses.fields(cls):
            assert "rate" not in field.name.lower(), f"Found rate in {cls.__name__}.{field.name}"

    # 3. Execution check: settled_on matches injected clock
    worker = make_worker()
    assert worker.id is not None
    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(12, 0),
    )
    clock.now = datetime(2026, 11, 20, 10, 0, 0)
    settlement = settlements.settle(worker.id, hourly_rate=7500, paid=0, note="ملاحظة")
    assert settlement.settled_on == date(2026, 11, 20)
    assert settlement.note == "ملاحظة"


def test_preview_writes_nothing(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    transactions: TransactionService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
) -> None:
    """Verify preview_settlement leaves all tables completely unmodified."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(12, 0),
    )
    transactions.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=5000,
        occurred_on=date(2026, 11, 1),
    )

    def get_counts() -> dict[str, int]:
        tables = ["workers", "sessions", "money_transactions", "settlements"]
        return {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }

    counts_before = get_counts()
    preview = settlements.preview_settlement(worker.id, hourly_rate=5000)
    assert preview.session_count == 1
    assert preview.transaction_count == 1
    counts_after = get_counts()

    assert counts_before == counts_after
    assert not conn.in_transaction


# ---------------------------------------------------------------------------
# Atomicity tests
# ---------------------------------------------------------------------------


def test_atomicity_rollback_on_attach_records_failure(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    transactions: TransactionService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify complete rollback when attach_records fails."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(18, 0),
    )
    transactions.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=10000,
        occurred_on=date(2026, 11, 1),
    )

    def failing_attach(*args: Any, **kwargs: Any) -> None:
        raise DatabaseError("Simulated attach error")

    monkeypatch.setattr(SettlementRepository, "attach_records", failing_attach)

    with pytest.raises(DatabaseError, match="Simulated attach error"):
        settlements.settle(worker.id, hourly_rate=5000, paid=0)

    assert not conn.in_transaction
    settlement_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)

    assert settlement_repo.list_for_worker(worker.id) == []
    unsettled_sessions = session_repo.list_for_worker(worker.id, unsettled_only=True)
    assert len(unsettled_sessions) == 1
    assert unsettled_sessions[0].settlement_id is None
    unsettled_txs = tx_repo.list_for_worker(worker.id, unsettled_only=True)
    assert len(unsettled_txs) == 1
    assert unsettled_txs[0].settlement_id is None


def test_atomicity_rollback_on_add_failure(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    transactions: TransactionService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify complete rollback when SettlementRepository.add fails."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(18, 0),
    )
    transactions.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=10000,
        occurred_on=date(2026, 11, 1),
    )

    def failing_add(*args: Any, **kwargs: Any) -> Settlement:
        raise DatabaseError("Simulated add error")

    monkeypatch.setattr(SettlementRepository, "add", failing_add)

    with pytest.raises(DatabaseError, match="Simulated add error"):
        settlements.settle(worker.id, hourly_rate=5000, paid=0)

    assert not conn.in_transaction
    settlement_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)

    assert settlement_repo.list_for_worker(worker.id) == []
    assert len(session_repo.list_for_worker(worker.id, unsettled_only=True)) == 1


def test_atomicity_partial_lock_rollback(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that if attach_records locks one session and then fails, that session is unlocked."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(12, 0),
    )
    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 2),
        start_clock=time(8, 0),
        end_clock=time(12, 0),
    )

    real_attach = SettlementRepository.attach_records

    def partial_failing_attach(
        self: SettlementRepository,
        settlement_id: int,
        *,
        session_ids: list[int],
        transaction_ids: list[int],
    ) -> None:
        # Lock only the first session, then simulate error
        real_attach(
            self,
            settlement_id,
            session_ids=[session_ids[0]],
            transaction_ids=[],
        )
        raise DatabaseError("Crash during multi-record attach")

    monkeypatch.setattr(SettlementRepository, "attach_records", partial_failing_attach)

    with pytest.raises(DatabaseError, match="Crash during multi-record attach"):
        settlements.settle(worker.id, hourly_rate=5000, paid=0)

    assert not conn.in_transaction

    settlement_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)

    assert settlement_repo.list_for_worker(worker.id) == []
    unsettled = session_repo.list_for_worker(worker.id, unsettled_only=True)
    assert len(unsettled) == 2
    for s in unsettled:
        assert s.settlement_id is None


def test_atomicity_retry_after_failure(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    transactions: TransactionService,
    settlements: SettlementService,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify that a failed settlement can be retried successfully with the same data."""
    worker = make_worker()
    assert worker.id is not None

    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(18, 0),
    )
    transactions.add_transaction(
        worker.id,
        kind=TransactionKind.ADVANCE,
        amount=10000,
        occurred_on=date(2026, 11, 1),
    )

    # 1. Fail once
    failed = True

    def flaky_attach(self: SettlementRepository, *args: Any, **kwargs: Any) -> None:
        nonlocal failed
        if failed:
            failed = False
            raise DatabaseError("Temporary transient failure")
        real_attach(self, *args, **kwargs)

    real_attach = SettlementRepository.attach_records
    monkeypatch.setattr(SettlementRepository, "attach_records", flaky_attach)

    with pytest.raises(DatabaseError):
        settlements.settle(worker.id, hourly_rate=5000, paid=0)

    # 2. Retry succeeds
    settlement = settlements.settle(worker.id, hourly_rate=5000, paid=0)
    assert settlement.id is not None


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


def test_get_settlement_and_details_miss(settlements: SettlementService) -> None:
    """Verify get_settlement and get_details return None when ID does not exist."""
    assert settlements.get_settlement(99999) is None
    assert settlements.get_details(99999) is None


def test_list_settlements_order_and_filtering(
    make_worker: Callable[..., Worker],
    attendance: AttendanceService,
    settlements: SettlementService,
    clock: FakeClock,
) -> None:
    """Verify list_settlements returns settlements sorted by ID ascending for target worker only."""
    worker_1 = make_worker(name="عامل أول")
    worker_2 = make_worker(name="عامل ثان")
    assert worker_1.id is not None
    assert worker_2.id is not None

    # Worker 1: 1st settlement
    attendance.add_manual(
        worker_1.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(12, 0),
    )
    s1 = settlements.settle(worker_1.id, hourly_rate=5000, paid=0)

    # Worker 2: settlement
    attendance.add_manual(
        worker_2.id,
        day=date(2026, 11, 1),
        start_clock=time(8, 0),
        end_clock=time(12, 0),
    )
    s2 = settlements.settle(worker_2.id, hourly_rate=5000, paid=0)

    # Worker 1: 2nd settlement
    clock.now = datetime(2026, 12, 1, 18, 0, 0)
    attendance.add_manual(
        worker_1.id,
        day=date(2026, 12, 1),
        start_clock=time(8, 0),
        end_clock=time(12, 0),
    )
    s3 = settlements.settle(worker_1.id, hourly_rate=5000, paid=0)

    list_w1 = settlements.list_settlements(worker_1.id)
    assert len(list_w1) == 2
    assert list_w1[0].id == s1.id
    assert list_w1[1].id == s3.id

    list_w2 = settlements.list_settlements(worker_2.id)
    assert len(list_w2) == 1
    assert list_w2[0].id == s2.id


def test_current_balance_and_current_balances_without_settlements(
    make_worker: Callable[..., Worker],
    settlements: SettlementService,
) -> None:
    """Verify current_balance returns 0 and current_balances excludes unsettled workers."""
    worker = make_worker()
    assert worker.id is not None

    assert settlements.current_balance(worker.id) == 0
    assert settlements.current_balances() == {}


# ---------------------------------------------------------------------------
# Architecture and hygiene AST tests
# ---------------------------------------------------------------------------


def test_settlements_ast_architecture() -> None:
    """Verify settlements.py contains no .execute, no date.today/datetime.now, and no assert."""
    settlements_file = Path("src/worktime/services/settlements.py").resolve()
    assert settlements_file.exists(), "settlements.py does not exist"

    tree = ast.parse(settlements_file.read_text(encoding="utf-8"), filename=str(settlements_file))

    violations: list[str] = []
    for node in ast.walk(tree):
        # 1. No execute or executemany
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in ("execute", "executemany"):
                violations.append(f"Line {node.lineno}: calls {node.func.attr}")

        # 2. No datetime.now or date.today
        if isinstance(node, ast.Attribute) and node.attr in ("now", "today"):
            violations.append(f"Line {node.lineno}: calls direct time method {node.attr}")
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in ("now", "today"):
                    violations.append(f"Line {node.lineno}: imports forbidden time method")

        # 3. No assert statements
        if isinstance(node, ast.Assert):
            violations.append(f"Line {node.lineno}: contains assert statement")

    assert not violations, "Violations found in settlements.py:\n" + "\n".join(violations)


def test_settlement_service_default_clock(conn: sqlite3.Connection) -> None:
    """Verify SettlementService can be initialized with the default system_clock."""
    service = SettlementService(conn)
    assert service.get_settlement(99999) is None
