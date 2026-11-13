import sqlite3
from collections.abc import Generator

import pytest

from worktime.data import open_database


@pytest.fixture
def conn() -> Generator[sqlite3.Connection, None, None]:
    connection = open_database(":memory:")
    try:
        yield connection
    finally:
        connection.close()


def insert_worker(
    conn: sqlite3.Connection,
    name: str = "Worker 1",
    phone: str = "",
    note: str = "",
    archived: int = 0,
) -> int:
    cursor = conn.execute(
        "INSERT INTO workers (name, phone, note, archived) VALUES (?, ?, ?, ?)",
        (name, phone, note, archived),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def insert_settlement(
    conn: sqlite3.Connection,
    worker_id: int,
    settled_on: str = "2026-11-06",
    total_minutes: int = 60,
    wage: int = 50000,
    advances_total: int = 0,
    prepayments_total: int = 0,
    deductions_total: int = 0,
    previous_balance: int = 0,
    payable: int = 50000,
    paid: int = 50000,
    new_balance: int = 0,
    note: str = "",
) -> int:
    cursor = conn.execute(
        """INSERT INTO settlements (
            worker_id, settled_on, total_minutes, wage,
            advances_total, prepayments_total, deductions_total,
            previous_balance, payable, paid, new_balance, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            worker_id,
            settled_on,
            total_minutes,
            wage,
            advances_total,
            prepayments_total,
            deductions_total,
            previous_balance,
            payable,
            paid,
            new_balance,
            note,
        ),
    )
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def insert_session(
    conn: sqlite3.Connection,
    worker_id: int,
    start_at: str = "2026-11-06T09:00:00",
    end_at: str | None = "2026-11-06T17:00:00",
    note: str = "",
    settlement_id: int | None = None,
) -> int:
    cursor = conn.execute(
        ("INSERT INTO sessions (worker_id, start_at, end_at, note) VALUES (?, ?, ?, ?)"),
        (worker_id, start_at, end_at, note),
    )
    assert cursor.lastrowid is not None
    sess_id = cursor.lastrowid
    if settlement_id is not None:
        conn.execute(
            "UPDATE sessions SET settlement_id = ? WHERE id = ?",
            (settlement_id, sess_id),
        )
    return sess_id


def insert_money_transaction(
    conn: sqlite3.Connection,
    worker_id: int,
    kind: str = "advance",
    amount: int = 1000,
    occurred_on: str = "2026-11-06",
    note: str = "",
    settlement_id: int | None = None,
) -> int:
    cursor = conn.execute(
        (
            "INSERT INTO money_transactions "
            "(worker_id, kind, amount, occurred_on, note) "
            "VALUES (?, ?, ?, ?, ?)"
        ),
        (worker_id, kind, amount, occurred_on, note),
    )
    assert cursor.lastrowid is not None
    tx_id = cursor.lastrowid
    if settlement_id is not None:
        conn.execute(
            "UPDATE money_transactions SET settlement_id = ? WHERE id = ?",
            (settlement_id, tx_id),
        )
    return tx_id
