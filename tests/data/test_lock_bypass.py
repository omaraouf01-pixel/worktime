"""Tests for database lock bypass prevention and recursive trigger enforcement."""

import sqlite3
from typing import Any

import pytest

from worktime.data.database import connect, migrate, open_database


def _table_snapshot(conn: sqlite3.Connection) -> dict[str, list[tuple[Any, ...]]]:
    tables = ("workers", "settlements", "sessions", "money_transactions")
    result: dict[str, list[tuple[Any, ...]]] = {}
    for t in tables:
        rows = conn.execute("SELECT * FROM " + t + " ORDER BY id").fetchall()
        result[t] = [tuple(r) for r in rows]
    return result


def _setup_test_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO workers (id, name, phone, note, archived) VALUES (1, 'Worker One', '', '', 0)"
    )
    conn.execute(
        "INSERT INTO workers (id, name, phone, note, archived) VALUES (2, 'Worker Two', '', '', 0)"
    )
    conn.execute(
        """INSERT INTO settlements (
            id, worker_id, settled_on, total_minutes, wage,
            advances_total, prepayments_total, deductions_total,
            previous_balance, payable, paid, new_balance, note
        ) VALUES (1, 1, '2026-11-06', 480, 50000, 1000, 0, 0, 0, 49000, 49000, 0, '')"""
    )
    conn.execute(
        "INSERT INTO sessions (id, worker_id, start_at, end_at, note) "
        "VALUES (1, 1, '2026-11-06T09:00:00', '2026-11-06T17:00:00', 'locked')"
    )
    conn.execute("UPDATE sessions SET settlement_id = 1 WHERE id = 1")
    conn.execute(
        "INSERT INTO sessions (id, worker_id, start_at, end_at, note) "
        "VALUES (2, 1, '2026-11-07T09:00:00', '2026-11-07T17:00:00', 'unlocked')"
    )
    conn.execute(
        "INSERT INTO money_transactions (id, worker_id, kind, amount, occurred_on, note) "
        "VALUES (1, 1, 'advance', 1000, '2026-11-06', 'locked')"
    )
    conn.execute("UPDATE money_transactions SET settlement_id = 1 WHERE id = 1")
    conn.execute(
        "INSERT INTO money_transactions (id, worker_id, kind, amount, occurred_on, note) "
        "VALUES (2, 1, 'advance', 2000, '2026-11-07', 'unlocked')"
    )


@pytest.fixture(params=["managed", "raw"])
def bypass_conn(request: pytest.FixtureRequest) -> sqlite3.Connection:
    if request.param == "managed":
        connection = open_database(":memory:")
    else:
        connection = sqlite3.connect(":memory:")
        migrate(connection)
    _setup_test_db(connection)
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def managed_conn() -> sqlite3.Connection:
    connection = open_database(":memory:")
    _setup_test_db(connection)
    try:
        yield connection
    finally:
        connection.close()


def _assert_fails_and_leaves_tables_unchanged(
    conn: sqlite3.Connection,
    statement: str,
    params: tuple[Any, ...],
    expected_message: str,
) -> None:
    before = _table_snapshot(conn)
    with pytest.raises(sqlite3.IntegrityError) as exc_info:
        conn.execute(statement, params)
    assert expected_message in str(exc_info.value)
    after = _table_snapshot(conn)
    assert before == after


# -----------------------------------------------------------------------------
# B.1 Replacement and upsert bypass tests on both connection kinds
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "statement", "params", "expected_msg"),
    [
        (
            "workers",
            (
                "INSERT OR REPLACE INTO workers (id, name, phone, note, archived) "
                "VALUES (1, 'Hacked', '', '', 0)"
            ),
            (),
            "record already exists",
        ),
        (
            "workers",
            (
                "REPLACE INTO workers (id, name, phone, note, archived) "
                "VALUES (1, 'Hacked', '', '', 0)"
            ),
            (),
            "record already exists",
        ),
        (
            "workers",
            "INSERT INTO workers (id, name, phone, note, archived) VALUES (1, 'Hacked', '', '', 0) "
            "ON CONFLICT(id) DO UPDATE SET name = 'Hacked'",
            (),
            "record already exists",
        ),
        (
            "sessions",
            "INSERT OR REPLACE INTO sessions (id, worker_id, start_at, end_at, note) "
            "VALUES (1, 1, '2026-11-06T10:00:00', '2026-11-06T18:00:00', 'hacked')",
            (),
            "record already exists",
        ),
        (
            "sessions",
            "REPLACE INTO sessions (id, worker_id, start_at, end_at, note) "
            "VALUES (1, 1, '2026-11-06T10:00:00', '2026-11-06T18:00:00', 'hacked')",
            (),
            "record already exists",
        ),
        (
            "sessions",
            "INSERT INTO sessions (id, worker_id, start_at, end_at, note) "
            "VALUES (1, 1, '2026-11-06T10:00:00', '2026-11-06T18:00:00', 'hacked') "
            "ON CONFLICT(id) DO UPDATE SET note = 'hacked'",
            (),
            "record already exists",
        ),
        (
            "money_transactions",
            (
                "INSERT OR REPLACE INTO money_transactions "
                "(id, worker_id, kind, amount, occurred_on, note) "
                "VALUES (1, 1, 'advance', 9999, '2026-11-06', 'hacked')"
            ),
            (),
            "record already exists",
        ),
        (
            "money_transactions",
            (
                "REPLACE INTO money_transactions "
                "(id, worker_id, kind, amount, occurred_on, note) "
                "VALUES (1, 1, 'advance', 9999, '2026-11-06', 'hacked')"
            ),
            (),
            "record already exists",
        ),
        (
            "money_transactions",
            "INSERT INTO money_transactions (id, worker_id, kind, amount, occurred_on, note) "
            "VALUES (1, 1, 'advance', 9999, '2026-11-06', 'hacked') "
            "ON CONFLICT(id) DO UPDATE SET amount = 9999",
            (),
            "record already exists",
        ),
        (
            "settlements",
            (
                "INSERT OR REPLACE INTO settlements (id, worker_id, settled_on, total_minutes, "
                "wage, advances_total, prepayments_total, deductions_total, previous_balance, "
                "payable, paid, new_balance, note) VALUES (1, 1, '2026-11-06', 480, 50000, "
                "1000, 0, 0, 0, 49000, 49000, 0, 'hacked')"
            ),
            (),
            "settlement is immutable",
        ),
        (
            "settlements",
            (
                "REPLACE INTO settlements (id, worker_id, settled_on, total_minutes, wage, "
                "advances_total, prepayments_total, deductions_total, previous_balance, "
                "payable, paid, new_balance, note) VALUES (1, 1, '2026-11-06', 480, 50000, "
                "1000, 0, 0, 0, 49000, 49000, 0, 'hacked')"
            ),
            (),
            "settlement is immutable",
        ),
        (
            "settlements",
            (
                "INSERT INTO settlements (id, worker_id, settled_on, total_minutes, wage, "
                "advances_total, prepayments_total, deductions_total, previous_balance, "
                "payable, paid, new_balance, note) VALUES (1, 1, '2026-11-06', 480, 50000, "
                "1000, 0, 0, 0, 49000, 49000, 0, 'hacked') "
                "ON CONFLICT(id) DO UPDATE SET note = 'hacked'"
            ),
            (),
            "settlement is immutable",
        ),
    ],
)
def test_b1_replace_and_upsert_on_existing_id_rejected(
    bypass_conn: sqlite3.Connection,
    table: str,
    statement: str,
    params: tuple[Any, ...],
    expected_msg: str,
) -> None:
    _assert_fails_and_leaves_tables_unchanged(bypass_conn, statement, params, expected_msg)


# -----------------------------------------------------------------------------
# B.2 Recursive triggers: UPDATE OR REPLACE and active worker name REPLACE
# -----------------------------------------------------------------------------


def test_b2_update_or_replace_locked_session_rejected(managed_conn: sqlite3.Connection) -> None:
    _assert_fails_and_leaves_tables_unchanged(
        managed_conn,
        "UPDATE OR REPLACE sessions SET id = 1 WHERE id = 2",
        (),
        "record locked",
    )


def test_b2_update_or_replace_locked_transaction_rejected(managed_conn: sqlite3.Connection) -> None:
    _assert_fails_and_leaves_tables_unchanged(
        managed_conn,
        "UPDATE OR REPLACE money_transactions SET id = 1 WHERE id = 2",
        (),
        "record locked",
    )


def test_b2_insert_or_replace_worker_active_name_rejected(managed_conn: sqlite3.Connection) -> None:
    _assert_fails_and_leaves_tables_unchanged(
        managed_conn,
        (
            "INSERT OR REPLACE INTO workers (name, phone, note, archived) "
            "VALUES ('Worker One', '999', 'replacement', 0)"
        ),
        (),
        "workers are archived, not deleted",
    )
    row = managed_conn.execute("SELECT name, phone FROM workers WHERE id = 1").fetchone()
    assert row is not None
    assert row[0] == "Worker One"
    assert row[1] == ""


# -----------------------------------------------------------------------------
# B.3 Pre-locked inserts on both connection kinds
# -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "params"),
    [
        (
            "INSERT INTO sessions (worker_id, start_at, end_at, settlement_id) VALUES (?, ?, ?, ?)",
            (1, "2026-11-08T09:00:00", None, 1),
        ),
        (
            "INSERT INTO sessions (worker_id, start_at, end_at, settlement_id) VALUES (?, ?, ?, ?)",
            (1, "2026-11-08T09:00:00", "2026-11-08T17:00:00", 1),
        ),
        (
            (
                "INSERT INTO money_transactions "
                "(worker_id, kind, amount, occurred_on, settlement_id) VALUES (?, ?, ?, ?, ?)"
            ),
            (1, "advance", 500, "2026-11-08", 1),
        ),
        (
            "INSERT INTO sessions (worker_id, start_at, end_at, settlement_id) VALUES (?, ?, ?, ?)",
            (2, "2026-11-08T09:00:00", "2026-11-08T17:00:00", 1),
        ),
        (
            (
                "INSERT INTO money_transactions "
                "(worker_id, kind, amount, occurred_on, settlement_id) VALUES (?, ?, ?, ?, ?)"
            ),
            (2, "advance", 500, "2026-11-08", 1),
        ),
    ],
)
def test_b3_prelocked_inserts_rejected(
    bypass_conn: sqlite3.Connection,
    statement: str,
    params: tuple[Any, ...],
) -> None:
    _assert_fails_and_leaves_tables_unchanged(
        bypass_conn,
        statement,
        params,
        "new records cannot be pre-locked",
    )


# -----------------------------------------------------------------------------
# B.4 Positive controls (must still succeed)
# -----------------------------------------------------------------------------


def test_b4_positive_controls(bypass_conn: sqlite3.Connection) -> None:
    # Plain INSERT without an id
    c_w = bypass_conn.execute("INSERT INTO workers (name) VALUES ('Worker Three')")
    w3_id = c_w.lastrowid
    assert w3_id is not None

    c_s = bypass_conn.execute(
        (
            "INSERT INTO sessions (worker_id, start_at, end_at) "
            "VALUES (?, '2026-11-09T08:00:00', '2026-11-09T12:00:00')"
        ),
        (w3_id,),
    )
    s3_id = c_s.lastrowid
    assert s3_id is not None

    c_t = bypass_conn.execute(
        (
            "INSERT INTO money_transactions (worker_id, kind, amount, occurred_on) "
            "VALUES (?, 'advance', 500, '2026-11-09')"
        ),
        (w3_id,),
    )
    t3_id = c_t.lastrowid
    assert t3_id is not None

    c_set = bypass_conn.execute(
        """INSERT INTO settlements (
            worker_id, settled_on, total_minutes, wage,
            advances_total, prepayments_total, deductions_total,
            previous_balance, payable, paid, new_balance, note
        ) VALUES (?, '2026-11-09', 240, 20000, 500, 0, 0, 0, 19500, 19500, 0, '')""",
        (w3_id,),
    )
    set3_id = c_set.lastrowid
    assert set3_id is not None

    # INSERT with an explicit unused id
    bypass_conn.execute("INSERT INTO workers (id, name) VALUES (100, 'Worker Hundred')")
    bypass_conn.execute(
        "INSERT INTO sessions (id, worker_id, start_at, end_at) "
        "VALUES (100, 100, '2026-11-10T08:00:00', '2026-11-10T12:00:00')"
    )
    bypass_conn.execute(
        "INSERT INTO money_transactions (id, worker_id, kind, amount, occurred_on) "
        "VALUES (100, 100, 'advance', 1000, '2026-11-10')"
    )
    bypass_conn.execute(
        """INSERT INTO settlements (
            id, worker_id, settled_on, total_minutes, wage,
            advances_total, prepayments_total, deductions_total,
            previous_balance, payable, paid, new_balance, note
        ) VALUES (100, 100, '2026-11-10', 240, 20000, 1000, 0, 0, 0, 19000, 19000, 0, '')"""
    )

    # Linking an unlocked closed session and transaction to a
    # settlement of the same worker via UPDATE
    bypass_conn.execute("UPDATE sessions SET settlement_id = ? WHERE id = ?", (set3_id, s3_id))
    bypass_conn.execute(
        "UPDATE money_transactions SET settlement_id = ? WHERE id = ?", (set3_id, t3_id)
    )

    # Updating and deleting UNLOCKED rows
    bypass_conn.execute("UPDATE sessions SET note = 'unlocked note' WHERE id = 2")
    bypass_conn.execute("DELETE FROM sessions WHERE id = 2")

    bypass_conn.execute("UPDATE money_transactions SET note = 'unlocked note' WHERE id = 2")
    bypass_conn.execute("DELETE FROM money_transactions WHERE id = 2")


# -----------------------------------------------------------------------------
# B.5 Recursive triggers enabled on connect()
# -----------------------------------------------------------------------------


def test_b5_pragma_recursive_triggers_enabled() -> None:
    conn = connect(":memory:")
    try:
        cur = conn.execute("PRAGMA recursive_triggers")
        val = cur.fetchone()[0]
        assert val == 1
    finally:
        conn.close()
