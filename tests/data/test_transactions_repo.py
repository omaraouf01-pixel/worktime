import sqlite3
from datetime import date, datetime

import pytest

from tests.data.conftest import insert_settlement, insert_worker
from worktime.data import (
    DatabaseError,
    RecordNotFoundError,
    TransactionRepository,
)
from worktime.domain import (
    RecordLockedError,
    Transaction,
    TransactionKind,
)


@pytest.mark.parametrize(
    "kind",
    [
        TransactionKind.ADVANCE,
        TransactionKind.PREPAYMENT,
        TransactionKind.DEDUCTION,
    ],
)
def test_add_transaction_kinds_round_trip(conn: sqlite3.Connection, kind: TransactionKind) -> None:
    worker_id = insert_worker(conn)
    repo = TransactionRepository(conn)

    tx = Transaction(
        worker_id=worker_id,
        kind=kind,
        amount=500000,
        occurred_on=date(2026, 11, 6),
        note="دفعة نقدية",
    )
    saved = repo.add(tx)
    assert saved.id is not None
    assert saved.worker_id == worker_id
    assert saved.kind == kind
    assert saved.amount == 500000
    assert saved.occurred_on == date(2026, 11, 6)
    assert saved.note == "دفعة نقدية"
    assert saved.settlement_id is None

    loaded = repo.get(saved.id)
    assert loaded == saved


def test_add_transaction_with_existing_id_raises_error(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    repo = TransactionRepository(conn)
    tx = Transaction(
        id=12,
        worker_id=worker_id,
        kind=TransactionKind.ADVANCE,
        amount=1000,
        occurred_on=date(2026, 11, 6),
    )
    with pytest.raises(DatabaseError, match="id"):
        repo.add(tx)


def test_add_transaction_with_settlement_id_raises_database_error(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    repo = TransactionRepository(conn)
    tx = Transaction(
        worker_id=worker_id,
        kind=TransactionKind.ADVANCE,
        amount=1000,
        occurred_on=date(2026, 11, 6),
        settlement_id=settlement_id,
    )
    with pytest.raises(DatabaseError, match="new records cannot carry a settlement"):
        repo.add(tx)
    count = conn.execute("SELECT COUNT(*) FROM money_transactions").fetchone()[0]
    assert count == 0


def test_add_transaction_for_unknown_worker_raises_error(
    conn: sqlite3.Connection,
) -> None:
    repo = TransactionRepository(conn)
    tx = Transaction(
        worker_id=999,
        kind=TransactionKind.ADVANCE,
        amount=1000,
        occurred_on=date(2026, 11, 6),
    )
    with pytest.raises(RecordNotFoundError, match="worker not found"):
        repo.add(tx)


def test_add_transaction_occurred_on_as_datetime_raises_error(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    repo = TransactionRepository(conn)

    tx = Transaction(
        worker_id=worker_id,
        kind=TransactionKind.ADVANCE,
        amount=1000,
        occurred_on=date(2026, 11, 6),
    )
    # Bypass domain init to test repository data layer defense
    object.__setattr__(tx, "occurred_on", datetime(2026, 11, 6, 12, 0, 0))

    with pytest.raises(DatabaseError):
        repo.add(tx)


def test_get_transaction_missing_returns_none(conn: sqlite3.Connection) -> None:
    repo = TransactionRepository(conn)
    assert repo.get(999) is None


def test_list_for_worker_filtering_and_bounds(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    repo = TransactionRepository(conn)

    # 1. Day before from_date
    repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=1000,
            occurred_on=date(2026, 11, 4),
        )
    )
    # 2. Exactly from_date
    t_from = repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.PREPAYMENT,
            amount=2000,
            occurred_on=date(2026, 11, 5),
        )
    )
    # 3. Middle
    t_mid = repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.DEDUCTION,
            amount=3000,
            occurred_on=date(2026, 11, 5),
        )
    )
    # 4. Exactly to_date
    t_to = repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=4000,
            occurred_on=date(2026, 11, 6),
        )
    )
    # 5. Day after to_date
    repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=5000,
            occurred_on=date(2026, 11, 7),
        )
    )

    # Lock t_from with a settlement
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    conn.execute(
        "UPDATE money_transactions SET settlement_id = ? WHERE id = ?",
        (settlement_id, t_from.id),
    )

    # Filter with bounds from 2026-11-05 to 2026-11-06
    in_range = repo.list_for_worker(
        worker_id,
        from_date=date(2026, 11, 5),
        to_date=date(2026, 11, 6),
    )
    assert [t.id for t in in_range] == [t_from.id, t_mid.id, t_to.id]

    # unsettled_only hides locked t_from
    unsettled = repo.list_for_worker(
        worker_id,
        from_date=date(2026, 11, 5),
        to_date=date(2026, 11, 6),
        unsettled_only=True,
    )
    assert [t.id for t in unsettled] == [t_mid.id, t_to.id]

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
            to_date=datetime(2026, 11, 6, 0, 0, 0),  # type: ignore[arg-type]
        )

    # Only from_date
    only_from = repo.list_for_worker(worker_id, from_date=date(2026, 11, 6))
    assert [t.id for t in only_from] == [t_to.id, repo.list_for_worker(worker_id)[-1].id]

    # Only to_date
    only_to = repo.list_for_worker(worker_id, to_date=date(2026, 11, 5))
    all_tx = repo.list_for_worker(worker_id)
    assert [t.id for t in only_to] == [all_tx[0].id, t_from.id, t_mid.id]


def test_update_transaction(conn: sqlite3.Connection) -> None:
    w1 = insert_worker(conn, name="Worker 1")
    w2 = insert_worker(conn, name="Worker 2")
    repo = TransactionRepository(conn)

    tx = repo.add(
        Transaction(
            worker_id=w1,
            kind=TransactionKind.ADVANCE,
            amount=1000,
            occurred_on=date(2026, 11, 5),
            note="Initial",
        )
    )
    assert tx.id is not None

    # Normal update
    updated = repo.update(
        Transaction(
            id=tx.id,
            worker_id=w1,
            kind=TransactionKind.DEDUCTION,
            amount=2500,
            occurred_on=date(2026, 11, 6),
            note="Updated",
        )
    )
    assert updated.kind == TransactionKind.DEDUCTION
    assert updated.amount == 2500
    assert updated.occurred_on == date(2026, 11, 6)
    assert updated.note == "Updated"

    # Attempt to change worker_id or settlement_id:
    # Repository ignores them and updates only mutable fields.
    fake_settlement_id = 42
    re_updated = repo.update(
        Transaction(
            id=tx.id,
            worker_id=w2,
            kind=TransactionKind.PREPAYMENT,
            amount=3000,
            occurred_on=date(2026, 11, 6),
            note="Updated again",
            settlement_id=fake_settlement_id,
        )
    )
    assert re_updated.worker_id == w1
    assert re_updated.settlement_id is None

    # Update without id raises DatabaseError
    with pytest.raises(DatabaseError, match="id"):
        repo.update(
            Transaction(
                worker_id=w1,
                kind=TransactionKind.ADVANCE,
                amount=1000,
                occurred_on=date(2026, 11, 6),
            )
        )

    # Update missing id raises RecordNotFoundError
    with pytest.raises(RecordNotFoundError):
        repo.update(
            Transaction(
                id=999,
                worker_id=w1,
                kind=TransactionKind.ADVANCE,
                amount=1000,
                occurred_on=date(2026, 11, 6),
            )
        )


def test_update_locked_transaction_raises_record_locked_error(
    conn: sqlite3.Connection,
) -> None:
    worker_id = insert_worker(conn)
    repo = TransactionRepository(conn)
    tx = repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=1000,
            occurred_on=date(2026, 11, 6),
        )
    )
    assert tx.id is not None

    settlement_id = insert_settlement(conn, worker_id=worker_id)
    conn.execute(
        "UPDATE money_transactions SET settlement_id = ? WHERE id = ?",
        (settlement_id, tx.id),
    )

    with pytest.raises(RecordLockedError):
        repo.update(
            Transaction(
                id=tx.id,
                worker_id=worker_id,
                kind=TransactionKind.ADVANCE,
                amount=2000,
                occurred_on=date(2026, 11, 6),
            )
        )


def test_delete_transaction(conn: sqlite3.Connection) -> None:
    worker_id = insert_worker(conn)
    repo = TransactionRepository(conn)

    tx = repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.ADVANCE,
            amount=1000,
            occurred_on=date(2026, 11, 6),
        )
    )
    assert tx.id is not None

    # Delete missing id
    with pytest.raises(RecordNotFoundError):
        repo.delete(999)

    # Delete locked transaction
    settlement_id = insert_settlement(conn, worker_id=worker_id)
    conn.execute(
        "UPDATE money_transactions SET settlement_id = ? WHERE id = ?",
        (settlement_id, tx.id),
    )
    with pytest.raises(RecordLockedError):
        repo.delete(tx.id)

    # Row still exists
    assert repo.get(tx.id) is not None

    # Delete unlocked transaction
    unlocked = repo.add(
        Transaction(
            worker_id=worker_id,
            kind=TransactionKind.PREPAYMENT,
            amount=500,
            occurred_on=date(2026, 11, 7),
        )
    )
    assert unlocked.id is not None
    repo.delete(unlocked.id)
    assert repo.get(unlocked.id) is None
