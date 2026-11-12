"""Tests for SettlementRepository and record locking."""

import ast
import sqlite3
from collections.abc import Sequence
from datetime import date, datetime
from pathlib import Path

import pytest

from tests.data.conftest import insert_worker
from worktime.data import (
    DatabaseError,
    RecordNotFoundError,
    SessionRepository,
    SettlementRepository,
    TransactionRepository,
    WorkerRepository,
    write_transaction,
)
from worktime.domain import (
    RecordLockedError,
    Session,
    Settlement,
    Transaction,
    TransactionKind,
    ValidationError,
    Worker,
)


def _make_settlement(
    *,
    worker_id: int,
    settled_on: date = date(2026, 11, 10),
    total_minutes: int = 300,
    wage: int = 50000,
    advances_total: int = 10000,
    prepayments_total: int = 5000,
    deductions_total: int = 5000,
    previous_balance: int = 0,
    paid: int = 30000,
    note: str = "",
    id: int | None = None,
) -> Settlement:
    deductions = advances_total + prepayments_total + deductions_total
    payable = previous_balance + wage - deductions
    if payable > 0:
        new_balance = payable - paid
    else:
        paid = 0
        new_balance = payable
    return Settlement(
        id=id,
        worker_id=worker_id,
        settled_on=settled_on,
        total_minutes=total_minutes,
        wage=wage,
        advances_total=advances_total,
        prepayments_total=prepayments_total,
        deductions_total=deductions_total,
        previous_balance=previous_balance,
        payable=payable,
        paid=paid,
        new_balance=new_balance,
        note=note,
    )


def test_add_and_get_round_trip(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="Omar")
    repo = SettlementRepository(conn)

    arabic_note = "تسوية شهر نوفمبر"
    settlement = _make_settlement(
        worker_id=worker_id,
        settled_on=date(2026, 11, 10),
        total_minutes=480,
        wage=80000,
        advances_total=10000,
        prepayments_total=5000,
        deductions_total=5000,
        previous_balance=20000,
        paid=50000,
        note=arabic_note,
    )
    saved = repo.add(settlement)
    assert saved.id is not None
    assert saved.worker_id == worker_id
    assert saved.settled_on == date(2026, 11, 10)
    assert saved.total_minutes == 480
    assert saved.wage == 80000
    assert saved.advances_total == 10000
    assert saved.prepayments_total == 5000
    assert saved.deductions_total == 5000
    assert saved.previous_balance == 20000
    assert saved.payable == 80000
    assert saved.paid == 50000
    assert saved.new_balance == 30000
    assert saved.note == arabic_note

    loaded = repo.get(saved.id)
    assert loaded == saved


def test_add_negative_balance_settlement(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="Zaid")
    repo = SettlementRepository(conn)

    settlement = _make_settlement(
        worker_id=worker_id,
        total_minutes=120,
        wage=20000,
        advances_total=50000,
        prepayments_total=0,
        deductions_total=0,
        previous_balance=-10000,
        note="رصيد سالب بعد السلفة",
    )
    assert settlement.payable == -40000
    assert settlement.paid == 0
    assert settlement.new_balance == -40000

    saved = repo.add(settlement)
    assert saved.id is not None
    assert saved.new_balance == -40000

    loaded = repo.get(saved.id)
    assert loaded == saved


def test_add_with_existing_id_raises_database_error(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    repo = SettlementRepository(conn)
    settlement = _make_settlement(worker_id=worker_id, id=42)
    with pytest.raises(DatabaseError, match="Cannot add settlement that already has an id"):
        repo.add(settlement)


def test_add_unknown_worker_raises_record_not_found(conn: sqlite3.Connection) -> None:
    repo = SettlementRepository(conn)
    settlement = _make_settlement(worker_id=99999)
    with pytest.raises(RecordNotFoundError, match="worker not found"):
        repo.add(settlement)


def test_get_missing_returns_none(conn: sqlite3.Connection) -> None:
    repo = SettlementRepository(conn)
    assert repo.get(99999) is None


def test_list_for_worker_ordered_by_id(conn: sqlite3.Connection) -> None:
    worker1 = insert_worker(conn, name="Worker 1")
    worker2 = insert_worker(conn, name="Worker 2")
    repo = SettlementRepository(conn)

    s1 = repo.add(_make_settlement(worker_id=worker1, settled_on=date(2026, 11, 5)))
    s2 = repo.add(_make_settlement(worker_id=worker2, settled_on=date(2026, 11, 6)))
    s3 = repo.add(_make_settlement(worker_id=worker1, settled_on=date(2026, 11, 7)))

    w1_list = repo.list_for_worker(worker1)
    assert [s.id for s in w1_list] == [s1.id, s3.id]
    assert w1_list[0] == s1
    assert w1_list[1] == s3

    assert repo.list_for_worker(worker2) == [s2]
    assert repo.list_for_worker(99999) == []


def test_last_balance(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    repo = SettlementRepository(conn)

    assert repo.last_balance(worker_id) == 0

    s1 = repo.add(
        _make_settlement(
            worker_id=worker_id,
            settled_on=date(2026, 11, 10),
            wage=50000,
            paid=30000,
        )
    )
    assert repo.last_balance(worker_id) == s1.new_balance

    s2 = repo.add(
        _make_settlement(
            worker_id=worker_id,
            settled_on=date(2026, 11, 1),
            wage=10000,
            paid=10000,
        )
    )
    assert s2.id is not None and s1.id is not None and s2.id > s1.id
    assert repo.last_balance(worker_id) == s2.new_balance


def test_latest_balances(conn: sqlite3.Connection) -> None:
    repo = SettlementRepository(conn)
    assert repo.latest_balances() == {}

    w1 = insert_worker(conn, name="Worker 1")
    w2 = insert_worker(conn, name="Worker 2")
    w3 = insert_worker(conn, name="Worker 3")
    w4 = insert_worker(conn, name="Worker 4")

    repo.add(_make_settlement(worker_id=w1, wage=50000, paid=20000))
    repo.add(_make_settlement(worker_id=w1, wage=60000, previous_balance=10000, paid=45000))

    repo.add(
        _make_settlement(
            worker_id=w2,
            wage=10000,
            advances_total=40000,
            prepayments_total=0,
            deductions_total=0,
        )
    )

    repo.add(_make_settlement(worker_id=w3, wage=50000, paid=30000))

    balances = repo.latest_balances()
    assert balances == {
        w1: 5000,
        w2: -30000,
        w3: 0,
    }
    assert w4 not in balances


def test_settlements_are_immutable(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    repo = SettlementRepository(conn)

    assert not hasattr(repo, "update")
    assert not hasattr(repo, "delete")

    saved = repo.add(_make_settlement(worker_id=worker_id))
    with pytest.raises(sqlite3.IntegrityError, match="settlement is immutable"):
        conn.execute("UPDATE settlements SET note = 'changed' WHERE id = ?", (saved.id,))

    with pytest.raises(sqlite3.IntegrityError, match="settlement is immutable"):
        conn.execute("DELETE FROM settlements WHERE id = ?", (saved.id,))


def test_attach_records_happy_path(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    s_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)

    sess1 = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 16, 0, 0),
        )
    )
    sess2 = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 2, 8, 0, 0),
            end=datetime(2026, 11, 2, 16, 0, 0),
        )
    )
    sess_unrelated = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 3, 8, 0, 0),
            end=datetime(2026, 11, 3, 16, 0, 0),
        )
    )

    tx1 = tx_repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=10000,
            occurred_on=date(2026, 11, 1),
        )
    )
    tx2 = tx_repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.DEDUCTION,
            amount=5000,
            occurred_on=date(2026, 11, 2),
        )
    )
    tx_unrelated = tx_repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.PREPAYMENT,
            amount=5000,
            occurred_on=date(2026, 11, 3),
        )
    )

    settlement = s_repo.add(_make_settlement(worker_id=worker_id))
    assert settlement.id is not None

    assert sess1.id is not None and sess2.id is not None and sess_unrelated.id is not None
    assert tx1.id is not None and tx2.id is not None and tx_unrelated.id is not None

    s_repo.attach_records(
        settlement.id,
        session_ids=[sess1.id, sess2.id],
        transaction_ids=[tx1.id, tx2.id],
    )

    re_sess1 = session_repo.get(sess1.id)
    assert re_sess1 is not None and re_sess1.is_locked and re_sess1.settlement_id == settlement.id
    re_sess2 = session_repo.get(sess2.id)
    assert re_sess2 is not None and re_sess2.is_locked and re_sess2.settlement_id == settlement.id
    re_sess_unrelated = session_repo.get(sess_unrelated.id)
    assert (
        re_sess_unrelated is not None
        and not re_sess_unrelated.is_locked
        and re_sess_unrelated.settlement_id is None
    )

    re_tx1 = tx_repo.get(tx1.id)
    assert re_tx1 is not None and re_tx1.is_locked and re_tx1.settlement_id == settlement.id
    re_tx2 = tx_repo.get(tx2.id)
    assert re_tx2 is not None and re_tx2.is_locked and re_tx2.settlement_id == settlement.id
    re_tx_unrelated = tx_repo.get(tx_unrelated.id)
    assert (
        re_tx_unrelated is not None
        and not re_tx_unrelated.is_locked
        and re_tx_unrelated.settlement_id is None
    )


def test_attach_records_empty_lists_is_noop(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    s_repo = SettlementRepository(conn)
    settlement = s_repo.add(_make_settlement(worker_id=worker_id))
    assert settlement.id is not None

    s_repo.attach_records(settlement.id, session_ids=[], transaction_ids=[])


def test_attach_records_unknown_settlement(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    s_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)

    sess = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 16, 0, 0),
        )
    )
    tx = tx_repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=5000,
            occurred_on=date(2026, 11, 1),
        )
    )
    assert sess.id is not None and tx.id is not None

    with pytest.raises(RecordNotFoundError, match="settlement not found"):
        s_repo.attach_records(99999, session_ids=[sess.id], transaction_ids=[tx.id])

    re_sess = session_repo.get(sess.id)
    assert re_sess is not None and not re_sess.is_locked
    re_tx = tx_repo.get(tx.id)
    assert re_tx is not None and not re_tx.is_locked


def test_attach_records_missing_records(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    s_repo = SettlementRepository(conn)
    settlement = s_repo.add(_make_settlement(worker_id=worker_id))
    assert settlement.id is not None

    with pytest.raises(RecordNotFoundError, match="Session not found"):
        s_repo.attach_records(settlement.id, session_ids=[99999], transaction_ids=[])

    with pytest.raises(RecordNotFoundError, match="Transaction not found"):
        s_repo.attach_records(settlement.id, session_ids=[], transaction_ids=[99999])


def test_attach_records_already_linked(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    s_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)

    sess = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 16, 0, 0),
        )
    )
    tx = tx_repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=5000,
            occurred_on=date(2026, 11, 1),
        )
    )
    s1 = s_repo.add(_make_settlement(worker_id=worker_id))
    s2 = s_repo.add(_make_settlement(worker_id=worker_id))
    assert sess.id is not None and tx.id is not None and s1.id is not None and s2.id is not None

    s_repo.attach_records(s1.id, session_ids=[sess.id], transaction_ids=[tx.id])

    with pytest.raises(RecordLockedError, match="record already settled"):
        s_repo.attach_records(s1.id, session_ids=[sess.id], transaction_ids=[])
    re_sess = session_repo.get(sess.id)
    assert re_sess is not None and re_sess.settlement_id == s1.id

    with pytest.raises(RecordLockedError, match="record already settled"):
        s_repo.attach_records(s2.id, session_ids=[sess.id], transaction_ids=[])
    re_sess = session_repo.get(sess.id)
    assert re_sess is not None and re_sess.settlement_id == s1.id

    with pytest.raises(RecordLockedError, match="record already settled"):
        s_repo.attach_records(s1.id, session_ids=[], transaction_ids=[tx.id])
    re_tx = tx_repo.get(tx.id)
    assert re_tx is not None and re_tx.settlement_id == s1.id

    with pytest.raises(RecordLockedError, match="record already settled"):
        s_repo.attach_records(s2.id, session_ids=[], transaction_ids=[tx.id])
    re_tx = tx_repo.get(tx.id)
    assert re_tx is not None and re_tx.settlement_id == s1.id


def test_attach_records_open_session_raises_validation_error(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    s_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)

    open_sess = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=None,
        )
    )
    settlement = s_repo.add(_make_settlement(worker_id=worker_id))
    assert open_sess.id is not None and settlement.id is not None

    with pytest.raises(ValidationError, match="cannot lock an open session"):
        s_repo.attach_records(settlement.id, session_ids=[open_sess.id], transaction_ids=[])


def test_attach_records_different_worker_raises_validation_error(
    conn: sqlite3.Connection,
) -> None:
    w1 = insert_worker(conn, name="Worker 1")
    w2 = insert_worker(conn, name="Worker 2")
    s_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)

    sess_w2 = session_repo.add(
        Session(
            worker_id=w2,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 16, 0, 0),
        )
    )
    tx_w2 = tx_repo.add(
        Transaction(
            worker_id=w2,
            kind=TransactionKind.ADVANCE,
            amount=5000,
            occurred_on=date(2026, 11, 1),
        )
    )
    s_w1 = s_repo.add(_make_settlement(worker_id=w1))
    assert sess_w2.id is not None and tx_w2.id is not None and s_w1.id is not None

    with pytest.raises(ValidationError, match="settlement belongs to another worker"):
        s_repo.attach_records(s_w1.id, session_ids=[sess_w2.id], transaction_ids=[])

    with pytest.raises(ValidationError, match="settlement belongs to another worker"):
        s_repo.attach_records(s_w1.id, session_ids=[], transaction_ids=[tx_w2.id])


@pytest.mark.parametrize(
    "invalid_ids",
    [
        [1, 1],
        [0],
        [-1],
        [True],
        [1.5],
    ],
)
def test_attach_records_invalid_ids_raise_database_error(
    conn: sqlite3.Connection,
    invalid_ids: Sequence[object],
) -> None:
    worker_id = insert_worker(conn)
    s_repo = SettlementRepository(conn)
    settlement = s_repo.add(_make_settlement(worker_id=worker_id))
    assert settlement.id is not None

    # Cast to Sequence[int] to test runtime validation of erroneous inputs
    bad_ids = invalid_ids  # type: ignore[assignment]

    with pytest.raises(DatabaseError):
        s_repo.attach_records(settlement.id, session_ids=bad_ids, transaction_ids=[])

    with pytest.raises(DatabaseError):
        s_repo.attach_records(settlement.id, session_ids=[], transaction_ids=bad_ids)


def test_attach_records_atomic_rollback(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    s_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)

    sess = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 16, 0, 0),
        )
    )
    settlement = s_repo.add(_make_settlement(worker_id=worker_id))
    assert sess.id is not None and settlement.id is not None

    with pytest.raises(RecordNotFoundError):
        with write_transaction(conn):
            s_repo.attach_records(
                settlement.id,
                session_ids=[sess.id, 99999],
                transaction_ids=[],
            )

    re_sess = session_repo.get(sess.id)
    assert re_sess is not None and not re_sess.is_locked and re_sess.settlement_id is None


def test_sessions_of_and_transactions_of_order(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    s_repo = SettlementRepository(conn)
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)

    s_late = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 2, 8, 0, 0),
            end=datetime(2026, 11, 2, 16, 0, 0),
        )
    )
    s_early = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 16, 0, 0),
        )
    )

    t_late = tx_repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=5000,
            occurred_on=date(2026, 11, 5),
        )
    )
    t_early = tx_repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.DEDUCTION,
            amount=2000,
            occurred_on=date(2026, 11, 1),
        )
    )

    settlement = s_repo.add(_make_settlement(worker_id=worker_id))
    assert settlement.id is not None
    assert s_late.id is not None and s_early.id is not None
    assert t_late.id is not None and t_early.id is not None

    # Attach in reversed order
    s_repo.attach_records(
        settlement.id,
        session_ids=[s_late.id, s_early.id],
        transaction_ids=[t_late.id, t_early.id],
    )

    sessions = s_repo.sessions_of(settlement.id)
    assert [s.id for s in sessions] == [s_early.id, s_late.id]

    txs = s_repo.transactions_of(settlement.id)
    assert [t.id for t in txs] == [t_early.id, t_late.id]

    # Unknown settlement or settlement with no attached records
    assert s_repo.sessions_of(99999) == []
    assert s_repo.transactions_of(99999) == []

    s_empty = s_repo.add(_make_settlement(worker_id=worker_id))
    assert s_empty.id is not None
    assert s_repo.sessions_of(s_empty.id) == []
    assert s_repo.transactions_of(s_empty.id) == []


def test_settlements_source_compliance() -> None:
    path = Path("src/worktime/data/settlements.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    for node in ast.walk(tree):
        assert not isinstance(node, ast.JoinedStr), "f-string found in settlements.py"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper_val = node.value.upper()
            assert "BEGIN" not in upper_val, "BEGIN found in settlements.py string"
            assert "COMMIT" not in upper_val, "COMMIT found in settlements.py string"
            assert "ROLLBACK" not in upper_val, "ROLLBACK found in settlements.py string"
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "write_transaction"
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                assert alias.name != "write_transaction"


def test_mapping_helpers_edge_cases(conn: sqlite3.Connection) -> None:
    from worktime.data._mapping import (
        _bool,
        _int,
        _opt_int,
        _opt_str,
        _str,
        from_db_date,
        from_db_datetime,
        require_lastrowid,
        translate_integrity_error,
    )

    with pytest.raises(DatabaseError, match="Invalid ISO datetime"):
        from_db_datetime("not-a-datetime")

    with pytest.raises(DatabaseError, match="Expected naive datetime without microseconds"):
        from_db_datetime("2026-11-10T12:00:00+01:00")

    with pytest.raises(DatabaseError, match="Expected naive datetime without microseconds"):
        from_db_datetime("2026-11-10T12:00:00.123456")

    with pytest.raises(DatabaseError, match="Invalid ISO date"):
        from_db_date("not-a-date")

    cursor = conn.cursor()
    with pytest.raises(DatabaseError, match="Cursor has no lastrowid"):
        require_lastrowid(cursor)

    generic_exc = sqlite3.IntegrityError("CHECK constraint failed")
    translated = translate_integrity_error(generic_exc, context="unknown")
    assert isinstance(translated, DatabaseError)

    conn.execute("CREATE TEMPORARY TABLE test_types (b INTEGER, s TEXT, i INTEGER, f REAL)")
    conn.execute("INSERT INTO test_types VALUES (1, 'text', 42, 3.14)")
    row = conn.execute("SELECT * FROM test_types").fetchone()

    with pytest.raises(DatabaseError, match="Expected int for column"):
        _int(row, "s")
    with pytest.raises(DatabaseError, match="Expected int for column"):
        _int(row, "f")

    with pytest.raises(DatabaseError, match="Expected int or None for column"):
        _opt_int(row, "s")

    with pytest.raises(DatabaseError, match="Expected str for column"):
        _str(row, "i")

    with pytest.raises(DatabaseError, match="Expected str or None for column"):
        _opt_str(row, "i")

    assert _bool(row, "b") is True

    class FakeRow(dict[str, object]):
        pass

    fake_bool = FakeRow({"val": True, "bad": 3.14})
    assert _bool(fake_bool, "val") is True  # type: ignore[arg-type]
    with pytest.raises(DatabaseError, match="Expected bool or int for column"):
        _bool(fake_bool, "bad")  # type: ignore[arg-type]


def test_defensive_not_found_branches(
    conn: sqlite3.Connection,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_id = insert_worker(conn, name="Defensive Worker")
    w_repo = WorkerRepository(conn)
    s_repo = SettlementRepository(conn)
    sess_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)

    monkeypatch.setattr(s_repo, "get", lambda *args, **kwargs: None)
    with pytest.raises(DatabaseError, match="Settlement not found after insert"):
        s_repo.add(_make_settlement(worker_id=worker_id))

    monkeypatch.setattr(w_repo, "get", lambda *args, **kwargs: None)
    with pytest.raises(DatabaseError, match="Worker not found after insert"):
        w_repo.add(Worker(name="Worker X"))
    with pytest.raises(DatabaseError, match="Worker not found after update"):
        w_repo.update(Worker(id=worker_id, name="Updated"))

    sess = Session(worker_id=worker_id, start=datetime(2026, 11, 1, 8, 0, 0))
    monkeypatch.setattr(sess_repo, "get", lambda *args, **kwargs: None)
    with pytest.raises(DatabaseError, match="Session not found after insert"):
        sess_repo.add(sess)
    with pytest.raises(DatabaseError, match="Session not found after update"):
        sess_repo.update(Session(id=1, worker_id=worker_id, start=datetime(2026, 11, 1, 8, 0, 0)))

    tx = Transaction(
        worker_id=worker_id,
        kind=TransactionKind.ADVANCE,
        amount=1000,
        occurred_on=date(2026, 11, 1),
    )
    monkeypatch.setattr(tx_repo, "get", lambda *args, **kwargs: None)
    with pytest.raises(DatabaseError, match="Transaction not found after insert"):
        tx_repo.add(tx)
    with pytest.raises(DatabaseError, match="Transaction not found after update"):
        tx_repo.update(
            Transaction(
                id=1,
                worker_id=worker_id,
                kind=TransactionKind.ADVANCE,
                amount=1000,
                occurred_on=date(2026, 11, 1),
            )
        )
