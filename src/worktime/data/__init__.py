"""SQLite data layer foundation."""

from worktime.data.database import (
    connect,
    default_db_path,
    migrate,
    open_database,
    write_transaction,
)
from worktime.data.errors import DatabaseError, DatabaseVersionError
from worktime.data.schema import MIGRATIONS, SCHEMA_VERSION

__all__ = [
    "DatabaseError",
    "DatabaseVersionError",
    "MIGRATIONS",
    "SCHEMA_VERSION",
    "connect",
    "default_db_path",
    "migrate",
    "open_database",
    "write_transaction",
]
