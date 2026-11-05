import ast
import sqlite3
from pathlib import Path

import pytest

from worktime.data import (
    MIGRATIONS,
    DatabaseError,
    DatabaseVersionError,
    connect,
    default_db_path,
    migrate,
    open_database,
    write_transaction,
)


def test_memory_database_migration_idempotent() -> None:
    conn = connect(":memory:")
    try:
        first_version = migrate(conn)
        assert first_version == 1
        user_version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version == 1

        second_version = migrate(conn)
        assert second_version == 1
        user_version_again = conn.execute("PRAGMA user_version").fetchone()[0]
        assert user_version_again == 1
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
        assert user_version == 1
    finally:
        conn2.close()


def test_connection_pragmas() -> None:
    conn = connect(":memory:")
    try:
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        synchronous = conn.execute("PRAGMA synchronous").fetchone()[0]

        assert foreign_keys == 1
        assert busy_timeout == 5000
        assert synchronous == 2
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
    monkeypatch.setenv("APPDATA", str(fake_appdata))
    path = default_db_path()
    assert path == fake_appdata / "WorkTime" / "worktime.db"
    assert not path.exists()
    assert not (fake_appdata / "WorkTime").exists()

    monkeypatch.delenv("APPDATA", raising=False)
    home_path = default_db_path()
    assert home_path == Path.home() / "WorkTime" / "worktime.db"
    assert not (Path.home() / "WorkTime" / "worktime.db").exists()


def test_schema_sql_hygiene() -> None:
    for migration in MIGRATIONS:
        for statement in migration:
            assert "--" not in statement

    schema_file = Path("src/worktime/data/schema.py")
    tree = ast.parse(schema_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not isinstance(node, ast.JoinedStr), "schema.py must not contain f-strings"
