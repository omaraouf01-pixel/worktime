"""Database error types."""


class DatabaseError(Exception):
    """Base exception for all database errors."""


class DatabaseVersionError(DatabaseError):
    """Raised when the database schema version is incompatible."""
