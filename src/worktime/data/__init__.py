"""SQLite data layer foundation and repositories."""

from worktime.data.database import (
    connect,
    default_db_path,
    migrate,
    open_database,
    write_transaction,
)
from worktime.data.errors import (
    DatabaseError,
    DatabaseVersionError,
    DuplicateWorkerError,
    OpenSessionExistsError,
    RecordNotFoundError,
)
from worktime.data.schema import MIGRATIONS, SCHEMA_VERSION
from worktime.data.sessions import SessionRepository
from worktime.data.settlements import SettlementRepository
from worktime.data.transactions import TransactionRepository
from worktime.data.workers import WorkerRepository

__all__ = [
    "DatabaseError",
    "DatabaseVersionError",
    "DuplicateWorkerError",
    "MIGRATIONS",
    "OpenSessionExistsError",
    "RecordNotFoundError",
    "SCHEMA_VERSION",
    "SessionRepository",
    "SettlementRepository",
    "TransactionRepository",
    "WorkerRepository",
    "connect",
    "default_db_path",
    "migrate",
    "open_database",
    "write_transaction",
]
