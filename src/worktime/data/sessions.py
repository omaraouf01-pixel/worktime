"""Session data repository."""

import sqlite3
from datetime import date

from worktime.data._mapping import (
    day_start,
    next_day_start,
    require_lastrowid,
    row_to_session,
    to_db_date,
    to_db_datetime,
    translate_integrity_error,
)
from worktime.data.errors import (
    DatabaseError,
    RecordNotFoundError,
)
from worktime.domain.session import Session


class SessionRepository:
    """Repository for Session domain entities."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize repository with a database connection."""
        self._conn = conn

    def add(self, session: Session) -> Session:
        """Insert a new session and return it with assigned id."""
        if session.id is not None:
            raise DatabaseError("Cannot add session that already has an id")
        if session.settlement_id is not None:
            raise DatabaseError("new records cannot carry a settlement")
        start_at_str = to_db_datetime(session.start)
        end_at_str = to_db_datetime(session.end) if session.end is not None else None
        try:
            cursor = self._conn.execute(
                ("INSERT INTO sessions (worker_id, start_at, end_at, note) VALUES (?, ?, ?, ?)"),
                (
                    session.worker_id,
                    start_at_str,
                    end_at_str,
                    session.note,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, context="session") from exc
        session_id = require_lastrowid(cursor)
        stored = self.get(session_id)
        if stored is None:
            raise DatabaseError("Session not found after insert")
        return stored

    def get(self, session_id: int) -> Session | None:
        """Retrieve a session by id, or None if not found."""
        cursor = self._conn.execute(
            (
                "SELECT id, worker_id, start_at, end_at, note, settlement_id "
                "FROM sessions WHERE id = ?"
            ),
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return row_to_session(row)

    def get_open(self, worker_id: int) -> Session | None:
        """Retrieve the open session for a worker, or None if none open."""
        cursor = self._conn.execute(
            (
                "SELECT id, worker_id, start_at, end_at, note, settlement_id "
                "FROM sessions WHERE worker_id = ? AND end_at IS NULL"
            ),
            (worker_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return row_to_session(row)

    def list_open(self) -> list[Session]:
        """List all open sessions across all workers ordered by start_at then id."""
        cursor = self._conn.execute(
            "SELECT id, worker_id, start_at, end_at, note, settlement_id "
            "FROM sessions WHERE end_at IS NULL ORDER BY start_at, id"
        )
        return [row_to_session(row) for row in cursor.fetchall()]

    def list_for_worker(
        self,
        worker_id: int,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        unsettled_only: bool = False,
    ) -> list[Session]:
        """List sessions for a worker filtered by optional date bounds and settlement status."""
        if from_date is not None:
            to_db_date(from_date)
        if to_date is not None:
            to_db_date(to_date)
        if from_date is not None and to_date is not None and from_date > to_date:
            raise DatabaseError("from_date cannot be after to_date")

        clauses = ["worker_id = ?"]
        params: list[object] = [worker_id]

        if from_date is not None:
            clauses.append("start_at >= ?")
            params.append(day_start(from_date))
        if to_date is not None:
            clauses.append("start_at < ?")
            params.append(next_day_start(to_date))
        if unsettled_only:
            clauses.append("settlement_id IS NULL")

        where_clause = " AND ".join(clauses)
        query = (
            "SELECT id, worker_id, start_at, end_at, note, settlement_id "
            "FROM sessions WHERE " + where_clause + " ORDER BY start_at, id"
        )
        cursor = self._conn.execute(query, params)
        return [row_to_session(row) for row in cursor.fetchall()]

    def update(self, session: Session) -> Session:
        """Update mutable fields of a session and return the updated entity."""
        if session.id is None:
            raise DatabaseError("Cannot update session without an id")
        start_at_str = to_db_datetime(session.start)
        end_at_str = to_db_datetime(session.end) if session.end is not None else None
        try:
            cursor = self._conn.execute(
                "UPDATE sessions SET start_at = ?, end_at = ?, note = ? WHERE id = ?",
                (start_at_str, end_at_str, session.note, session.id),
            )
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, context="session") from exc
        if cursor.rowcount == 0:
            raise RecordNotFoundError("Session not found")
        stored = self.get(session.id)
        if stored is None:
            raise DatabaseError("Session not found after update")
        return stored

    def delete(self, session_id: int) -> None:
        """Delete an unlocked session by id."""
        try:
            cursor = self._conn.execute(
                "DELETE FROM sessions WHERE id = ?",
                (session_id,),
            )
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, context="session") from exc
        if cursor.rowcount == 0:
            raise RecordNotFoundError("Session not found")
