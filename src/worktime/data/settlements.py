"""Settlement data repository."""

import sqlite3
from collections.abc import Sequence

from worktime.data._mapping import (
    _int,
    require_lastrowid,
    row_to_session,
    row_to_settlement,
    row_to_transaction,
    to_db_date,
    translate_integrity_error,
)
from worktime.data.errors import (
    DatabaseError,
    RecordNotFoundError,
)
from worktime.domain.errors import RecordLockedError
from worktime.domain.session import Session
from worktime.domain.settlement import Settlement
from worktime.domain.transaction import Transaction


class SettlementRepository:
    """Repository for Settlement domain entities."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize repository with a database connection."""
        self._conn = conn

    def add(self, settlement: Settlement) -> Settlement:
        """Insert a new settlement and return it with assigned id."""
        if settlement.id is not None:
            raise DatabaseError("Cannot add settlement that already has an id")
        settled_on_str = to_db_date(settlement.settled_on)
        try:
            cursor = self._conn.execute(
                (
                    "INSERT INTO settlements ("
                    "worker_id, settled_on, total_minutes, wage, "
                    "advances_total, prepayments_total, deductions_total, "
                    "previous_balance, payable, paid, new_balance, note"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    settlement.worker_id,
                    settled_on_str,
                    settlement.total_minutes,
                    settlement.wage,
                    settlement.advances_total,
                    settlement.prepayments_total,
                    settlement.deductions_total,
                    settlement.previous_balance,
                    settlement.payable,
                    settlement.paid,
                    settlement.new_balance,
                    settlement.note,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, context="settlement") from exc
        settlement_id = require_lastrowid(cursor)
        stored = self.get(settlement_id)
        if stored is None:
            raise DatabaseError("Settlement not found after insert")
        return stored

    def get(self, settlement_id: int) -> Settlement | None:
        """Retrieve a settlement by id, or None if not found."""
        cursor = self._conn.execute(
            (
                "SELECT id, worker_id, settled_on, total_minutes, wage, "
                "advances_total, prepayments_total, deductions_total, "
                "previous_balance, payable, paid, new_balance, note "
                "FROM settlements WHERE id = ?"
            ),
            (settlement_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return row_to_settlement(row)

    def list_for_worker(self, worker_id: int) -> list[Settlement]:
        """List settlements for a worker ordered by id ascending."""
        cursor = self._conn.execute(
            (
                "SELECT id, worker_id, settled_on, total_minutes, wage, "
                "advances_total, prepayments_total, deductions_total, "
                "previous_balance, payable, paid, new_balance, note "
                "FROM settlements WHERE worker_id = ? ORDER BY id ASC"
            ),
            (worker_id,),
        )
        return [row_to_settlement(row) for row in cursor.fetchall()]

    def last_balance(self, worker_id: int) -> int:
        """Return the new_balance of the worker's settlement with highest id, or 0."""
        cursor = self._conn.execute(
            "SELECT new_balance FROM settlements WHERE worker_id = ? ORDER BY id DESC LIMIT 1",
            (worker_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return 0
        return _int(row, "new_balance")

    def latest_balances(self) -> dict[int, int]:
        """Return latest new_balance per worker keyed by worker_id."""
        cursor = self._conn.execute(
            "SELECT s.worker_id, s.new_balance "
            "FROM settlements s "
            "WHERE s.id = ("
            "    SELECT MAX(sub.id) FROM settlements sub WHERE sub.worker_id = s.worker_id"
            ")"
        )
        return {_int(row, "worker_id"): _int(row, "new_balance") for row in cursor.fetchall()}

    def attach_records(
        self,
        settlement_id: int,
        *,
        session_ids: Sequence[int],
        transaction_ids: Sequence[int],
    ) -> None:
        """Attach records to settlement; caller must manage write_transaction for atomicity."""
        for sid in session_ids:
            if isinstance(sid, bool) or not isinstance(sid, int) or sid < 1:
                raise DatabaseError("Invalid session id: " + str(sid))
        if len(session_ids) != len(set(session_ids)):
            raise DatabaseError("Duplicate session id in session_ids")

        for tid in transaction_ids:
            if isinstance(tid, bool) or not isinstance(tid, int) or tid < 1:
                raise DatabaseError("Invalid transaction id: " + str(tid))
        if len(transaction_ids) != len(set(transaction_ids)):
            raise DatabaseError("Duplicate transaction id in transaction_ids")

        if self.get(settlement_id) is None:
            raise RecordNotFoundError("settlement not found")

        for sid in session_ids:
            try:
                cursor = self._conn.execute(
                    "UPDATE sessions SET settlement_id = ? WHERE id = ? AND settlement_id IS NULL",
                    (settlement_id, sid),
                )
            except sqlite3.IntegrityError as exc:
                raise translate_integrity_error(exc, context="session") from exc
            if cursor.rowcount == 0:
                row = self._conn.execute(
                    "SELECT settlement_id FROM sessions WHERE id = ?",
                    (sid,),
                ).fetchone()
                if row is None:
                    raise RecordNotFoundError("Session not found")
                raise RecordLockedError("record already settled")

        for tid in transaction_ids:
            try:
                cursor = self._conn.execute(
                    (
                        "UPDATE money_transactions SET settlement_id = ? "
                        "WHERE id = ? AND settlement_id IS NULL"
                    ),
                    (settlement_id, tid),
                )
            except sqlite3.IntegrityError as exc:
                raise translate_integrity_error(exc, context="transaction") from exc
            if cursor.rowcount == 0:
                row = self._conn.execute(
                    "SELECT settlement_id FROM money_transactions WHERE id = ?",
                    (tid,),
                ).fetchone()
                if row is None:
                    raise RecordNotFoundError("Transaction not found")
                raise RecordLockedError("record already settled")

    def sessions_of(self, settlement_id: int) -> list[Session]:
        """List sessions attached to a settlement ordered by start_at then id."""
        cursor = self._conn.execute(
            (
                "SELECT id, worker_id, start_at, end_at, note, settlement_id "
                "FROM sessions WHERE settlement_id = ? ORDER BY start_at, id"
            ),
            (settlement_id,),
        )
        return [row_to_session(row) for row in cursor.fetchall()]

    def transactions_of(self, settlement_id: int) -> list[Transaction]:
        """List transactions attached to a settlement ordered by occurred_on then id."""
        cursor = self._conn.execute(
            (
                "SELECT id, worker_id, kind, amount, occurred_on, note, settlement_id "
                "FROM money_transactions WHERE settlement_id = ? ORDER BY occurred_on, id"
            ),
            (settlement_id,),
        )
        return [row_to_transaction(row) for row in cursor.fetchall()]
