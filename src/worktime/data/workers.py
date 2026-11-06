"""Worker data repository."""

import sqlite3

from worktime.data._mapping import (
    require_lastrowid,
    row_to_worker,
    translate_integrity_error,
)
from worktime.data.errors import (
    DatabaseError,
    RecordNotFoundError,
)
from worktime.domain.worker import Worker


class WorkerRepository:
    """Repository for Worker domain entities."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize repository with a database connection."""
        self._conn = conn

    def add(self, worker: Worker) -> Worker:
        """Insert a new worker and return it with assigned id."""
        if worker.id is not None:
            raise DatabaseError("Cannot add worker that already has an id")
        try:
            cursor = self._conn.execute(
                "INSERT INTO workers (name, phone, note, archived) VALUES (?, ?, ?, ?)",
                (worker.name, worker.phone, worker.note, 1 if worker.archived else 0),
            )
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, context="worker") from exc
        worker_id = require_lastrowid(cursor)
        stored = self.get(worker_id)
        if stored is None:
            raise DatabaseError("Worker not found after insert")
        return stored

    def get(self, worker_id: int) -> Worker | None:
        """Retrieve a worker by id, or None if not found."""
        cursor = self._conn.execute(
            "SELECT id, name, phone, note, archived FROM workers WHERE id = ?",
            (worker_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return row_to_worker(row)

    def list_workers(self, *, include_archived: bool = False) -> list[Worker]:
        """List workers ordered by case-insensitive name then id."""
        if include_archived:
            query = (
                "SELECT id, name, phone, note, archived "
                "FROM workers ORDER BY name COLLATE NOCASE, id"
            )
        else:
            query = (
                "SELECT id, name, phone, note, archived "
                "FROM workers WHERE archived = 0 ORDER BY name COLLATE NOCASE, id"
            )
        cursor = self._conn.execute(query)
        return [row_to_worker(row) for row in cursor.fetchall()]

    def update(self, worker: Worker) -> Worker:
        """Update an existing worker's fields and return the updated entity."""
        if worker.id is None:
            raise DatabaseError("Cannot update worker without an id")
        try:
            cursor = self._conn.execute(
                ("UPDATE workers SET name = ?, phone = ?, note = ?, archived = ? WHERE id = ?"),
                (
                    worker.name,
                    worker.phone,
                    worker.note,
                    1 if worker.archived else 0,
                    worker.id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, context="worker") from exc
        if cursor.rowcount == 0:
            raise RecordNotFoundError("Worker not found")
        stored = self.get(worker.id)
        if stored is None:
            raise DatabaseError("Worker not found after update")
        return stored
