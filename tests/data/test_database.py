import ast
import sqlite3
from pathlib import Path

import pytest

from worktime.data import (
    MIGRATIONS,
    SCHEMA_VERSION,
    DatabaseError,
    DatabaseVersionError,
    connect,
    default_db_path,
    migrate,
    open_database,
    write_transaction,
)


def test_memory_database_migration_idempotent() -> None:
    assert SCHEMA_VERSION == 2
    conn = connect(":memory:")
    try:
        first_version = migrate(conn)
        assert first_version == SCHEMA_VERSION
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == SCHEMA_VERSION

        second_version = migrate(conn)
        assert second_version == SCHEMA_VERSION
        user_version_again = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version_again == SCHEMA_VERSION
    finally:
        conn.close()


def test_file_database_in_nested_directory(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "folder" / "worktime.db"
    assert not db_path.parent.exists()

    conn1 = open_database(db_path)
    try:
        conn1.execute("INSERT INTO workers (name) VALUES (?)", ("Alice",))
    finally:
        conn1.close()

    assert db_path.exists()

    conn2 = open_database(db_path)
    try:
        row = conn2.execute("SELECT name FROM workers WHERE name = ?", ("Alice",)).fetchone()
        assert row is not None
        assert row["name"] == "Alice"
        user_version = conn2.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == SCHEMA_VERSION
    finally:
        conn2.close()


def test_connection_pragmas() -> None:
    conn = connect(":memory:")
    try:
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]
        recursive_triggers = conn.execute("PRAGMA recursive_triggers").fetchone()[0]

        assert foreign_keys == 1
        assert busy_timeout == 5000
        assert synchronous == 2
        assert recursive_triggers == 1
    finally:
        conn.close()


def test_row_factory_accessible_by_column_name() -> None:
    conn = open_database(":memory:")
    try:
        conn.execute("INSERT INTO workers (name, phone) VALUES (?, ?)", ("Bob", "12345"))
        row = conn.execute(
            "SELECT id, name, phone FROM workers WHERE name = ?", ("Bob",)
        ).fetchone()
        assert row is not None
        assert row["id"] == 1
        assert row["name"] == "Bob"
        assert row["phone"] == "12345"
    finally:
        conn.close()


def test_migrate_rejects_newer_database() -> None:
    conn = connect(":memory:")
    try:
        conn.execute("PRAGMA user_version = 99")
        with pytest.raises(DatabaseVersionError):
            migrate(conn)

        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == 99
    finally:
        conn.close()


def test_migration_atomicity_rolls_back_failed_migration() -> None:
    custom_migrations = (
        ("CREATE TABLE phase_one (id INTEGER PRIMARY KEY);",),
        (
            "CREATE TABLE phase_two (id INTEGER PRIMARY KEY);",
            "INVALID SQL SYNTAX HERE;",
        ),
    )

    conn = connect(":memory:")
    try:
        with pytest.raises(sqlite3.OperationalError):
            migrate(conn, migrations=custom_migrations)

        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == 1

        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'phase_%'"
            ).fetchall()
        ]
        assert "phase_one" in tables
        assert "phase_two" not in tables
    finally:
        conn.close()


def test_write_transaction_commit_and_rollback() -> None:
    conn = connect(":memory:")
    try:
        conn.execute("CREATE TABLE counter (val INTEGER)")
        conn.execute("INSERT INTO counter VALUES (1)")

        with write_transaction(conn):
            conn.execute("UPDATE counter SET val = 2")

        row = conn.execute("SELECT val FROM counter").fetchone()
        assert row is not None
        assert row[0] == 2

        with pytest.raises(RuntimeError):
            with write_transaction(conn):
                conn.execute("UPDATE counter SET val = 3")
                raise RuntimeError("failure")

        row_after_fail = conn.execute("SELECT val FROM counter").fetchone()
        assert row_after_fail is not None
        assert row_after_fail[0] == 2
        assert not conn.in_transaction
    finally:
        conn.close()


def test_write_transaction_disallows_nesting() -> None:
    conn = connect(":memory:")
    try:
        with write_transaction(conn):
            with pytest.raises(DatabaseError, match="nested"):
                with write_transaction(conn):
                    pass
    finally:
        conn.close()


def test_default_db_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake_appdata = tmp_path / "AppData" / "Roaming"
    fake_home = tmp_path / "Home"
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    monkeypatch.setenv("APPDATA", str(fake_appdata))
    path = default_db_path()
    assert path == fake_appdata / "WorkTime" / "worktime.db"
    assert not path.exists()
    assert not (fake_appdata / "WorkTime").exists()

    monkeypatch.delenv("APPDATA", raising=False)
    home_path = default_db_path()
    assert home_path == fake_home / "WorkTime" / "worktime.db"
    assert not home_path.exists()
    assert not (fake_home / "WorkTime").exists()


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit])
def test_write_transaction_base_exception_rollback(exc_type: type[BaseException]) -> None:
    conn = connect(":memory:")
    try:
        conn.execute("CREATE TABLE counter (val INTEGER)")
        conn.execute("INSERT INTO counter VALUES (1)")
        with pytest.raises(exc_type):
            with write_transaction(conn):
                conn.execute("UPDATE counter SET val = 2")
                raise exc_type()
        row = conn.execute("SELECT val FROM counter").fetchone()
        assert row is not None
        assert row[0] == 1
        assert not conn.in_transaction
    finally:
        conn.close()


def test_database_migration_upgrade() -> None:
    raw = sqlite3.connect(":memory:", isolation_level=None)
    raw.row_factory = sqlite3.Row
    try:
        v1 = migrate(raw, MIGRATIONS[:1])
        assert v1 == 1

        raw.execute(
            "INSERT INTO workers (id, name, phone, note, archived) VALUES (1, 'Alice', '', '', 0)"
        )
        raw.execute(
            "INSERT INTO sessions (id, worker_id, start_at, end_at, note) "
            "VALUES (1, 1, '2026-11-06T09:00:00', '2026-11-06T17:00:00', 'sess')"
        )
        raw.execute(
            "INSERT INTO money_transactions (id, worker_id, kind, amount, occurred_on, note) "
            "VALUES (1, 1, 'advance', 1000, '2026-11-06', 'tx')"
        )
        raw.execute(
            """INSERT INTO settlements (
                id, worker_id, settled_on, total_minutes, wage,
                advances_total, prepayments_total, deductions_total,
                previous_balance, payable, paid, new_balance, note
            ) VALUES (1, 1, '2026-11-06', 480, 50000, 1000, 0, 0, 0, 49000, 49000, 0, 'set')"""
        )
        raw.execute("UPDATE sessions SET settlement_id = 1 WHERE id = 1")
        raw.execute("UPDATE money_transactions SET settlement_id = 1 WHERE id = 1")

        before_workers = [
            tuple(r) for r in raw.execute("SELECT * FROM workers ORDER BY id").fetchall()
        ]
        before_sessions = [
            tuple(r) for r in raw.execute("SELECT * FROM sessions ORDER BY id").fetchall()
        ]
        before_txs = [
            tuple(r) for r in raw.execute("SELECT * FROM money_transactions ORDER BY id").fetchall()
        ]
        before_settlements = [
            tuple(r) for r in raw.execute("SELECT * FROM settlements ORDER BY id").fetchall()
        ]

        v2 = migrate(raw)
        assert v2 == 2
        user_version = raw.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == 2

        assert [
            tuple(r) for r in raw.execute("SELECT * FROM workers ORDER BY id").fetchall()
        ] == before_workers
        assert [
            tuple(r) for r in raw.execute("SELECT * FROM sessions ORDER BY id").fetchall()
        ] == before_sessions
        assert [
            tuple(r) for r in raw.execute("SELECT * FROM money_transactions ORDER BY id").fetchall()
        ] == before_txs
        assert [
            tuple(r) for r in raw.execute("SELECT * FROM settlements ORDER BY id").fetchall()
        ] == before_settlements

        triggers = {
            r[0]
            for r in raw.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'").fetchall()
        }
        new_triggers = {
            "trg_sessions_no_preset_lock",
            "trg_money_no_preset_lock",
            "trg_workers_no_replace",
            "trg_sessions_no_replace",
            "trg_money_no_replace",
            "trg_settlements_no_replace",
        }
        assert new_triggers.issubset(triggers)

        with pytest.raises(sqlite3.IntegrityError, match="record locked"):
            raw.execute("UPDATE sessions SET note = 'fail' WHERE id = 1")

        with pytest.raises(sqlite3.IntegrityError, match="record locked"):
            raw.execute("UPDATE money_transactions SET note = 'fail' WHERE id = 1")

        with pytest.raises(sqlite3.IntegrityError, match="settlement is immutable"):
            raw.execute("UPDATE settlements SET note = 'fail' WHERE id = 1")

        with pytest.raises(sqlite3.IntegrityError, match="new records cannot be pre-locked"):
            raw.execute(
                "INSERT INTO sessions (worker_id, start_at, end_at, settlement_id) "
                "VALUES (1, '2026-11-07T09:00:00', '2026-11-07T17:00:00', 1)"
            )

        with pytest.raises(sqlite3.IntegrityError, match="record already exists"):
            raw.execute(
                "INSERT OR REPLACE INTO sessions (id, worker_id, start_at, end_at, note) "
                "VALUES (1, 1, '2026-11-06T09:00:00', '2026-11-06T17:00:00', 'hacked')"
            )
    finally:
        raw.close()


def test_schema_sql_hygiene() -> None:
    for migration in MIGRATIONS:
        for statement in migration:
            assert "--" not in statement

    schema_file = Path("src/worktime/data/schema.py")
    tree = ast.parse(schema_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not isinstance(node, ast.JoinedStr), "schema.py must not contain f-strings"
