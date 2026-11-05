"""SQLite database connection, transaction management, and migrations."""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from worktime.data.errors import DatabaseError, DatabaseVersionError
from worktime.data.schema import MIGRATIONS


def default_db_path() -> Path:
    """Return default database file path."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "WorkTime" / "worktime.db"
    return Path.home() / "WorkTime" / "worktime.db"


def connect(path: Path | str) -> sqlite3.Connection:
    """Create and configure a new SQLite connection."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


@contextmanager
def write_transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Execute a context block inside an immediate write transaction."""
    if conn.in_transaction:
        raise DatabaseError("Cannot start a nested transaction")
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def migrate(
    conn: sqlite3.Connection,
    migrations: tuple[tuple[str, ...], ...] = MIGRATIONS,
) -> int:
    """Apply pending migrations to the database and return the final schema version."""
    cursor = conn.execute("PRAGMA user_version")
    row = cursor.fetchone()
    current_version = int(row[0]) if row else 0

    if current_version > len(migrations):
        raise DatabaseVersionError(
            "Database version "
            + str(current_version)
            + " is newer than application version "
            + str(len(migrations))
        )

    for version_index in range(current_version, len(migrations)):
        migration = migrations[version_index]
        target_version = version_index + 1
        with write_transaction(conn):
            for statement in migration:
                conn.execute(statement)
            conn.execute("PRAGMA user_version = " + str(target_version))

    return len(migrations)


def open_database(path: Path | str) -> sqlite3.Connection:
    """Connect to the database and apply all pending migrations."""
    conn = connect(path)
    migrate(conn)
    return conn
