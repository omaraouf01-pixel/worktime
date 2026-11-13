"""Settlement service managing previews, atomic settlement creation, and record locking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from worktime.data import (
    SessionRepository,
    SettlementRepository,
    TransactionRepository,
    WorkerRepository,
    write_transaction,
)
from worktime.domain import (
    Session,
    Settlement,
    SettlementDraft,
    Transaction,
    prepare_settlement,
)
from worktime.services._rules import (
    ensure_no_open_session,
    require_worker,
)
from worktime.services.clock import Clock, system_clock
from worktime.services.errors import (
    NothingToSettleError,
    SettlementChangedError,
)

if TYPE_CHECKING:
    import sqlite3


@dataclass(frozen=True, slots=True, kw_only=True)
class SettlementPreview:
    """Settlement preview containing computed draft and covered record counts."""

    draft: SettlementDraft
    session_count: int
    transaction_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SettlementDetails:
    """Full settlement record along with its covered sessions and transactions."""

    settlement: Settlement
    sessions: tuple[Session, ...]
    transactions: tuple[Transaction, ...]


class SettlementService:
    """Service managing atomic settlements, previews, and historical settlement views."""

    def __init__(self, conn: sqlite3.Connection, clock: Clock = system_clock) -> None:
        """Initialize settlement service with database connection and injected clock."""
        self._conn = conn
        self._clock = clock
        self._workers = WorkerRepository(conn)
        self._sessions = SessionRepository(conn)
        self._transactions = TransactionRepository(conn)
        self._settlements = SettlementRepository(conn)

    def _prepare_draft(
        self,
        worker_id: int,
        hourly_rate: int,
    ) -> tuple[SettlementDraft, list[int], list[int]]:
        """Validate worker state and build settlement draft with covered record IDs."""
        require_worker(self._workers, worker_id, allow_archived=True)
        ensure_no_open_session(self._sessions, worker_id)
        sessions = self._sessions.list_for_worker(worker_id, unsettled_only=True)
        transactions = self._transactions.list_for_worker(worker_id, unsettled_only=True)
        previous_balance = self._settlements.last_balance(worker_id)
        if not sessions and not transactions and previous_balance <= 0:
            raise NothingToSettleError("Worker has no unsettled records and no positive balance.")
        draft = prepare_settlement(
            worker_id=worker_id,
            sessions=sessions,
            transactions=transactions,
            previous_balance=previous_balance,
            hourly_rate=hourly_rate,
        )
        session_ids = [cast(int, s.id) for s in sessions]
        tx_ids = [cast(int, t.id) for t in transactions]
        return draft, session_ids, tx_ids

    def preview_settlement(
        self,
        worker_id: int,
        *,
        hourly_rate: int,
    ) -> SettlementPreview:
        """Preview settlement draft and record counts for a worker without modifying state."""
        draft, session_ids, tx_ids = self._prepare_draft(worker_id, hourly_rate)
        return SettlementPreview(
            draft=draft,
            session_count=len(session_ids),
            transaction_count=len(tx_ids),
        )

    def settle(
        self,
        worker_id: int,
        *,
        hourly_rate: int,
        paid: int,
        note: str = "",
        expected_payable: int | None = None,
    ) -> Settlement:
        """Settle records for a worker atomically and lock covered sessions and transactions."""
        with write_transaction(self._conn):
            draft, session_ids, tx_ids = self._prepare_draft(worker_id, hourly_rate)
            if expected_payable is not None and expected_payable != draft.payable:
                raise SettlementChangedError(
                    f"Payable amount changed from expected {expected_payable} to {draft.payable}."
                )
            settlement = draft.finalize(
                paid=paid,
                settled_on=self._clock().date(),
                note=note,
            )
            stored = self._settlements.add(settlement)
            self._settlements.attach_records(
                cast(int, stored.id),
                session_ids=session_ids,
                transaction_ids=tx_ids,
            )
            return stored

    def get_settlement(self, settlement_id: int) -> Settlement | None:
        """Retrieve a settlement by ID or return None if not found."""
        return self._settlements.get(settlement_id)

    def get_details(self, settlement_id: int) -> SettlementDetails | None:
        """Retrieve complete details for a settlement or return None if not found."""
        settlement = self._settlements.get(settlement_id)
        if settlement is None:
            return None
        sessions = self._settlements.sessions_of(settlement_id)
        transactions = self._settlements.transactions_of(settlement_id)
        return SettlementDetails(
            settlement=settlement,
            sessions=tuple(sessions),
            transactions=tuple(transactions),
        )

    def list_settlements(self, worker_id: int) -> list[Settlement]:
        """List all settlements for a worker ordered by ID ascending."""
        return self._settlements.list_for_worker(worker_id)

    def current_balance(self, worker_id: int) -> int:
        """Return the latest balance in centimes for a worker, or zero if never settled."""
        return self._settlements.last_balance(worker_id)

    def current_balances(self) -> dict[int, int]:
        """Return a mapping of worker IDs to their latest balance in centimes."""
        return self._settlements.latest_balances()
