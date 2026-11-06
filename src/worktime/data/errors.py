"""Database error types."""


class DatabaseError(Exception):
    """Base exception for all database errors."""


class DatabaseVersionError(DatabaseError):
    """Raised when the database schema version is incompatible."""


class RecordNotFoundError(DatabaseError):
    """Raised when a requested database record is not found."""


class DuplicateWorkerError(DatabaseError):
    """Raised when an active worker with the same name already exists."""


class OpenSessionExistsError(DatabaseError):
    """Raised when an open session already exists for the worker."""
