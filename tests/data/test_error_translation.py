"""Tests for translation of SQLite IntegrityError to domain and data exceptions."""

import sqlite3

import pytest

from worktime.data._mapping import translate_integrity_error
from worktime.data.errors import (
    DatabaseError,
    DuplicateWorkerError,
    OpenSessionExistsError,
    RecordNotFoundError,
)
from worktime.domain.errors import RecordLockedError, ValidationError


@pytest.mark.parametrize(
    ("message", "context", "expected_type", "expected_msg"),
    [
        (
            "record locked",
            "session",
            RecordLockedError,
            "record locked",
        ),
        (
            "cannot lock an open session",
            "session",
            ValidationError,
            "cannot lock an open session",
        ),
        (
            "settlement belongs to another worker",
            "session",
            ValidationError,
            "settlement belongs to another worker",
        ),
        (
            "FOREIGN KEY constraint failed",
            "session",
            RecordNotFoundError,
            "worker not found",
        ),
        (
            "FOREIGN KEY constraint failed: sessions.worker_id",
            "session",
            RecordNotFoundError,
            "worker not found",
        ),
        (
            "UNIQUE constraint failed: workers.name",
            "worker",
            DuplicateWorkerError,
            "UNIQUE constraint failed: workers.name",
        ),
        (
            "UNIQUE constraint failed: sessions.worker_id",
            "session",
            OpenSessionExistsError,
            "UNIQUE constraint failed: sessions.worker_id",
        ),
        (
            "UNIQUE constraint failed: other.col",
            "other",
            DatabaseError,
            "UNIQUE constraint failed: other.col",
        ),
        # Messages merely containing trigger phrases must NOT match exact equality
        (
            "note says record locked",
            "session",
            DatabaseError,
            "note says record locked",
        ),
        (
            "prefix: cannot lock an open session",
            "session",
            DatabaseError,
            "prefix: cannot lock an open session",
        ),
        (
            "prefix: settlement belongs to another worker",
            "session",
            DatabaseError,
            "prefix: settlement belongs to another worker",
        ),
        (
            "not a start FOREIGN KEY constraint failed",
            "session",
            DatabaseError,
            "not a start FOREIGN KEY constraint failed",
        ),
        (
            "not a start UNIQUE constraint failed: workers.name",
            "worker",
            DatabaseError,
            "not a start UNIQUE constraint failed: workers.name",
        ),
        # Unmapped messages falling through to plain DatabaseError
        (
            "record already exists",
            "worker",
            DatabaseError,
            "record already exists",
        ),
        (
            "settlement is immutable",
            "settlement",
            DatabaseError,
            "settlement is immutable",
        ),
        (
            "new records cannot be pre-locked",
            "session",
            DatabaseError,
            "new records cannot be pre-locked",
        ),
        (
            "workers are archived, not deleted",
            "worker",
            DatabaseError,
            "workers are archived, not deleted",
        ),
    ],
)
def test_translate_integrity_error(
    message: str,
    context: str,
    expected_type: type[Exception],
    expected_msg: str,
) -> None:
    exc = sqlite3.IntegrityError(message)
    translated = translate_integrity_error(exc, context=context)
    assert type(translated) is expected_type
    assert str(translated) == expected_msg
