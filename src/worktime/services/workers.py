"""Worker service managing worker profiles, status lifecycle, and summary views."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

from worktime.data import (
    SessionRepository,
    SettlementRepository,
    WorkerRepository,
    write_transaction,
)
from worktime.domain import Worker
from worktime.services._rules import ensure_no_open_session
from worktime.services.errors import RecordNotFoundError

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerSummary:
    """Worker summary with balance in centimes and optional open session start timestamp."""

    worker: Worker
    balance: int
    open_since: datetime | None


class WorkerService:
    """Service managing worker lifecycle, profiles, and summary views."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize worker service with an active SQLite database connection."""
        self._conn = conn
        self._workers = WorkerRepository(conn)
        self._sessions = SessionRepository(conn)
        self._settlements = SettlementRepository(conn)

    def add_worker(self, *, name: str, phone: str = "", note: str = "") -> Worker:
        """Create and persist a new active worker entity."""
        with write_transaction(self._conn):
            return self._workers.add(Worker(name=name, phone=phone, note=note))

    def update_worker(
        self,
        worker_id: int,
        *,
        name: str,
        phone: str = "",
        note: str = "",
    ) -> Worker:
        """Update worker contact information and note while preserving archive status."""
        with write_transaction(self._conn):
            existing = self._workers.get(worker_id)
            if existing is None:
                raise RecordNotFoundError("worker not found")
            updated = replace(existing, name=name, phone=phone, note=note)
            return self._workers.update(updated)

    def archive_worker(self, worker_id: int) -> Worker:
        """Archive a worker without open sessions or return unchanged if already archived."""
        with write_transaction(self._conn):
            existing = self._workers.get(worker_id)
            if existing is None:
                raise RecordNotFoundError("worker not found")
            if existing.archived:
                return existing
            ensure_no_open_session(self._sessions, worker_id)
            updated = replace(existing, archived=True)
            return self._workers.update(updated)

    def restore_worker(self, worker_id: int) -> Worker:
        """Restore an archived worker or return unchanged if already active."""
        with write_transaction(self._conn):
            existing = self._workers.get(worker_id)
            if existing is None:
                raise RecordNotFoundError("worker not found")
            if not existing.archived:
                return existing
            updated = replace(existing, archived=False)
            return self._workers.update(updated)

    def get_worker(self, worker_id: int) -> Worker | None:
        """Retrieve a worker by ID or return None if not found."""
        return self._workers.get(worker_id)

    def list_workers(self, *, include_archived: bool = False) -> list[Worker]:
        """List workers sorted by name, optionally including archived workers."""
        return self._workers.list_workers(include_archived=include_archived)

    def list_summaries(self, *, include_archived: bool = False) -> list[WorkerSummary]:
        """List worker summaries in list_workers order with balances and open sessions."""
        workers = self._workers.list_workers(include_archived=include_archived)
        balances = self._settlements.latest_balances()
        open_sessions = self._sessions.list_open()
        open_map = {s.worker_id: s.start for s in open_sessions}
        return [
            WorkerSummary(
                worker=w,
                balance=balances.get(w.id, 0) if w.id is not None else 0,
                open_since=open_map.get(w.id) if w.id is not None else None,
            )
            for w in workers
        ]
