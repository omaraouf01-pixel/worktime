import sqlite3
from datetime import UTC, date, datetime

import pytest

from tests.data.conftest import insert_settlement, insert_worker
from worktime.data import (
    DatabaseError,
    OpenSessionExistsError,
    RecordNotFoundError,
    SessionRepository,
)
from worktime.domain import RecordLockedError, Session


def test_add_open_and_closed_sessions(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="Worker A")
    repo = SessionRepository(conn)

    open_sess = Session(
        worker_id=worker_id,
        start=datetime(2026, 11, 6, 8, 30, 0),
        note="صباحي",
    )
    saved_open = repo.add(open_sess)
    assert saved_open.id is not None
    assert saved_open.worker_id == worker_id
    assert saved_open.start == datetime(2026, 11, 6, 8, 30, 0)
    assert saved_open.end is None
    assert saved_open.note == "صباحي"
    assert saved_open.settlement_id is None

    loaded_open = repo.get(saved_open.id)
    assert loaded_open == saved_open

    worker_b = insert_worker(conn, name="Worker B")
    closed_sess = Session(
        worker_id=worker_b,
        start=datetime(2026, 11, 6, 9, 0, 0),
        end=datetime(2026, 11, 6, 17, 0, 0),
        note="يوم كامل",
    )
    saved_closed = repo.add(closed_sess)
    assert saved_closed.id is not None
    assert saved_closed.end == datetime(2026, 11, 6, 17, 0, 0)

    loaded_closed = repo.get(saved_closed.id)
    assert loaded_closed == saved_closed


def test_add_session_with_existing_id_raises_error(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    repo = SessionRepository(conn)
    sess = Session(
        id=42,
        worker_id=worker_id,
        start=datetime(2026, 11, 6, 8, 0, 0),
    )
    with pytest.raises(DatabaseError, match="id"):
        repo.add(sess)


def test_add_session_with_settlement_id_raises_database_error(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    repo = SessionRepository(conn)
    sess = Session(
        worker_id=worker_id,
        start=datetime(2026, 11, 6, 8, 0, 0),
        end=datetime(2026, 11, 6, 12, 0, 0),
        settlement_id=settlement_id,
    )
    with pytest.raises(DatabaseError, match="new records cannot carry a settlement"):
        repo.add(sess)
    count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    assert count == 0


def test_second_open_session_rejected_for_same_worker(
    conn: sqlite3.Connection,
) -> None:
    worker1 = insert_worker(conn, name="Worker 1")
    worker2 = insert_worker(conn, name="Worker 2")
    repo = SessionRepository(conn)

    repo.add(Session(worker_id=worker1, start=datetime(2026, 11, 6, 8, 0, 0)))

    with pytest.raises(OpenSessionExistsError):
        repo.add(Session(worker_id=worker1, start=datetime(2026, 11, 6, 10, 0, 0)))

    # Open session for another worker is fine
    s2 = repo.add(Session(worker_id=worker2, start=datetime(2026, 11, 6, 8, 0, 0)))
    assert s2.id is not None

    # Closed session + open session for worker 2 is fine
    closed_w2 = repo.add(
        Session(
            worker_id=worker2,
            start=datetime(2026, 11, 5, 8, 0, 0),
            end=datetime(2026, 11, 5, 12, 0, 0),
        )
    )
    assert closed_w2.id is not None


def test_add_session_for_unknown_worker_raises_error(
    conn: sqlite3.Connection,
) -> None:
    repo = SessionRepository(conn)
    sess = Session(worker_id=999, start=datetime(2026, 11, 6, 8, 0, 0))
    with pytest.raises(RecordNotFoundError, match="worker not found"):
        repo.add(sess)


def test_invalid_datetimes_rejected_with_database_error(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    repo = SessionRepository(conn)

    # microsecond != 0
    micro_sess = Session(
        worker_id=worker_id,
        start=datetime(2026, 11, 6, 8, 0, 0, 123456),
    )
    with pytest.raises(DatabaseError):
        repo.add(micro_sess)

    # timezone-aware datetime: bypass domain validation to test data layer defense
    aware_dt = datetime(2026, 11, 6, 8, 0, 0, tzinfo=UTC)
    raw_sess = Session(worker_id=worker_id, start=datetime(2026, 11, 6, 8, 0, 0))
    object.__setattr__(raw_sess, "start", aware_dt)
    with pytest.raises(DatabaseError):
        repo.add(raw_sess)

    # Verify nothing was written to sessions table
    cursor = conn.execute("SELECT count(*) FROM sessions")
    assert cursor.fetchone()[0] == 0


def test_get_open_and_list_open(conn: sqlite3.Connection) -> None:
    w1 = insert_worker(conn, name="Worker 1")
    w2 = insert_worker(conn, name="Worker 2")
    w3 = insert_worker(conn, name="Worker 3")
    repo = SessionRepository(conn)

    assert repo.get_open(w1) is None
    assert repo.list_open() == []

    s_w2 = repo.add(Session(worker_id=w2, start=datetime(2026, 11, 6, 10, 0, 0)))
    s_w1 = repo.add(Session(worker_id=w1, start=datetime(2026, 11, 6, 8, 0, 0)))
    repo.add(
        Session(
            worker_id=w3,
            start=datetime(2026, 11, 6, 7, 0, 0),
            end=datetime(2026, 11, 6, 12, 0, 0),
        )
    )

    open_w1 = repo.get_open(w1)
    assert open_w1 is not None
    assert open_w1.id == s_w1.id

    open_sessions = repo.list_open()
    assert [s.id for s in open_sessions] == [s_w1.id, s_w2.id]


def test_list_for_worker_filtering_and_bounds(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    repo = SessionRepository(conn)

    # 1. Day before from_date: ends before from_date start
    repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 4, 23, 59, 59),
            end=datetime(2026, 11, 5, 2, 0, 0),
        )
    )
    # 2. Exactly at start of from_date (2026-11-05T00:00:00)
    s_from_start = repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 5, 0, 0, 0),
            end=datetime(2026, 11, 5, 8, 0, 0),
        )
    )
    # 3. Middle of range (2026-11-05 afternoon)
    s_mid = repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 5, 14, 0, 0),
            end=datetime(2026, 11, 5, 18, 0, 0),
        )
    )
    # 4. End of to_date (2026-11-06T23:59:00)
    s_to_end = repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 6, 23, 59, 0),
        )
    )
    # 5. Day after to_date (2026-11-07T00:00:00)
    repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 7, 0, 0, 0),
            end=datetime(2026, 11, 7, 5, 0, 0),
        )
    )

    # Lock session 2 with a settlement
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    conn.execute(
        "UPDATE sessions SET settlement_id = ? WHERE id = ?",
        (settlement_id, s_from_start.id),
    )

    # Filter with bounds from 2026-11-05 to 2026-11-06
    in_range = repo.list_for_worker(
        worker_id,
        from_date=date(2026, 11, 5),
        to_date=date(2026, 11, 6),
    )
    assert [s.id for s in in_range] == [s_from_start.id, s_mid.id, s_to_end.id]

    # unsettled_only hides s_from_start
    unsettled = repo.list_for_worker(
        worker_id,
        from_date=date(2026, 11, 5),
        to_date=date(2026, 11, 6),
        unsettled_only=True,
    )
    assert [s.id for s in unsettled] == [s_mid.id, s_to_end.id]

    # from_date > to_date raises DatabaseError
    with pytest.raises(DatabaseError, match="from_date"):
        repo.list_for_worker(
            worker_id,
            from_date=date(2026, 11, 7),
            to_date=date(2026, 11, 6),
        )

    # unknown worker returns []
    assert repo.list_for_worker(9999) == []

    # passing datetime as date bound raises DatabaseError
    with pytest.raises(DatabaseError):
        repo.list_for_worker(
            worker_id,
            from_date=datetime(2026, 11, 5, 0, 0, 0),  # type: ignore[arg-type]
        )
    with pytest.raises(DatabaseError):
        repo.list_for_worker(
            worker_id,
            to_date=datetime(2026, 11, 6, 23, 59, 59),  # type: ignore[arg-type]
        )

    # Only from_date: includes s_from_start, s_mid, s_to_end, s_after
    only_from = repo.list_for_worker(worker_id, from_date=date(2026, 11, 6))
    assert [s.id for s in only_from] == [s_to_end.id, repo.list_for_worker(worker_id)[-1].id]

    # Only to_date: includes s_before, s_from_start, s_mid
    only_to = repo.list_for_worker(worker_id, to_date=date(2026, 11, 5))
    all_sess = repo.list_for_worker(worker_id)
    assert [s.id for s in only_to] == [all_sess[0].id, s_from_start.id, s_mid.id]


def test_update_session(conn: sqlite3.Connection) -> None:
    w1 = insert_worker(conn, name="Worker 1")
    w2 = insert_worker(conn, name="Worker 2")
    repo = SessionRepository(conn)

    saved = repo.add(
        Session(
            worker_id=w1,
            start=datetime(2026, 11, 6, 8, 0, 0),
            note="Initial",
        )
    )
    assert saved.id is not None

    # Normal update: close session, change note
    updated = repo.update(
        Session(
            id=saved.id,
            worker_id=saved.worker_id,
            start=datetime(2026, 11, 6, 8, 30, 0),
            end=datetime(2026, 11, 6, 16, 30, 0),
            note="Updated",
        )
    )
    assert updated.start == datetime(2026, 11, 6, 8, 30, 0)
    assert updated.end == datetime(2026, 11, 6, 16, 30, 0)
    assert updated.note == "Updated"

    # Attempt to change worker_id or settlement_id:
    # Repository ignores them and updates only start, end, note.
    fake_settlement_id = 42
    re_updated = repo.update(
        Session(
            id=saved.id,
            worker_id=w2,
            start=datetime(2026, 11, 6, 8, 30, 0),
            end=datetime(2026, 11, 6, 16, 30, 0),
            note="Updated again",
            settlement_id=fake_settlement_id,
        )
    )
    assert re_updated.worker_id == w1
    assert re_updated.settlement_id is None

    # Update without id raises DatabaseError
    with pytest.raises(DatabaseError, match="id"):
        repo.update(Session(worker_id=w1, start=datetime(2026, 11, 6, 8, 0, 0)))

    # Update missing id raises RecordNotFoundError
    with pytest.raises(RecordNotFoundError):
        repo.update(
            Session(
                id=999,
                worker_id=w1,
                start=datetime(2026, 11, 6, 8, 0, 0),
            )
        )


def test_update_locked_session_raises_record_locked_error(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    repo = SessionRepository(conn)
    sess = repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 6, 8, 0, 0),
            end=datetime(2026, 11, 6, 12, 0, 0),
        )
    )
    assert sess.id is not None
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    conn.execute(
        "UPDATE sessions SET settlement_id = ? WHERE id = ?",
        (settlement_id, sess.id),
    )

    with pytest.raises(RecordLockedError):
        repo.update(
            Session(
                id=sess.id,
                worker_id=worker_id,
                start=datetime(2026, 11, 6, 9, 0, 0),
                end=datetime(2026, 11, 6, 13, 0, 0),
            )
        )


def test_reopening_session_when_another_is_open_raises_conflict(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    repo = SessionRepository(conn)

    closed = repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 5, 8, 0, 0),
            end=datetime(2026, 11, 5, 12, 0, 0),
        )
    )
    assert closed.id is not None
    repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 6, 8, 0, 0),
        )
    )

    # Attempt to reopen closed session (end=None) while open session exists
    with pytest.raises(OpenSessionExistsError):
        repo.update(
            Session(
                id=closed.id,
                worker_id=worker_id,
                start=closed.start,
                end=None,
            )
        )


def test_delete_session(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    repo = SessionRepository(conn)

    sess = repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 6, 8, 0, 0),
            end=datetime(2026, 11, 6, 12, 0, 0),
        )
    )
    assert sess.id is not None

    # Delete missing id
    with pytest.raises(RecordNotFoundError):
        repo.delete(999)

    # Delete locked session
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    conn.execute(
        "UPDATE sessions SET settlement_id = ? WHERE id = ?",
        (settlement_id, sess.id),
    )
    with pytest.raises(RecordLockedError):
        repo.delete(sess.id)

    # Row still exists
    assert repo.get(sess.id) is not None

    # Delete unlocked session
    unlocked = repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 7, 8, 0, 0),
        )
    )
    assert unlocked.id is not None
    repo.delete(unlocked.id)
    assert repo.get(unlocked.id) is None
