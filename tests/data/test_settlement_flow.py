"""End-to-end integration flow tests simulating the settlement service."""

import sqlite3
from datetime import date, datetime, timedelta

import pytest

from tests.data.conftest import insert_worker
from worktime.data import (
    SessionRepository,
    SettlementRepository,
    TransactionRepository,
    write_transaction,
)
from worktime.domain import (
    RecordLockedError,
    Session,
    Transaction,
    TransactionKind,
    ValidationError,
    prepare_settlement,
)


def test_brief_example_1_and_2_end_to_end(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="Amine")
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)
    s_repo = SettlementRepository(conn)

    # 10 closed sessions of 600 minutes each (total 6000 minutes = 100 hours)
    base_start = datetime(2026, 11, 1, 8, 0, 0)
    sessions_p1: list[Session] = []
    for i in range(10):
        start = base_start + timedelta(days=i)
        end = start + timedelta(minutes=600)
        s = session_repo.add(Session(worker_id=worker_id, start=start, end=end))
        sessions_p1.append(s)

    # One advance of 700000 centimes (7000 DA)
    adv = tx_repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=700000,
            occurred_on=date(2026, 11, 5),
        )
    )

    hourly_rate = 5000  # 5000 centimes/hour
    prev_balance_1 = s_repo.last_balance(worker_id)
    assert prev_balance_1 == 0

    unsettled_sessions = session_repo.list_for_worker(worker_id, unsettled_only=True)
    unsettled_txs = tx_repo.list_for_worker(worker_id, unsettled_only=True)
    assert len(unsettled_sessions) == 10
    assert len(unsettled_txs) == 1

    with write_transaction(conn):
        draft_1 = prepare_settlement(
            worker_id=worker_id,
            sessions=unsettled_sessions,
            transactions=unsettled_txs,
            previous_balance=prev_balance_1,
            hourly_rate=hourly_rate,
        )
        assert draft_1.wage == 500000
        assert draft_1.payable == -200000

        final_1 = draft_1.finalize(paid=0, settled_on=date(2026, 11, 10))
        saved_1 = s_repo.add(final_1)
        assert saved_1.id is not None
        assert saved_1.wage == 500000
        assert saved_1.payable == -200000
        assert saved_1.new_balance == -200000

        session_ids_1 = [s.id for s in unsettled_sessions if s.id is not None]
        tx_ids_1 = [t.id for t in unsettled_txs if t.id is not None]
        s_repo.attach_records(saved_1.id, session_ids=session_ids_1, transaction_ids=tx_ids_1)

    assert s_repo.last_balance(worker_id) == -200000
    assert session_repo.list_for_worker(worker_id, unsettled_only=True) == []
    assert tx_repo.list_for_worker(worker_id, unsettled_only=True) == []

    for s in sessions_p1:
        assert s.id is not None
        re_s = session_repo.get(s.id)
        assert re_s is not None and re_s.is_locked and re_s.settlement_id == saved_1.id
    assert adv.id is not None
    re_adv = tx_repo.get(adv.id)
    assert re_adv is not None and re_adv.is_locked and re_adv.settlement_id == saved_1.id

    # Add 12 new closed sessions of 600 minutes each (total 7200 minutes = 120 hours)
    base_start_2 = datetime(2026, 11, 11, 8, 0, 0)
    sessions_p2: list[Session] = []
    for i in range(12):
        start = base_start_2 + timedelta(days=i)
        end = start + timedelta(minutes=600)
        s = session_repo.add(Session(worker_id=worker_id, start=start, end=end))
        sessions_p2.append(s)

    prev_balance_2 = s_repo.last_balance(worker_id)
    assert prev_balance_2 == -200000

    unsettled_sessions_2 = session_repo.list_for_worker(worker_id, unsettled_only=True)
    unsettled_txs_2 = tx_repo.list_for_worker(worker_id, unsettled_only=True)
    assert len(unsettled_sessions_2) == 12
    assert len(unsettled_txs_2) == 0

    with write_transaction(conn):
        draft_2 = prepare_settlement(
            worker_id=worker_id,
            sessions=unsettled_sessions_2,
            transactions=unsettled_txs_2,
            previous_balance=prev_balance_2,
            hourly_rate=hourly_rate,
        )
        # 7200 mins @ 5000/hr = 600000 wage; payable = -200000 + 600000 = 400000
        assert draft_2.wage == 600000
        assert draft_2.payable == 400000

        final_2 = draft_2.finalize(paid=300000, settled_on=date(2026, 11, 25))
        saved_2 = s_repo.add(final_2)
        assert saved_2.id is not None
        assert saved_2.new_balance == 100000

        session_ids_2 = [s.id for s in unsettled_sessions_2 if s.id is not None]
        s_repo.attach_records(saved_2.id, session_ids=session_ids_2, transaction_ids=[])

    assert s_repo.last_balance(worker_id) == 100000
    assert saved_2.id is not None
    settlement_2_sessions = s_repo.sessions_of(saved_2.id)
    assert [s.id for s in settlement_2_sessions] == [s.id for s in sessions_p2]


def test_november_scenario(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="Karim")
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)
    s_repo = SettlementRepository(conn)

    # 22 closed sessions totaling 4620 minutes (22 * 210 minutes = 3.5 hours each)
    base_start = datetime(2026, 11, 1, 8, 0, 0)
    for i in range(22):
        start = base_start + timedelta(days=i)
        end = start + timedelta(minutes=210)
        session_repo.add(Session(worker_id=worker_id, start=start, end=end))

    # Four advances totaling 450000 centimes
    advance_amounts = [100000, 100000, 150000, 100000]
    for i, amount in enumerate(advance_amounts):
        tx_repo.add(
            Transaction(
                worker_id=worker_id,
                kind=TransactionKind.ADVANCE,
                amount=amount,
                occurred_on=date(2026, 11, 1 + i * 5),
            )
        )

    hourly_rate = 10000  # 10000 centimes/hr (100 DA/hr)
    sessions = session_repo.list_for_worker(worker_id, unsettled_only=True)
    transactions = tx_repo.list_for_worker(worker_id, unsettled_only=True)
    assert len(sessions) == 22
    assert len(transactions) == 4

    prev_balance = s_repo.last_balance(worker_id)
    assert prev_balance == 0

    with write_transaction(conn):
        draft = prepare_settlement(
            worker_id=worker_id,
            sessions=sessions,
            transactions=transactions,
            previous_balance=prev_balance,
            hourly_rate=hourly_rate,
        )
        assert draft.total_minutes == 4620
        assert draft.wage == 770000
        assert draft.advances_total == 450000
        assert draft.payable == 320000

        final = draft.finalize(paid=320000, settled_on=date(2026, 11, 30))
        assert final.new_balance == 0

        saved = s_repo.add(final)
        assert saved.id is not None
        s_repo.attach_records(
            saved.id,
            session_ids=[s.id for s in sessions if s.id is not None],
            transaction_ids=[t.id for t in transactions if t.id is not None],
        )

    assert s_repo.last_balance(worker_id) == 0
    assert session_repo.list_for_worker(worker_id, unsettled_only=True) == []
    assert tx_repo.list_for_worker(worker_id, unsettled_only=True) == []


def test_debt_only_settlement(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="Samir")
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)
    s_repo = SettlementRepository(conn)

    # No sessions, one deduction of 50000 centimes
    deduction = tx_repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.DEDUCTION,
            amount=50000,
            occurred_on=date(2026, 11, 5),
        )
    )
    assert deduction.id is not None

    prev_balance = s_repo.last_balance(worker_id)
    assert prev_balance == 0

    with write_transaction(conn):
        draft = prepare_settlement(
            worker_id=worker_id,
            sessions=[],
            transactions=[deduction],
            previous_balance=prev_balance,
            hourly_rate=5000,
        )
        assert draft.total_minutes == 0
        assert draft.wage == 0
        assert draft.deductions_total == 50000
        assert draft.payable == -50000

        final = draft.finalize(paid=0, settled_on=date(2026, 11, 10))
        saved = s_repo.add(final)
        assert saved.id is not None
        assert saved.new_balance == -50000

        s_repo.attach_records(saved.id, session_ids=[], transaction_ids=[deduction.id])

    assert s_repo.last_balance(worker_id) == -50000

    # Carried to next settlement
    sess = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 15, 8, 0, 0),
            end=datetime(2026, 11, 15, 10, 0, 0),  # 120 minutes
        )
    )
    assert sess.id is not None

    with write_transaction(conn):
        draft2 = prepare_settlement(
            worker_id=worker_id,
            sessions=[sess],
            transactions=[],
            previous_balance=s_repo.last_balance(worker_id),
            hourly_rate=50000,  # 50000/hr -> 120 min = 100000
        )
        # previous -50000 + 100000 = 50000
        assert draft2.payable == 50000
        final2 = draft2.finalize(paid=50000, settled_on=date(2026, 11, 20))
        saved2 = s_repo.add(final2)
        assert saved2.id is not None
        assert saved2.new_balance == 0
        s_repo.attach_records(saved2.id, session_ids=[sess.id], transaction_ids=[])

    assert s_repo.last_balance(worker_id) == 0


def test_atomic_rollback_on_failed_attachment(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="Rachid")
    session_repo = SessionRepository(conn)
    s_repo = SettlementRepository(conn)

    sess1 = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 16, 0, 0),
        )
    )
    assert sess1.id is not None

    with write_transaction(conn):
        draft1 = prepare_settlement(
            worker_id=worker_id,
            sessions=[sess1],
            transactions=[],
            previous_balance=0,
            hourly_rate=5000,
        )
        final1 = draft1.finalize(paid=0, settled_on=date(2026, 11, 2))
        saved1 = s_repo.add(final1)
        assert saved1.id is not None
        s_repo.attach_records(saved1.id, session_ids=[sess1.id], transaction_ids=[])

    assert s_repo.last_balance(worker_id) == 40000
    assert len(s_repo.list_for_worker(worker_id)) == 1

    sess2 = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 3, 8, 0, 0),
            end=datetime(2026, 11, 3, 16, 0, 0),
        )
    )
    assert sess2.id is not None

    # Attempt to attach sess1 (already locked) along with sess2 in a new settlement
    with pytest.raises(RecordLockedError, match="record already settled"):
        with write_transaction(conn):
            draft2 = prepare_settlement(
                worker_id=worker_id,
                sessions=[sess2],
                transactions=[],
                previous_balance=s_repo.last_balance(worker_id),
                hourly_rate=5000,
            )
            final2 = draft2.finalize(paid=0, settled_on=date(2026, 11, 4))
            saved2 = s_repo.add(final2)
            assert saved2.id is not None
            s_repo.attach_records(
                saved2.id,
                session_ids=[sess2.id, sess1.id],
                transaction_ids=[],
            )

    # Rollback verified: settlement count unchanged, sess2 remains unlocked
    assert len(s_repo.list_for_worker(worker_id)) == 1
    re_sess2 = session_repo.get(sess2.id)
    assert re_sess2 is not None and not re_sess2.is_locked and re_sess2.settlement_id is None
    re_sess1 = session_repo.get(sess1.id)
    assert re_sess1 is not None and re_sess1.settlement_id == saved1.id


def test_open_session_guard(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn, name="Hassan")
    session_repo = SessionRepository(conn)
    s_repo = SettlementRepository(conn)

    closed = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 16, 0, 0),
        )
    )
    open_sess = session_repo.add(
        Session(
            worker_id=worker_id,
            start=datetime(2026, 11, 2, 8, 0, 0),
            end=None,
        )
    )

    with pytest.raises(ValidationError, match="worker has an open session"):
        prepare_settlement(
            worker_id=worker_id,
            sessions=[closed, open_sess],
            transactions=[],
            previous_balance=0,
            hourly_rate=5000,
        )

    assert s_repo.list_for_worker(worker_id) == []


def test_worker_isolation(conn: sqlite3.Connection) -> None:
    w_a = insert_worker(conn, name="Worker A")
    w_b = insert_worker(conn, name="Worker B")
    session_repo = SessionRepository(conn)
    tx_repo = TransactionRepository(conn)
    s_repo = SettlementRepository(conn)

    # Worker A: advance > wage -> negative balance
    s_a = session_repo.add(
        Session(
            worker_id=w_a,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 12, 0, 0),  # 240 min = 20000 @ 5000/hr
        )
    )
    t_a = tx_repo.add(
        Transaction(
            worker_id=w_a,
            kind=TransactionKind.ADVANCE,
            amount=50000,
            occurred_on=date(2026, 11, 1),
        )
    )

    # Worker B: wage > 0 -> positive balance
    s_b = session_repo.add(
        Session(
            worker_id=w_b,
            start=datetime(2026, 11, 1, 8, 0, 0),
            end=datetime(2026, 11, 1, 16, 0, 0),  # 480 min = 40000 @ 5000/hr
        )
    )

    assert s_a.id is not None and t_a.id is not None and s_b.id is not None

    with write_transaction(conn):
        draft_a = prepare_settlement(
            worker_id=w_a,
            sessions=[s_a],
            transactions=[t_a],
            previous_balance=0,
            hourly_rate=5000,
        )
        saved_a = s_repo.add(draft_a.finalize(paid=0, settled_on=date(2026, 11, 5)))
        assert saved_a.id is not None
        s_repo.attach_records(saved_a.id, session_ids=[s_a.id], transaction_ids=[t_a.id])

    with write_transaction(conn):
        draft_b = prepare_settlement(
            worker_id=w_b,
            sessions=[s_b],
            transactions=[],
            previous_balance=0,
            hourly_rate=5000,
        )
        saved_b = s_repo.add(draft_b.finalize(paid=10000, settled_on=date(2026, 11, 5)))
        assert saved_b.id is not None
        s_repo.attach_records(saved_b.id, session_ids=[s_b.id], transaction_ids=[])

    assert s_repo.last_balance(w_a) == -30000
    assert s_repo.last_balance(w_b) == 30000

    re_s_a = session_repo.get(s_a.id)
    assert re_s_a is not None and re_s_a.settlement_id == saved_a.id
    re_s_b = session_repo.get(s_b.id)
    assert re_s_b is not None and re_s_b.settlement_id == saved_b.id
