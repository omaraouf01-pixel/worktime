import sqlite3

import pytest

from tests.data.conftest import (
    insert_money_transaction,
    insert_session,
    insert_settlement,
    insert_worker,
)


def test_schema_objects_exist(conn: sqlite3.Connection) -> None:
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    expected_tables = {
        "workers",
        "settlements",
        "sessions",
        "money_transactions",
        "app_settings",
    }
    assert tables == expected_tables

    indexes = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }
    expected_indexes = {
        "ux_workers_active_name",
        "ix_settlements_worker",
        "ux_sessions_one_open",
        "ix_sessions_worker_start",
        "ix_sessions_settlement",
        "ix_money_worker_date",
        "ix_money_settlement",
    }
    assert indexes == expected_indexes

    triggers = {
        r[0]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall()
    }
    expected_triggers = {
        "trg_sessions_locked_update",
        "trg_sessions_locked_delete",
        "trg_money_locked_update",
        "trg_money_locked_delete",
        "trg_sessions_lock_needs_closed",
        "trg_sessions_lock_same_worker",
        "trg_money_lock_same_worker",
        "trg_settlements_immutable_update",
        "trg_settlements_immutable_delete",
        "trg_workers_no_delete",
        "trg_sessions_no_preset_lock",
        "trg_money_no_preset_lock",
        "trg_workers_no_replace",
        "trg_sessions_no_replace",
        "trg_money_no_replace",
        "trg_settlements_no_replace",
    }
    assert triggers == expected_triggers


@pytest.mark.parametrize(
    ("name", "phone", "note", "archived"),
    [
        ("", "", "", 0),
        ("   ", "", "", 0),
        (" Leading", "", "", 0),
        ("Trailing ", "", "", 0),
        ("  Both  ", "", "", 0),
        ("A" * 101, "", "", 0),
        ("Valid Name", "P" * 31, "", 0),
        ("Valid Name", "", "N" * 501, 0),
        ("Valid Name", "", "", 2),
        ("Valid Name", "", "", -1),
    ],
)
def test_worker_invalid_data_rejected(
    conn: sqlite3.Connection,
    name: str,
    phone: str,
    note: str,
    archived: int,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        insert_worker(conn, name=name, phone=phone, note=note, archived=archived)


def test_worker_arabic_name_accepted(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="محمد عمر")
    row = conn.execute("SELECT name FROM workers WHERE id = ?", (worker_id,)).fetchone()
    assert row is not None
    assert row["name"] == "محمد عمر"


def test_worker_duplicate_active_name_case_insensitive_rejected(conn: sqlite3.Connection) -> None:
    insert_worker(conn, name="Alice")
    with pytest.raises(sqlite3.IntegrityError):
        insert_worker(conn, name="alice")


def test_worker_same_name_allowed_when_one_archived(conn: sqlite3.Connection) -> None:
    w1 = insert_worker(conn, name="Bob", archived=1)
    w2 = insert_worker(conn, name="Bob", archived=0)
    assert w1 != w2


@pytest.mark.parametrize(
    ("start_at", "end_at", "invalid_worker"),
    [
        ("2026-11-06T10:00:00", "2026-11-06T10:00:00", False),
        ("2026-11-06T10:00:00", "2026-11-06T09:00:00", False),
        ("2026-11-06", "2026-11-06T12:00:00", False),
        ("2026-11-06 10:00:00", "2026-11-06 12:00:00", False),
        ("2026-11-06T10:00:00", "2026-11-06 12:00:00", False),
        ("2026-11-06T10:00:00", "2026-11-06T12:00:00", True),
    ],
)
def test_session_invalid_data_rejected(
    conn: sqlite3.Connection,
    start_at: str,
    end_at: str,
    invalid_worker: bool,
) -> None:
    real_worker_id = insert_worker(conn, name="WorkerSession")
    worker_id = 9999 if invalid_worker else real_worker_id
    with pytest.raises(sqlite3.IntegrityError):
        insert_session(conn, worker_id=worker_id, start_at=start_at, end_at=end_at)


def test_session_open_session_uniqueness_rules(conn: sqlite3.Connection) -> None:
    w1 = insert_worker(conn, name="Worker1")
    w2 = insert_worker(conn, name="Worker2")

    insert_session(conn, worker_id=w1, start_at="2026-11-06T08:00:00", end_at=None)

    with pytest.raises(sqlite3.IntegrityError):
        insert_session(conn, worker_id=w1, start_at="2026-11-06T10:00:00", end_at=None)

    insert_session(conn, worker_id=w2, start_at="2026-11-06T08:00:00", end_at=None)

    insert_session(
        conn,
        worker_id=w1,
        start_at="2026-11-05T08:00:00",
        end_at="2026-11-05T12:00:00",
    )


@pytest.mark.parametrize(
    ("kind", "amount", "occurred_on"),
    [
        ("other", 1000, "2026-11-06"),
        ("loan", 1000, "2026-11-06"),
        ("", 1000, "2026-11-06"),
        ("advance", 0, "2026-11-06"),
        ("advance", -5, "2026-11-06"),
        ("advance", 1000, "2026/11/06"),
        ("advance", 1000, "2026-1-1"),
        ("advance", 1000, "2026-11-06T10:00:00"),
    ],
)
def test_money_transaction_invalid_data_rejected(
    conn: sqlite3.Connection,
    kind: str,
    amount: int,
    occurred_on: str,
) -> None:
    worker_id = insert_worker(conn, name="WorkerMoney")
    with pytest.raises(sqlite3.IntegrityError):
        insert_money_transaction(
            conn,
            worker_id=worker_id,
            kind=kind,
            amount=amount,
            occurred_on=occurred_on,
        )


@pytest.mark.parametrize(
    (
        "total_minutes",
        "wage",
        "advances",
        "prepayments",
        "deductions",
        "previous",
        "payable",
        "paid",
        "new_balance",
    ),
    [
        (60, -1, 0, 0, 0, 0, -1, 0, -1),
        (60, 50000, 10000, 0, 0, 0, 35000, 35000, 0),
        (60, 50000, 0, 0, 0, 0, 50000, 50001, -1),
        (60, 10000, 20000, 0, 0, 0, -10000, 1000, -11000),
        (60, 50000, 0, 0, 0, 0, 50000, 20000, 25000),
    ],
)
def test_settlement_invalid_invariants_rejected(
    conn: sqlite3.Connection,
    total_minutes: int,
    wage: int,
    advances: int,
    prepayments: int,
    deductions: int,
    previous: int,
    payable: int,
    paid: int,
    new_balance: int,
) -> None:
    worker_id = insert_worker(conn, name="WorkerSettlementInvalid")
    with pytest.raises(sqlite3.IntegrityError):
        insert_settlement(
            conn,
            worker_id=worker_id,
            total_minutes=total_minutes,
            wage=wage,
            advances_total=advances,
            prepayments_total=prepayments,
            deductions_total=deductions,
            previous_balance=previous,
            payable=payable,
            paid=paid,
            new_balance=new_balance,
        )


def test_settlement_brief_examples_accepted(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="WorkerExamples")

    s1 = insert_settlement(
        conn,
        worker_id=worker_id,
        settled_on="2026-11-06",
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
    assert s1 > 0

    s2 = insert_settlement(
        conn,
        worker_id=worker_id,
        settled_on="2026-11-07",
        total_minutes=6000,
        wage=600000,
        advances_total=0,
        prepayments_total=0,
        deductions_total=0,
        previous_balance=-200000,
        payable=400000,
        paid=300000,
        new_balance=100000,
    )
    assert s2 > 0


def test_trigger_record_locked_sessions(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="WorkerLockedSession")
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    session_id = insert_session(
        conn,
        worker_id=worker_id,
        settlement_id=settlement_id,
    )

    with pytest.raises(sqlite3.IntegrityError, match="record locked"):
        conn.execute("UPDATE sessions SET note = ? WHERE id = ?", ("modified", session_id))

    with pytest.raises(sqlite3.IntegrityError, match="record locked"):
        conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def test_trigger_record_locked_money_transactions(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="WorkerLockedMoney")
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    tx_id = insert_money_transaction(
        conn,
        worker_id=worker_id,
        settlement_id=settlement_id,
    )

    with pytest.raises(sqlite3.IntegrityError, match="record locked"):
        conn.execute("UPDATE money_transactions SET amount = ? WHERE id = ?", (2000, tx_id))

    with pytest.raises(sqlite3.IntegrityError, match="record locked"):
        conn.execute("DELETE FROM money_transactions WHERE id = ?", (tx_id,))


def test_trigger_settlements_immutable(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="WorkerSettlementImmutable")
    settlement_id = insert_settlement(conn, worker_id=worker_id)

    with pytest.raises(sqlite3.IntegrityError, match="settlement is immutable"):
        conn.execute(
            "UPDATE settlements SET note = ? WHERE id = ?",
            ("new note", settlement_id),
        )

    with pytest.raises(sqlite3.IntegrityError, match="settlement is immutable"):
        conn.execute("DELETE FROM settlements WHERE id = ?", (settlement_id,))


def test_trigger_workers_no_delete(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="WorkerNoDelete")

    with pytest.raises(sqlite3.IntegrityError, match="workers are archived, not deleted"):
        conn.execute("DELETE FROM workers WHERE id = ?", (worker_id,))


def test_trigger_cannot_lock_open_session(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="WorkerOpenLock")
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    session_id = insert_session(conn, worker_id=worker_id, end_at=None)

    with pytest.raises(sqlite3.IntegrityError, match="cannot lock an open session"):
        conn.execute(
            "UPDATE sessions SET settlement_id = ? WHERE id = ?",
            (settlement_id, session_id),
        )


def test_trigger_lock_same_worker_enforced(conn: sqlite3.Connection) -> None:
    w1 = insert_worker(conn, name="WorkerOne")
    w2 = insert_worker(conn, name="WorkerTwo")

    s1 = insert_settlement(conn, worker_id=w1)
    session_w2 = insert_session(conn, worker_id=w2)
    tx_w2 = insert_money_transaction(conn, worker_id=w2)

    with pytest.raises(sqlite3.IntegrityError, match="settlement belongs to another worker"):
        conn.execute(
            "UPDATE sessions SET settlement_id = ? WHERE id = ?",
            (s1, session_w2),
        )

    with pytest.raises(sqlite3.IntegrityError, match="settlement belongs to another worker"):
        conn.execute(
            "UPDATE money_transactions SET settlement_id = ? WHERE id = ?",
            (s1, tx_w2),
        )


def test_trigger_lock_happy_path_and_prevent_unlock(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="WorkerHappyLock")
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    session_id = insert_session(conn, worker_id=worker_id, settlement_id=None)
    tx_id = insert_money_transaction(conn, worker_id=worker_id, settlement_id=None)

    conn.execute(
        "UPDATE sessions SET settlement_id = ? WHERE id = ?",
        (settlement_id, session_id),
    )
    conn.execute(
        "UPDATE money_transactions SET settlement_id = ? WHERE id = ?",
        (settlement_id, tx_id),
    )

    s_row = conn.execute(
        "SELECT settlement_id FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()
    assert s_row is not None
    assert s_row["settlement_id"] == settlement_id

    tx_row = conn.execute(
        "SELECT settlement_id FROM money_transactions WHERE id = ?", (tx_id,)
    ).fetchone()
    assert tx_row is not None
    assert tx_row["settlement_id"] == settlement_id

    with pytest.raises(sqlite3.IntegrityError, match="record locked"):
        conn.execute("UPDATE sessions SET settlement_id = NULL WHERE id = ?", (session_id,))

    with pytest.raises(sqlite3.IntegrityError, match="record locked"):
        conn.execute("UPDATE money_transactions SET settlement_id = NULL WHERE id = ?", (tx_id,))


def test_unlocked_rows_update_and_delete_normally(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="WorkerNormal", phone="123", note="Original", archived=0)
    conn.execute(
        "UPDATE workers SET phone = ?, note = ?, archived = ? WHERE id = ?",
        ("456", "Updated", 1, worker_id),
    )
    w_row = conn.execute(
        "SELECT phone, note, archived FROM workers WHERE id = ?", (worker_id,)
    ).fetchone()
    assert w_row is not None
    assert w_row["phone"] == "456"
    assert w_row["note"] == "Updated"
    assert w_row["archived"] == 1

    session_id = insert_session(
        conn,
        worker_id=worker_id,
        start_at="2026-11-06T08:00:00",
        end_at="2026-11-06T12:00:00",
        note="Initial",
    )
    conn.execute("UPDATE sessions SET note = ? WHERE id = ?", ("Updated note", session_id))
    s_row = conn.execute("SELECT note FROM sessions WHERE id = ?", (session_id,)).fetchone()
    assert s_row is not None
    assert s_row["note"] == "Updated note"
    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    assert conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,)).fetchone() is None

    tx_id = insert_money_transaction(conn, worker_id=worker_id, amount=1000, note="Initial")
    conn.execute(
        "UPDATE money_transactions SET amount = ?, note = ? WHERE id = ?",
        (2000, "Updated", tx_id),
    )
    tx_row = conn.execute(
        "SELECT amount, note FROM money_transactions WHERE id = ?", (tx_id,)
    ).fetchone()
    assert tx_row is not None
    assert tx_row["amount"] == 2000
    assert tx_row["note"] == "Updated"
    conn.execute("DELETE FROM money_transactions WHERE id = ?", (tx_id,))
    assert (
        conn.execute("SELECT id FROM money_transactions WHERE id = ?", (tx_id,)).fetchone() is None
    )
