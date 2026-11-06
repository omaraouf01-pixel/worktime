import ast
import sqlite3
from pathlib import Path

import pytest

from worktime.data import (
    DatabaseError,
    DuplicateWorkerError,
    RecordNotFoundError,
    WorkerRepository,
)
from worktime.domain import Worker


def test_add_worker_round_trip(conn: sqlite3.Connection) -> None:
    repo = WorkerRepository(conn)
    worker = Worker(
        name="محمد بلقاسم",
        phone="0550123456",
        note="عامل مؤقت",
        archived=False,
    )
    saved = repo.add(worker)
    assert saved.id is not None
    assert saved.name == "محمد بلقاسم"
    assert saved.phone == "0550123456"
    assert saved.note == "عامل مؤقت"
    assert saved.archived is False

    loaded = repo.get(saved.id)
    assert loaded == saved


def test_add_worker_with_id_raises_error(conn: sqlite3.Connection) -> None:
    repo = WorkerRepository(conn)
    worker = Worker(id=1, name="Ali", phone="", note="", archived=False)
    with pytest.raises(DatabaseError, match="id"):
        repo.add(worker)


def test_get_worker_missing_returns_none(conn: sqlite3.Connection) -> None:
    repo = WorkerRepository(conn)
    assert repo.get(999) is None


def test_list_workers_filtering_and_ordering(conn: sqlite3.Connection) -> None:
    repo = WorkerRepository(conn)
    w_charlie = repo.add(Worker(name="charlie"))
    w_alice_archived = repo.add(Worker(name="alice"))
    repo.update(
        Worker(
            id=w_alice_archived.id,
            name=w_alice_archived.name,
            archived=True,
        )
    )
    w_bob = repo.add(Worker(name="BOB"))
    w_adam = repo.add(Worker(name="adam"))

    active = repo.list_workers()
    assert [w.name for w in active] == ["adam", "BOB", "charlie"]
    assert [w.id for w in active] == [w_adam.id, w_bob.id, w_charlie.id]

    all_workers = repo.list_workers(include_archived=True)
    assert [w.name for w in all_workers] == ["adam", "alice", "BOB", "charlie"]


def test_update_worker(conn: sqlite3.Connection) -> None:
    repo = WorkerRepository(conn)
    saved = repo.add(Worker(name="Initial Name", phone="123", note="Note"))
    assert saved.id is not None

    updated = repo.update(
        Worker(
            id=saved.id,
            name="New Name",
            phone="456",
            note="Updated Note",
            archived=True,
        )
    )
    assert updated.id == saved.id
    assert updated.name == "New Name"
    assert updated.phone == "456"
    assert updated.note == "Updated Note"
    assert updated.archived is True

    reloaded = repo.get(saved.id)
    assert reloaded == updated


def test_update_worker_missing_id_raises_error(conn: sqlite3.Connection) -> None:
    repo = WorkerRepository(conn)
    worker_without_id = Worker(name="No ID")
    with pytest.raises(DatabaseError, match="id"):
        repo.update(worker_without_id)

    worker_not_found = Worker(id=999, name="Ghost")
    with pytest.raises(RecordNotFoundError):
        repo.update(worker_not_found)


def test_duplicate_active_name_rejected_on_add(conn: sqlite3.Connection) -> None:
    repo = WorkerRepository(conn)
    repo.add(Worker(name="Omar"))
    with pytest.raises(DuplicateWorkerError):
        repo.add(Worker(name="omar"))


def test_duplicate_active_name_rejected_on_update(conn: sqlite3.Connection) -> None:
    repo = WorkerRepository(conn)
    repo.add(Worker(name="Omar"))
    w2 = repo.add(Worker(name="Khaled"))

    assert w2.id is not None
    with pytest.raises(DuplicateWorkerError):
        repo.update(Worker(id=w2.id, name="OMAR"))


def test_duplicate_name_allowed_if_other_is_archived(
    conn: sqlite3.Connection,
) -> None:
    repo = WorkerRepository(conn)
    w1 = repo.add(Worker(name="Omar"))
    assert w1.id is not None
    repo.update(Worker(id=w1.id, name="Omar", archived=True))

    w2 = repo.add(Worker(name="Omar"))
    assert w2.id is not None
    assert w2.id != w1.id


def test_unarchiving_into_conflict_raises_error_and_preserves_row(
    conn: sqlite3.Connection,
) -> None:
    repo = WorkerRepository(conn)
    w1 = repo.add(Worker(name="Omar"))
    assert w1.id is not None
    repo.update(Worker(id=w1.id, name="Omar", archived=True))

    repo.add(Worker(name="Omar"))

    with pytest.raises(DuplicateWorkerError):
        repo.update(Worker(id=w1.id, name="Omar", archived=False))

    reloaded = repo.get(w1.id)
    assert reloaded is not None
    assert reloaded.archived is True


def test_worker_repo_has_no_delete_method() -> None:
    assert not hasattr(WorkerRepository, "delete")


@pytest.mark.parametrize(
    "filename",
    ["workers.py", "sessions.py", "transactions.py", "_mapping.py"],
)
def test_no_transaction_control_in_repository_files(filename: str) -> None:
    path = Path("src/worktime/data") / filename
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "worktime.data.database":
            for alias in node.names:
                assert alias.name != "write_transaction"
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            upper = node.value.upper()
            assert "BEGIN" not in upper
            assert "COMMIT" not in upper
            assert "ROLLBACK" not in upper
