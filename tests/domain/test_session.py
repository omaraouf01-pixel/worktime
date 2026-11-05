from datetime import UTC, datetime, timedelta, timezone

import pytest

from worktime.domain.errors import RecordLockedError, ValidationError
from worktime.domain.session import Session


def test_session_open_and_closed_valid() -> None:
    start_dt = datetime(2026, 11, 5, 8, 30)
    end_dt = datetime(2026, 11, 5, 12, 0)

    open_session = Session(worker_id=1, start=start_dt)
    assert open_session.is_open is True
    assert open_session.is_locked is False
    assert open_session.end is None

    closed_session = Session(
        worker_id=1,
        start=start_dt,
        end=end_dt,
        note="  Morning shift  ",
        id=10,
        settlement_id=2,
    )
    assert closed_session.is_open is False
    assert closed_session.is_locked is True
    assert closed_session.end == end_dt
    assert closed_session.note == "Morning shift"
    assert closed_session.id == 10
    assert closed_session.settlement_id == 2


@pytest.mark.parametrize(
    ("start_dt", "end_dt"),
    [
        (datetime(2026, 11, 5, 10, 0), datetime(2026, 11, 5, 10, 0)),
        (datetime(2026, 11, 5, 10, 0), datetime(2026, 11, 5, 9, 59)),
        (datetime(2026, 11, 5, 10, 0), datetime(2026, 11, 4, 10, 0)),
    ],
)
def test_session_end_not_after_start_rejected(start_dt: datetime, end_dt: datetime) -> None:
    with pytest.raises(ValidationError):
        Session(worker_id=1, start=start_dt, end=end_dt)


@pytest.mark.parametrize(
    "aware_dt",
    [
        datetime(2026, 11, 5, 8, 0, tzinfo=UTC),
        datetime(2026, 11, 5, 8, 0, tzinfo=timezone(timedelta(hours=1))),
    ],
)
def test_session_aware_datetime_rejected(aware_dt: datetime) -> None:
    naive_dt = datetime(2026, 11, 5, 10, 0)
    with pytest.raises(ValidationError):
        Session(worker_id=1, start=aware_dt)
    with pytest.raises(ValidationError):
        Session(worker_id=1, start=naive_dt, end=aware_dt)


@pytest.mark.parametrize("invalid_dt", ["2026-11-05 08:00:00", 123456789, None])
def test_session_non_datetime_start_rejected(invalid_dt: object) -> None:
    with pytest.raises(ValidationError):
        Session(worker_id=1, start=invalid_dt)  # type: ignore[arg-type]


@pytest.mark.parametrize("invalid_worker_id", [0, -1, True, False, "1", None])
def test_session_invalid_worker_id_rejected(invalid_worker_id: object) -> None:
    with pytest.raises(ValidationError):
        Session(worker_id=invalid_worker_id, start=datetime(2026, 11, 5, 8, 0))  # type: ignore[arg-type]


def test_session_close_happy_path() -> None:
    start_dt = datetime(2026, 11, 5, 8, 0)
    end_dt = datetime(2026, 11, 5, 12, 0)
    session = Session(worker_id=1, start=start_dt)
    closed = session.close(end_dt)

    assert session.is_open is True
    assert closed.is_open is False
    assert closed.end == end_dt
    assert closed.worker_id == 1


def test_session_close_already_closed_rejected() -> None:
    session = Session(
        worker_id=1,
        start=datetime(2026, 11, 5, 8, 0),
        end=datetime(2026, 11, 5, 12, 0),
    )
    with pytest.raises(ValidationError):
        session.close(datetime(2026, 11, 5, 13, 0))


@pytest.mark.parametrize(
    "invalid_end",
    [
        datetime(2026, 11, 5, 8, 0),
        datetime(2026, 11, 5, 7, 0),
    ],
)
def test_session_close_with_end_not_after_start_rejected(invalid_end: datetime) -> None:
    session = Session(worker_id=1, start=datetime(2026, 11, 5, 8, 0))
    with pytest.raises(ValidationError):
        session.close(invalid_end)


def test_session_close_on_locked_rejected() -> None:
    session = Session(
        worker_id=1,
        start=datetime(2026, 11, 5, 8, 0),
        settlement_id=4,
    )
    with pytest.raises(RecordLockedError):
        session.close(datetime(2026, 11, 5, 12, 0))


def test_session_with_settlement_on_closed_success() -> None:
    session = Session(
        worker_id=1,
        start=datetime(2026, 11, 5, 8, 0),
        end=datetime(2026, 11, 5, 12, 0),
    )
    locked = session.with_settlement(7)
    assert locked.settlement_id == 7
    assert locked.is_locked is True


def test_session_with_settlement_on_open_rejected() -> None:
    session = Session(worker_id=1, start=datetime(2026, 11, 5, 8, 0))
    with pytest.raises(ValidationError):
        session.with_settlement(1)


def test_session_with_settlement_already_locked_rejected() -> None:
    session = Session(
        worker_id=1,
        start=datetime(2026, 11, 5, 8, 0),
        end=datetime(2026, 11, 5, 12, 0),
        settlement_id=1,
    )
    with pytest.raises(RecordLockedError):
        session.with_settlement(2)


def test_session_ensure_editable() -> None:
    unlocked = Session(worker_id=1, start=datetime(2026, 11, 5, 8, 0))
    unlocked.ensure_editable()

    locked = Session(
        worker_id=1,
        start=datetime(2026, 11, 5, 8, 0),
        end=datetime(2026, 11, 5, 12, 0),
        settlement_id=3,
    )
    with pytest.raises(RecordLockedError):
        locked.ensure_editable()
