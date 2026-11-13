"""Unit tests for WorkerService."""

import sqlite3
from collections.abc import Callable
from datetime import date, datetime

import pytest

from worktime.data import (
    DatabaseError,
    DuplicateWorkerError,
    RecordNotFoundError,
    SessionRepository,
    SettlementRepository,
    WorkerRepository,
    write_transaction,
)
from worktime.domain import Session, Settlement, ValidationError, Worker
from worktime.services import (
    WorkerHasOpenSessionError,
    WorkerService,
)


def test_add_get_list_round_trip(workers: WorkerService) -> None:
    worker = workers.add_worker(
        name="عمر بن الخطاب",
        phone="0550123456",
        note="عامل دوام جزئي",
    )
    assert worker.id is not None
    assert worker.name == "عمر بن الخطاب"
    assert worker.phone == "0550123456"
    assert worker.note == "عامل دوام جزئي"
    assert not worker.archived

    fetched = workers.get_worker(worker.id)
    assert fetched == worker

    listed = workers.list_workers()
    assert listed == [worker]


def test_add_worker_duplicate_name_rejected(workers: WorkerService) -> None:
    workers.add_worker(name="علي")
    with pytest.raises(DuplicateWorkerError):
        workers.add_worker(name="علي")


def test_add_worker_invalid_data_raises_validation_error(workers: WorkerService) -> None:
    with pytest.raises(ValidationError):
        workers.add_worker(name="")


def test_get_worker_missing_returns_none(workers: WorkerService) -> None:
    assert workers.get_worker(999) is None


def test_update_worker_updates_fields_and_preserves_archived(
    workers: WorkerService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker(name="زيد", phone="123", note="ملاحظة")
    assert worker.id is not None

    updated = workers.update_worker(
        worker.id,
        name="زيد المعدل",
        phone="456",
        note="ملاحظة جديدة",
    )
    assert updated.id == worker.id
    assert updated.name == "زيد المعدل"
    assert updated.phone == "456"
    assert updated.note == "ملاحظة جديدة"
    assert not updated.archived

    archived = workers.archive_worker(worker.id)
    assert archived.archived

    updated_archived = workers.update_worker(worker.id, name="زيد المؤرشف", phone="", note="")
    assert updated_archived.name == "زيد المؤرشف"
    assert updated_archived.archived


def test_update_worker_missing_raises_record_not_found(workers: WorkerService) -> None:
    with pytest.raises(RecordNotFoundError):
        workers.update_worker(999, name="غير موجود")


def test_update_worker_duplicate_name_rejected_and_unchanged(
    workers: WorkerService,
    make_worker: Callable[..., Worker],
) -> None:
    w1 = make_worker(name="عامل أ")
    w2 = make_worker(name="عامل ب")
    assert w1.id is not None
    assert w2.id is not None

    with pytest.raises(DuplicateWorkerError):
        workers.update_worker(w2.id, name="عامل أ")

    reloaded = workers.get_worker(w2.id)
    assert reloaded is not None
    assert reloaded.name == "عامل ب"


def test_archive_hides_worker_by_default(
    workers: WorkerService,
    make_worker: Callable[..., Worker],
) -> None:
    w1 = make_worker(name="أحمد")
    w2 = make_worker(name="بلال")
    assert w1.id is not None
    assert w2.id is not None

    workers.archive_worker(w1.id)

    active_workers = workers.list_workers()
    assert [w.name for w in active_workers] == ["بلال"]

    all_workers = workers.list_workers(include_archived=True)
    assert {w.name for w in all_workers} == {"أحمد", "بلال"}


def test_archive_refused_when_open_session_exists(
    conn: sqlite3.Connection,
    workers: WorkerService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker(name="طارق")
    assert worker.id is not None

    sessions = SessionRepository(conn)
    with write_transaction(conn):
        sessions.add(Session(worker_id=worker.id, start=datetime(2026, 11, 12, 10, 0, 0)))

    with pytest.raises(WorkerHasOpenSessionError):
        workers.archive_worker(worker.id)

    reloaded = workers.get_worker(worker.id)
    assert reloaded is not None
    assert not reloaded.archived


def test_archive_twice_is_noop(
    workers: WorkerService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker(name="سعيد")
    assert worker.id is not None

    first = workers.archive_worker(worker.id)
    assert first.archived

    second = workers.archive_worker(worker.id)
    assert second == first


def test_archive_missing_raises_record_not_found(workers: WorkerService) -> None:
    with pytest.raises(RecordNotFoundError):
        workers.archive_worker(999)


def test_restore_worker_success(
    workers: WorkerService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker(name="خالد")
    assert worker.id is not None

    workers.archive_worker(worker.id)
    assert workers.get_worker(worker.id) is not None
    assert workers.get_worker(worker.id).archived  # type: ignore[union-attr]

    restored = workers.restore_worker(worker.id)
    assert not restored.archived
    assert workers.list_workers() == [restored]


def test_restore_worker_already_active_is_noop(
    workers: WorkerService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker(name="ياسين")
    assert worker.id is not None

    restored = workers.restore_worker(worker.id)
    assert restored == worker
    assert not restored.archived


def test_restore_worker_into_name_conflict_fails_and_stays_archived(
    workers: WorkerService,
    make_worker: Callable[..., Worker],
) -> None:
    w1 = make_worker(name="حمزة")
    assert w1.id is not None
    workers.archive_worker(w1.id)

    # Add a new active worker with the same name
    workers.add_worker(name="حمزة")

    with pytest.raises(DuplicateWorkerError):
        workers.restore_worker(w1.id)

    reloaded = workers.get_worker(w1.id)
    assert reloaded is not None
    assert reloaded.archived


def test_restore_missing_raises_record_not_found(workers: WorkerService) -> None:
    with pytest.raises(RecordNotFoundError):
        workers.restore_worker(999)


def test_list_summaries_with_balances_and_open_sessions(
    conn: sqlite3.Connection,
    workers: WorkerService,
    make_worker: Callable[..., Worker],
) -> None:
    w1 = make_worker(name="أحمد")
    w2 = make_worker(name="بلال")
    w3 = make_worker(name="جمال")
    assert w1.id is not None and w2.id is not None and w3.id is not None

    # Example 1 settlement from project brief:
    # 100h wage=5000 DA, advances=7000 DA -> payable=-2000 DA, paid=0, new_balance=-200000 centimes
    settlements = SettlementRepository(conn)
    with write_transaction(conn):
        settlements.add(
            Settlement(
                worker_id=w1.id,
                settled_on=date(2026, 11, 10),
                total_minutes=6000,
                wage=500000,
                advances_total=700000,
                prepayments_total=0,
                deductions_total=0,
                previous_balance=0,
                payable=-200000,
                paid=0,
                new_balance=-200000,
            )
        )

    # Worker 2 has an open session
    sessions = SessionRepository(conn)
    open_start = datetime(2026, 11, 12, 14, 0, 0)
    with write_transaction(conn):
        sessions.add(Session(worker_id=w2.id, start=open_start))

    # Worker 3 is archived
    workers.archive_worker(w3.id)

    # Default list excludes archived
    summaries = workers.list_summaries()
    assert len(summaries) == 2
    assert [s.worker.name for s in summaries] == ["أحمد", "بلال"]

    assert summaries[0].balance == -200000
    assert summaries[0].open_since is None

    assert summaries[1].balance == 0
    assert summaries[1].open_since == open_start

    # Include archived
    all_summaries = workers.list_summaries(include_archived=True)
    assert len(all_summaries) == 3
    assert [s.worker.name for s in all_summaries] == ["أحمد", "بلال", "جمال"]
    assert all_summaries[2].balance == 0
    assert all_summaries[2].open_since is None


@pytest.mark.parametrize(
    "operation",
    [
        lambda w: w.get_worker(999),
        lambda w: w.list_workers(),
        lambda w: w.list_summaries(),
        lambda w: w.add_worker(name="تجربة"),
    ],
)
def test_transaction_hygiene_success(
    conn: sqlite3.Connection,
    workers: WorkerService,
    operation: Callable[[WorkerService], object],
) -> None:
    operation(workers)
    assert not conn.in_transaction


@pytest.mark.parametrize(
    "operation, expected_error",
    [
        (lambda w: w.add_worker(name=""), ValidationError),
        (lambda w: w.update_worker(999, name="س"), RecordNotFoundError),
        (lambda w: w.archive_worker(999), RecordNotFoundError),
        (lambda w: w.restore_worker(999), RecordNotFoundError),
    ],
)
def test_transaction_hygiene_failure(
    conn: sqlite3.Connection,
    workers: WorkerService,
    operation: Callable[[WorkerService], object],
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        operation(workers)
    assert not conn.in_transaction


def test_rollback_on_worker_update_error(
    conn: sqlite3.Connection,
    workers: WorkerService,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = make_worker(name="سفيان")
    assert worker.id is not None

    def fake_update(self: WorkerRepository, w: Worker) -> Worker:
        raise DatabaseError("simulated error during update")

    monkeypatch.setattr(WorkerRepository, "update", fake_update)

    with pytest.raises(DatabaseError, match="simulated error"):
        workers.update_worker(worker.id, name="سفيان المعدل")

    assert not conn.in_transaction
    reloaded = workers.get_worker(worker.id)
    assert reloaded is not None
    assert reloaded.name == "سفيان"
