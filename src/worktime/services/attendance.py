"""Attendance service managing sessions, clock-in/out, and manual entries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time
from typing import TYPE_CHECKING

from worktime.data import (
    SessionRepository,
    WorkerRepository,
    write_transaction,
)
from worktime.domain import (
    Session,
    ValidationError,
    resolve_end,
    total_minutes,
)
from worktime.services._rules import (
    ensure_no_overlap,
    ensure_not_in_future,
    require_worker,
)
from worktime.services.clock import Clock, system_clock
from worktime.services.errors import (
    NoOpenSessionError,
    OpenSessionExistsError,
    RecordNotFoundError,
)

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True, kw_only=True)
class ManualEntry:
    """Manual entry result wrapping saved session and midnight-crossing indicator."""

    session: Session
    crosses_midnight: bool


class AttendanceService:
    """Service managing attendance tracking, clock-in/out, and manual session editing."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock = system_clock) -> None:
        """Initialize attendance service with database connection and injected clock."""
        self._conn = conn
        self._clock = clock
        self._workers = WorkerRepository(conn)
        self._sessions = SessionRepository(conn)

    def start_work(self, worker_id: int) -> Session:
        """Clock in an active worker by opening an unbounded session at current clock time."""
        with write_transaction(self._conn):
            require_worker(self._workers, worker_id, allow_archived=False)
            if self._sessions.get_open(worker_id) is not None:
                raise OpenSessionExistsError("Worker already has an open session.")
            now = self._clock()
            candidate = Session(worker_id=worker_id, start=now)
            ensure_no_overlap(self._sessions, candidate)
            return self._sessions.add(candidate)

    def stop_work(self, worker_id: int) -> Session:
        """Clock out a worker by closing their open session at current clock time."""
        with write_transaction(self._conn):
            require_worker(self._workers, worker_id, allow_archived=True)
            open_session = self._sessions.get_open(worker_id)
            if open_session is None:
                raise NoOpenSessionError("Worker has no open session.")
            now = self._clock()
            closed = open_session.close(now)
            ensure_no_overlap(self._sessions, closed, ignore_id=open_session.id)
            return self._sessions.update(closed)

    def add_manual(
        self,
        worker_id: int,
        *,
        day: date,
        start_clock: time,
        end_clock: time,
        note: str = "",
    ) -> ManualEntry:
        """Create a completed manual session with minute precision, resolving overnight bounds."""
        with write_transaction(self._conn):
            require_worker(self._workers, worker_id, allow_archived=False)
            if isinstance(day, datetime) or not isinstance(day, date):
                raise ValidationError("Field 'day' must be a date.")
            if isinstance(start_clock, datetime) or not isinstance(start_clock, time):
                raise ValidationError("Field 'start_clock' must be a time.")
            if start_clock.tzinfo is not None:
                raise ValidationError("Field 'start_clock' must be a naive time.")
            if isinstance(end_clock, datetime) or not isinstance(end_clock, time):
                raise ValidationError("Field 'end_clock' must be a time.")
            if end_clock.tzinfo is not None:
                raise ValidationError("Field 'end_clock' must be a naive time.")

            s_clock = start_clock.replace(second=0, microsecond=0)
            e_clock = end_clock.replace(second=0, microsecond=0)
            start = datetime.combine(day, s_clock)
            end, crosses = resolve_end(start, e_clock)
            ensure_not_in_future(end, self._clock())
            candidate = Session(worker_id=worker_id, start=start, end=end, note=note)
            ensure_no_overlap(self._sessions, candidate)
            saved = self._sessions.add(candidate)
            return ManualEntry(session=saved, crosses_midnight=crosses)

    def update_session(
        self,
        session_id: int,
        *,
        start: datetime,
        end: datetime,
        note: str = "",
    ) -> Session:
        """Update session interval and note, rejecting locked records and future timestamps."""
        with write_transaction(self._conn):
            existing = self._sessions.get(session_id)
            if existing is None:
                raise RecordNotFoundError("Session not found.")
            existing.ensure_editable()
            if (
                not isinstance(start, datetime)
                or start.tzinfo is not None
                or start.microsecond != 0
            ):
                raise ValidationError("Field 'start' must be a naive datetime with microsecond=0.")
            if not isinstance(end, datetime) or end.tzinfo is not None or end.microsecond != 0:
                raise ValidationError("Field 'end' must be a naive datetime with microsecond=0.")

            updated = replace(existing, start=start, end=end, note=note)
            ensure_not_in_future(end, self._clock())
            ensure_no_overlap(self._sessions, updated, ignore_id=session_id)
            return self._sessions.update(updated)

    def delete_session(self, session_id: int) -> None:
        """Delete an unlocked session by ID or raise RecordNotFoundError or RecordLockedError."""
        with write_transaction(self._conn):
            existing = self._sessions.get(session_id)
            if existing is None:
                raise RecordNotFoundError("Session not found.")
            existing.ensure_editable()
            self._sessions.delete(session_id)

    def get_open_session(self, worker_id: int) -> Session | None:
        """Return the currently open session for the worker, or None if none open."""
        return self._sessions.get_open(worker_id)

    def list_open_sessions(self) -> list[Session]:
        """List all open sessions across all workers ordered by start time then ID."""
        return self._sessions.list_open()

    def list_sessions(
        self,
        worker_id: int,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        unsettled_only: bool = False,
    ) -> list[Session]:
        """List worker sessions filtered by date bounds and unsettled status."""
        return self._sessions.list_for_worker(
            worker_id,
            from_date=from_date,
            to_date=to_date,
            unsettled_only=unsettled_only,
        )

    def unsettled_minutes(self, worker_id: int) -> int:
        """Return total minutes of unsettled sessions, counting open session up to now."""
        sessions = self._sessions.list_for_worker(worker_id, unsettled_only=True)
        return total_minutes(sessions, now=self._clock())
