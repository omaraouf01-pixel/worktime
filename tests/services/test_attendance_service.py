"""Unit tests for AttendanceService."""

import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime, time

import pytest

from tests.services.conftest import FakeClock, lock_session
from worktime.data import (
    DatabaseError,
    OpenSessionExistsError,
    RecordNotFoundError,
    SessionRepository,
    write_transaction,
)
from worktime.domain import (
    RecordLockedError,
    Session,
    ValidationError,
    Worker,
)
from worktime.services import (
    AttendanceService,
    NoOpenSessionError,
    SessionOverlapError,
    WorkerArchivedError,
    WorkerService,
    system_clock,
)


def test_system_clock_and_default_attendance_clock(
    conn: sqlite3.Connection,
    make_worker: Callable[..., Worker],
) -> None:
    now = system_clock()
    assert isinstance(now, datetime)
    assert now.tzinfo is None
    assert now.microsecond == 0

    default_service = AttendanceService(conn)
    worker = make_worker(name="عامل افتراضي")
    assert worker.id is not None
    session = default_service.start_work(worker.id)
    assert session.start.microsecond == 0


@pytest.mark.parametrize(
    "invalid_day",
    [
        datetime(2026, 11, 12, 10, 0, 0),
        "2026-11-12",
    ],
)
def test_add_manual_invalid_day_raises_validation_error(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
    invalid_day: object,
) -> None:
    worker = make_worker()
    assert worker.id is not None
    with pytest.raises(ValidationError):
        attendance.add_manual(
            worker.id,
            day=invalid_day,  # type: ignore[arg-type]
            start_clock=time(9, 0),
            end_clock=time(10, 0),
        )


def test_start_and_stop_work_flow(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 12, 0, 0)
    session = attendance.start_work(worker.id)
    assert session.id is not None
    assert session.worker_id == worker.id
    assert session.start == datetime(2026, 11, 12, 12, 0, 0)
    assert session.is_open

    clock.advance(minutes=150)  # 14:30
    assert attendance.unsettled_minutes(worker.id) == 150

    stopped = attendance.stop_work(worker.id)
    assert stopped.id == session.id
    assert stopped.end == datetime(2026, 11, 12, 14, 30, 0)
    assert not stopped.is_open
    assert attendance.unsettled_minutes(worker.id) == 150
    assert attendance.get_open_session(worker.id) is None


def test_start_work_when_already_open_raises_open_session_exists(
    attendance: AttendanceService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    attendance.start_work(worker.id)
    with pytest.raises(OpenSessionExistsError):
        attendance.start_work(worker.id)


def test_stop_work_when_no_open_session_raises_no_open_session(
    attendance: AttendanceService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    with pytest.raises(NoOpenSessionError):
        attendance.stop_work(worker.id)


def test_start_and_stop_unknown_worker_raises_record_not_found(
    attendance: AttendanceService,
) -> None:
    with pytest.raises(RecordNotFoundError):
        attendance.start_work(999)

    with pytest.raises(RecordNotFoundError):
        attendance.stop_work(999)


def test_start_work_archived_worker_raises_worker_archived(
    workers: WorkerService,
    attendance: AttendanceService,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None
    workers.archive_worker(worker.id)

    with pytest.raises(WorkerArchivedError):
        attendance.start_work(worker.id)


def test_stop_work_allowed_for_archived_worker_with_open_session(
    conn: sqlite3.Connection,
    workers: WorkerService,
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    # Archive worker first, then simulate an open session inserted directly into DB
    workers.archive_worker(worker.id)
    sessions = SessionRepository(conn)
    with write_transaction(conn):
        sessions.add(Session(worker_id=worker.id, start=datetime(2026, 11, 12, 10, 0, 0)))

    clock.now = datetime(2026, 11, 12, 12, 0, 0)
    stopped = attendance.stop_work(worker.id)
    assert stopped.end == datetime(2026, 11, 12, 12, 0, 0)
    assert not stopped.is_open


def test_session_crossing_midnight_duration(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 11, 22, 0, 0)
    attendance.start_work(worker.id)

    clock.now = datetime(2026, 11, 12, 2, 0, 0)
    stopped = attendance.stop_work(worker.id)
    assert stopped.end == datetime(2026, 11, 12, 2, 0, 0)
    assert attendance.unsettled_minutes(worker.id) == 240


def test_clock_in_blocked_when_later_session_exists(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(15, 0),
        end_clock=time(17, 0),
    )

    # Move clock back to 16:00
    clock.now = datetime(2026, 11, 12, 16, 0, 0)
    with pytest.raises(SessionOverlapError):
        attendance.start_work(worker.id)

    assert attendance.get_open_session(worker.id) is None


def test_add_manual_normal_and_minute_reduction(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    entry = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(9, 15, 45, 123456),  # seconds/microseconds dropped
        end_clock=time(11, 30, 20, 654321),
        note="صباحا",
    )

    assert not entry.crosses_midnight
    assert entry.session.id is not None
    assert entry.session.start == datetime(2026, 11, 12, 9, 15, 0)
    assert entry.session.end == datetime(2026, 11, 12, 11, 30, 0)
    assert entry.session.note == "صباحا"


def test_add_manual_crossing_midnight(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 10, 0, 0)
    entry = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 11),
        start_clock=time(22, 0),
        end_clock=time(2, 0),
    )

    assert entry.crosses_midnight
    assert entry.session.start == datetime(2026, 11, 11, 22, 0, 0)
    assert entry.session.end == datetime(2026, 11, 12, 2, 0, 0)


def test_add_manual_equal_clocks_raises_validation_error(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    with pytest.raises(ValidationError):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, 12),
            start_clock=time(9, 0),
            end_clock=time(9, 0),
        )


@pytest.mark.parametrize(
    "start_c, end_c",
    [
        (time(9, 0, tzinfo=UTC), time(10, 0)),
        (time(9, 0), time(10, 0, tzinfo=UTC)),
        (datetime(2026, 11, 12, 9, 0), time(10, 0)),  # type: ignore[arg-type]
        (time(9, 0), datetime(2026, 11, 12, 10, 0)),  # type: ignore[arg-type]
        ("09:00", time(10, 0)),  # type: ignore[arg-type]
        (time(9, 0), "10:00"),  # type: ignore[arg-type]
    ],
)
def test_add_manual_invalid_clocks_raises_validation_error(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
    start_c: time,
    end_c: time,
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    with pytest.raises(ValidationError):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, 12),
            start_clock=start_c,
            end_clock=end_c,
        )


def test_add_manual_end_in_future_raises_validation_error(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 10, 0, 0)
    with pytest.raises(ValidationError, match="session ends in the future"):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, 12),
            start_clock=time(9, 0),
            end_clock=time(11, 0),
        )


def test_add_manual_overlap_rejections_and_allowed_adjacencies(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    # Existing session 10:00 - 12:00
    attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
    )

    # Overlaps: 11:00 - 13:00
    with pytest.raises(SessionOverlapError):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, 12),
            start_clock=time(11, 0),
            end_clock=time(13, 0),
        )

    # Adjacent session before (08:00 - 10:00) is allowed
    entry_before = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(8, 0),
        end_clock=time(10, 0),
    )
    assert entry_before.session.id is not None

    # Adjacent session after (12:00 - 14:00) is allowed
    entry_after = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(12, 0),
        end_clock=time(14, 0),
    )
    assert entry_after.session.id is not None


def test_add_manual_overlap_with_another_worker_allowed(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    w1 = make_worker(name="عامل 1")
    w2 = make_worker(name="عامل 2")
    assert w1.id is not None and w2.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    e1 = attendance.add_manual(
        w1.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
    )
    e2 = attendance.add_manual(
        w2.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
    )
    assert e1.session.id is not None
    assert e2.session.id is not None


def test_add_manual_worker_validations(
    workers: WorkerService,
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None
    workers.archive_worker(worker.id)

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    with pytest.raises(WorkerArchivedError):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, 12),
            start_clock=time(9, 0),
            end_clock=time(10, 0),
        )

    with pytest.raises(RecordNotFoundError):
        attendance.add_manual(
            999,
            day=date(2026, 11, 12),
            start_clock=time(9, 0),
            end_clock=time(10, 0),
        )


def test_add_manual_overlap_with_locked_session_rejected(
    conn: sqlite3.Connection,
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    entry = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
    )
    assert entry.session.id is not None
    lock_session(conn, worker.id, entry.session.id)

    with pytest.raises(SessionOverlapError):
        attendance.add_manual(
            worker.id,
            day=date(2026, 11, 12),
            start_clock=time(11, 0),
            end_clock=time(13, 0),
        )


def test_update_session_modifies_session_and_closes_open(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    session = attendance.start_work(worker.id)
    assert session.id is not None
    assert session.is_open

    updated = attendance.update_session(
        session.id,
        start=datetime(2026, 11, 12, 10, 0, 0),
        end=datetime(2026, 11, 12, 14, 0, 0),
        note="تصحيح الجلسة المنسية",
    )
    assert updated.id == session.id
    assert not updated.is_open
    assert updated.start == datetime(2026, 11, 12, 10, 0, 0)
    assert updated.end == datetime(2026, 11, 12, 14, 0, 0)
    assert updated.note == "تصحيح الجلسة المنسية"


def test_update_session_re_saving_same_interval_is_allowed(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    entry = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
    )
    assert entry.session.id is not None

    updated = attendance.update_session(
        entry.session.id,
        start=datetime(2026, 11, 12, 10, 0, 0),
        end=datetime(2026, 11, 12, 12, 0, 0),
        note="تحديث الملاحظة فقط",
    )
    assert updated.note == "تحديث الملاحظة فقط"


def test_update_session_validation_errors(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    entry = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
    )
    assert entry.session.id is not None
    sid = entry.session.id

    # Missing session
    with pytest.raises(RecordNotFoundError):
        attendance.update_session(
            999,
            start=datetime(2026, 11, 12, 10, 0, 0),
            end=datetime(2026, 11, 12, 12, 0, 0),
        )

    # End <= Start
    with pytest.raises(ValidationError):
        attendance.update_session(
            sid,
            start=datetime(2026, 11, 12, 12, 0, 0),
            end=datetime(2026, 11, 12, 10, 0, 0),
        )
    with pytest.raises(ValidationError):
        attendance.update_session(
            sid,
            start=datetime(2026, 11, 12, 10, 0, 0),
            end=datetime(2026, 11, 12, 10, 0, 0),
        )

    # Microseconds not 0
    with pytest.raises(ValidationError):
        attendance.update_session(
            sid,
            start=datetime(2026, 11, 12, 10, 0, 0, 500),
            end=datetime(2026, 11, 12, 12, 0, 0),
        )
    with pytest.raises(ValidationError):
        attendance.update_session(
            sid,
            start=datetime(2026, 11, 12, 10, 0, 0),
            end=datetime(2026, 11, 12, 12, 0, 0, 500),
        )

    # End in future
    with pytest.raises(ValidationError, match="session ends in the future"):
        attendance.update_session(
            sid,
            start=datetime(2026, 11, 12, 10, 0, 0),
            end=datetime(2026, 11, 12, 19, 0, 0),
        )


def test_update_session_overlap_with_another_session_rejected(
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    e1 = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
    )
    e2 = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(14, 0),
        end_clock=time(16, 0),
    )
    assert e1.session.id is not None and e2.session.id is not None

    with pytest.raises(SessionOverlapError):
        attendance.update_session(
            e2.session.id,
            start=datetime(2026, 11, 12, 11, 0, 0),
            end=datetime(2026, 11, 12, 15, 0, 0),
        )


def test_update_locked_session_raises_record_locked(
    conn: sqlite3.Connection,
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    entry = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
    )
    assert entry.session.id is not None
    lock_session(conn, worker.id, entry.session.id)

    with pytest.raises(RecordLockedError):
        attendance.update_session(
            entry.session.id,
            start=datetime(2026, 11, 12, 9, 0, 0),
            end=datetime(2026, 11, 12, 11, 0, 0),
        )


def test_delete_session_unlocked_and_locked(
    conn: sqlite3.Connection,
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    entry = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
    )
    assert entry.session.id is not None
    sid = entry.session.id

    attendance.delete_session(sid)
    assert attendance.list_sessions(worker.id) == []

    # Deleting missing raises RecordNotFoundError
    with pytest.raises(RecordNotFoundError):
        attendance.delete_session(sid)

    # Deleting locked raises RecordLockedError
    entry_locked = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(13, 0),
        end_clock=time(15, 0),
    )
    assert entry_locked.session.id is not None
    lock_session(conn, worker.id, entry_locked.session.id)

    with pytest.raises(RecordLockedError):
        attendance.delete_session(entry_locked.session.id)


def test_reads_filtering_and_unsettled_minutes(
    conn: sqlite3.Connection,
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
) -> None:
    w1 = make_worker(name="عامل 1")
    w2 = make_worker(name="عامل 2")
    assert w1.id is not None and w2.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    # w1 sessions:
    e1 = attendance.add_manual(
        w1.id,
        day=date(2026, 11, 10),
        start_clock=time(8, 0),
        end_clock=time(10, 0),
    )
    e2 = attendance.add_manual(
        w1.id,
        day=date(2026, 11, 11),
        start_clock=time(8, 0),
        end_clock=time(10, 0),
    )
    # Lock e1
    assert e1.session.id is not None
    lock_session(conn, w1.id, e1.session.id)

    # w2 has an open session
    s_open = attendance.start_work(w2.id)

    # list_open_sessions
    open_sessions = attendance.list_open_sessions()
    assert len(open_sessions) == 1
    assert open_sessions[0].id == s_open.id

    # list_sessions with date filters and unsettled_only
    all_w1 = attendance.list_sessions(w1.id)
    assert len(all_w1) == 2

    unsettled_w1 = attendance.list_sessions(w1.id, unsettled_only=True)
    assert len(unsettled_w1) == 1
    assert unsettled_w1[0].id == e2.session.id

    filtered_date = attendance.list_sessions(
        w1.id,
        from_date=date(2026, 11, 11),
        to_date=date(2026, 11, 11),
    )
    assert len(filtered_date) == 1
    assert filtered_date[0].id == e2.session.id

    # unsettled_minutes excludes locked sessions and counts open session up to now
    assert attendance.unsettled_minutes(w1.id) == 120  # only e2 (2 hours)
    assert attendance.unsettled_minutes(w2.id) == 0  # started at 18:00, clock is 18:00
    clock.advance(minutes=45)
    assert attendance.unsettled_minutes(w2.id) == 45

    # Unknown worker unsettled_minutes returns 0
    assert attendance.unsettled_minutes(999) == 0


@pytest.mark.parametrize(
    "operation",
    [
        lambda a: a.get_open_session(999),
        lambda a: a.list_open_sessions(),
        lambda a: a.list_sessions(999),
        lambda a: a.unsettled_minutes(999),
    ],
)
def test_transaction_hygiene_success(
    conn: sqlite3.Connection,
    attendance: AttendanceService,
    operation: Callable[[AttendanceService], object],
) -> None:
    operation(attendance)
    assert not conn.in_transaction


@pytest.mark.parametrize(
    "operation, expected_error",
    [
        (lambda a: a.start_work(999), RecordNotFoundError),
        (lambda a: a.stop_work(999), RecordNotFoundError),
        (
            lambda a: a.add_manual(
                999,
                day=date(2026, 11, 12),
                start_clock=time(9, 0),
                end_clock=time(10, 0),
            ),
            RecordNotFoundError,
        ),
        (
            lambda a: a.update_session(
                999,
                start=datetime(2026, 11, 12, 9, 0, 0),
                end=datetime(2026, 11, 12, 10, 0, 0),
            ),
            RecordNotFoundError,
        ),
        (lambda a: a.delete_session(999), RecordNotFoundError),
    ],
)
def test_transaction_hygiene_failure(
    conn: sqlite3.Connection,
    attendance: AttendanceService,
    operation: Callable[[AttendanceService], object],
    expected_error: type[Exception],
) -> None:
    with pytest.raises(expected_error):
        operation(attendance)
    assert not conn.in_transaction


def test_rollback_on_session_update_error(
    conn: sqlite3.Connection,
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 18, 0, 0)
    entry = attendance.add_manual(
        worker.id,
        day=date(2026, 11, 12),
        start_clock=time(10, 0),
        end_clock=time(12, 0),
        note="أصلية",
    )
    assert entry.session.id is not None
    sid = entry.session.id

    def fake_update(self: SessionRepository, s: Session) -> Session:
        raise DatabaseError("simulated database update failure")

    monkeypatch.setattr(SessionRepository, "update", fake_update)

    with pytest.raises(DatabaseError, match="simulated database update failure"):
        attendance.update_session(
            sid,
            start=datetime(2026, 11, 12, 10, 0, 0),
            end=datetime(2026, 11, 12, 13, 0, 0),
            note="معدلة",
        )

    assert not conn.in_transaction
    sessions = SessionRepository(conn)
    reloaded = sessions.get(sid)
    assert reloaded is not None
    assert reloaded.end == datetime(2026, 11, 12, 12, 0, 0)
    assert reloaded.note == "أصلية"


def test_rollback_on_stop_work_error(
    conn: sqlite3.Connection,
    attendance: AttendanceService,
    clock: FakeClock,
    make_worker: Callable[..., Worker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = make_worker()
    assert worker.id is not None

    clock.now = datetime(2026, 11, 12, 12, 0, 0)
    open_s = attendance.start_work(worker.id)
    assert open_s.id is not None

    def fake_update(self: SessionRepository, s: Session) -> Session:
        raise DatabaseError("simulated database update failure")

    monkeypatch.setattr(SessionRepository, "update", fake_update)

    clock.advance(minutes=60)
    with pytest.raises(DatabaseError, match="simulated database update failure"):
        attendance.stop_work(worker.id)

    assert not conn.in_transaction
    sessions = SessionRepository(conn)
    reloaded = sessions.get(open_s.id)
    assert reloaded is not None
    assert reloaded.is_open
