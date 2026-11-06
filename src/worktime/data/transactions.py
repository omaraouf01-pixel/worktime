"""Transaction data repository."""

import sqlite3
from datetime import date

from worktime.data._mapping import (
    require_lastrowid,
    row_to_transaction,
    to_db_date,
    translate_integrity_error,
)
from worktime.data.errors import (
    DatabaseError,
    RecordNotFoundError,
)
from worktime.domain.transaction import Transaction


class TransactionRepository:
    """Repository for Transaction domain entities."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        """Initialize repository with a database connection."""
        self._conn = conn

    def add(self, transaction: Transaction) -> Transaction:
        """Insert a new transaction and return it with assigned id."""
        if transaction.id is not None:
            raise DatabaseError("Cannot add transaction that already has an id")
        occurred_on_str = to_db_date(transaction.occurred_on)
        try:
            cursor = self._conn.execute(
                (
                    "INSERT INTO money_transactions "
                    "(worker_id, kind, amount, occurred_on, note, settlement_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)"
                ),
                (
                    transaction.worker_id,
                    transaction.kind.value,
                    transaction.amount,
                    occurred_on_str,
                    transaction.note,
                    transaction.settlement_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, context="transaction") from exc
        tx_id = require_lastrowid(cursor)
        stored = self.get(tx_id)
        if stored is None:
            raise DatabaseError("Transaction not found after insert")
        return stored

    def get(self, transaction_id: int) -> Transaction | None:
        """Retrieve a transaction by id, or None if not found."""
        cursor = self._conn.execute(
            (
                "SELECT id, worker_id, kind, amount, occurred_on, note, settlement_id "
                "FROM money_transactions WHERE id = ?"
            ),
            (transaction_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return row_to_transaction(row)

    def list_for_worker(
        self,
        worker_id: int,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        unsettled_only: bool = False,
    ) -> list[Transaction]:
        """List transactions for a worker filtered by optional date bounds and settlement status."""
        if from_date is not None:
            to_db_date(from_date)
        if to_date is not None:
            to_db_date(to_date)
        if from_date is not None and to_date is not None and from_date > to_date:
            raise DatabaseError("from_date cannot be after to_date")

        clauses = ["worker_id = ?"]
        params: list[object] = [worker_id]

        if from_date is not None:
            clauses.append("occurred_on >= ?")
            params.append(to_db_date(from_date))
        if to_date is not None:
            clauses.append("occurred_on <= ?")
            params.append(to_db_date(to_date))
        if unsettled_only:
            clauses.append("settlement_id IS NULL")

        where_clause = " AND ".join(clauses)
        query = (
            "SELECT id, worker_id, kind, amount, occurred_on, note, settlement_id "
            "FROM money_transactions WHERE " + where_clause + " ORDER BY occurred_on, id"
        )
        cursor = self._conn.execute(query, params)
        return [row_to_transaction(row) for row in cursor.fetchall()]

    def update(self, transaction: Transaction) -> Transaction:
        """Update mutable fields of a transaction and return the updated entity."""
        if transaction.id is None:
            raise DatabaseError("Cannot update transaction without an id")
        occurred_on_str = to_db_date(transaction.occurred_on)
        try:
            cursor = self._conn.execute(
                (
                    "UPDATE money_transactions "
                    "SET kind = ?, amount = ?, occurred_on = ?, note = ? "
                    "WHERE id = ?"
                ),
                (
                    transaction.kind.value,
                    transaction.amount,
                    occurred_on_str,
                    transaction.note,
                    transaction.id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, context="transaction") from exc
        if cursor.rowcount == 0:
            raise RecordNotFoundError("Transaction not found")
        stored = self.get(transaction.id)
        if stored is None:
            raise DatabaseError("Transaction not found after update")
        return stored

    def delete(self, transaction_id: int) -> None:
        """Delete an unlocked transaction by id."""
        try:
            cursor = self._conn.execute(
                "DELETE FROM money_transactions WHERE id = ?",
                (transaction_id,),
            )
        except sqlite3.IntegrityError as exc:
            raise translate_integrity_error(exc, context="transaction") from exc
        if cursor.rowcount == 0:
            raise RecordNotFoundError("Transaction not found")
