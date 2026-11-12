"""Private database mapping and validation helpers."""

import sqlite3
from datetime import date, datetime, timedelta

from worktime.data.errors import (
    DatabaseError,
    DuplicateWorkerError,
    OpenSessionExistsError,
    RecordNotFoundError,
)
from worktime.domain.errors import RecordLockedError, ValidationError
from worktime.domain.session import Session
from worktime.domain.settlement import Settlement
from worktime.domain.transaction import Transaction, TransactionKind
from worktime.domain.worker import Worker


def to_db_datetime(value: datetime) -> str:
    """Convert naive datetime without microseconds to ISO string."""
    if not isinstance(value, datetime) or value.tzinfo is not None or value.microsecond != 0:
        raise DatabaseError("Expected naive datetime with zero microseconds")
    return value.isoformat(timespec="seconds")


def from_db_datetime(text: str) -> datetime:
    """Parse ISO datetime string to naive datetime without microseconds."""
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DatabaseError("Invalid ISO datetime: " + text) from exc
    if dt.tzinfo is not None or dt.microsecond != 0:
        raise DatabaseError("Expected naive datetime without microseconds")
    return dt


def to_db_date(value: date) -> str:
    """Convert date to ISO string, rejecting datetimes."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise DatabaseError("Expected date instance, not datetime")
    return value.isoformat()


def from_db_date(text: str) -> date:
    """Parse ISO date string to date."""
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise DatabaseError("Invalid ISO date: " + text) from exc


def day_start(d: date) -> str:
    """Return start of day ISO timestamp string."""
    return to_db_date(d) + "T00:00:00"


def next_day_start(d: date) -> str:
    """Return start of next day ISO timestamp string."""
    to_db_date(d)
    return (d + timedelta(days=1)).isoformat() + "T00:00:00"


def require_lastrowid(cursor: sqlite3.Cursor) -> int:
    """Return cursor lastrowid as an int or raise DatabaseError."""
    rowid = cursor.lastrowid
    if rowid is None:
        raise DatabaseError("Cursor has no lastrowid")
    return rowid


def translate_integrity_error(exc: sqlite3.IntegrityError, *, context: str) -> Exception:
    """Translate SQLite integrity errors into domain or data layer exceptions."""
    msg = str(exc)
    if "cannot lock an open session" in msg:
        return ValidationError(msg)
    if "settlement belongs to another worker" in msg:
        return ValidationError(msg)
    if "record locked" in msg:
        return RecordLockedError(msg)
    if "FOREIGN KEY" in msg:
        return RecordNotFoundError("worker not found")
    if "UNIQUE" in msg:
        if context == "worker":
            return DuplicateWorkerError(msg)
        if context == "session":
            return OpenSessionExistsError(msg)
    return DatabaseError(msg)


def _int(row: sqlite3.Row, key: str) -> int:
    """Extract an integer column value."""
    val: object = row[key]
    if isinstance(val, bool) or not isinstance(val, int):
        raise DatabaseError("Expected int for column: " + key)
    return val


def _opt_int(row: sqlite3.Row, key: str) -> int | None:
    """Extract an optional integer column value."""
    val: object = row[key]
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, int):
        raise DatabaseError("Expected int or None for column: " + key)
    return val


def _str(row: sqlite3.Row, key: str) -> str:
    """Extract a string column value."""
    val: object = row[key]
    if not isinstance(val, str):
        raise DatabaseError("Expected str for column: " + key)
    return val


def _opt_str(row: sqlite3.Row, key: str) -> str | None:
    """Extract an optional string column value."""
    val: object = row[key]
    if val is None:
        return None
    if not isinstance(val, str):
        raise DatabaseError("Expected str or None for column: " + key)
    return val


def _bool(row: sqlite3.Row, key: str) -> bool:
    """Extract a boolean column value."""
    val: object = row[key]
    if isinstance(val, bool):
        return val
    if isinstance(val, int):
        return bool(val)
    raise DatabaseError("Expected bool or int for column: " + key)


def row_to_worker(row: sqlite3.Row) -> Worker:
    """Convert database row to Worker entity."""
    return Worker(
        id=_int(row, "id"),
        name=_str(row, "name"),
        phone=_str(row, "phone"),
        note=_str(row, "note"),
        archived=_bool(row, "archived"),
    )


def row_to_session(row: sqlite3.Row) -> Session:
    """Convert database row to Session entity."""
    end_val = _opt_str(row, "end_at")
    return Session(
        id=_int(row, "id"),
        worker_id=_int(row, "worker_id"),
        start=from_db_datetime(_str(row, "start_at")),
        end=from_db_datetime(end_val) if end_val is not None else None,
        note=_str(row, "note"),
        settlement_id=_opt_int(row, "settlement_id"),
    )


def row_to_transaction(row: sqlite3.Row) -> Transaction:
    """Convert database row to Transaction entity."""
    return Transaction(
        id=_int(row, "id"),
        worker_id=_int(row, "worker_id"),
        kind=TransactionKind(_str(row, "kind")),
        amount=_int(row, "amount"),
        occurred_on=from_db_date(_str(row, "occurred_on")),
        note=_str(row, "note"),
        settlement_id=_opt_int(row, "settlement_id"),
    )


def row_to_settlement(row: sqlite3.Row) -> Settlement:
    """Convert database row to Settlement entity."""
    return Settlement(
        id=_int(row, "id"),
        worker_id=_int(row, "worker_id"),
        settled_on=from_db_date(_str(row, "settled_on")),
        total_minutes=_int(row, "total_minutes"),
        wage=_int(row, "wage"),
        advances_total=_int(row, "advances_total"),
        prepayments_total=_int(row, "prepayments_total"),
        deductions_total=_int(row, "deductions_total"),
        previous_balance=_int(row, "previous_balance"),
        payable=_int(row, "payable"),
        paid=_int(row, "paid"),
        new_balance=_int(row, "new_balance"),
        note=_str(row, "note"),
    )
