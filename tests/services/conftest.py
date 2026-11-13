"""Pytest configuration and fixtures for service layer tests."""

import sqlite3
from collections.abc import Callable, Generator
from datetime import date, datetime, timedelta

import pytest

from worktime.data import (
    SettlementRepository,
    open_database,
    write_transaction,
)
from worktime.domain import Settlement, Worker
from worktime.services import AttendanceService, WorkerService


class FakeClock:
    """Controllable clock returning naive local datetime for testing."""

    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, *, minutes: int = 0, seconds: int = 0) -> None:
        self.now += timedelta(minutes=minutes, seconds=seconds)


@pytest.fixture
def conn() -> Generator[sqlite3.Connection, None, None]:
    connection = open_database(":memory:")
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 11, 12, 18, 0, 0))


@pytest.fixture
def workers(conn: sqlite3.Connection) -> WorkerService:
    return WorkerService(conn)


@pytest.fixture
def attendance(conn: sqlite3.Connection, clock: FakeClock) -> AttendanceService:
    return AttendanceService(conn, clock=clock)


@pytest.fixture
def make_worker(workers: WorkerService) -> Callable[..., Worker]:
    def _create(
        name: str = "عمر بن الخطاب",
        phone: str = "0550123456",
        note: str = "عامل دوام جزئي",
    ) -> Worker:
        return workers.add_worker(name=name, phone=phone, note=note)

    return _create


def lock_session(
    conn: sqlite3.Connection,
    worker_id: int,
    session_id: int,
    *,
    settled_on: date = date(2026, 11, 12),
    minutes: int = 60,
    wage: int = 50000,
    paid: int = 50000,
    new_balance: int = 0,
) -> Settlement:
    settlements = SettlementRepository(conn)
    with write_transaction(conn):
        settlement = settlements.add(
            Settlement(
                worker_id=worker_id,
                settled_on=settled_on,
                total_minutes=minutes,
                wage=wage,
                advances_total=0,
                prepayments_total=0,
                deductions_total=0,
                previous_balance=0,
                payable=wage,
                paid=paid,
                new_balance=new_balance,
            )
        )
        assert settlement.id is not None
        settlements.attach_records(
            settlement.id,
            session_ids=[session_id],
            transaction_ids=[],
        )
        return settlement
