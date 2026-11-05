"""Domain layer exception hierarchy."""


class DomainError(Exception):
    """Base exception for all domain errors."""


class ValidationError(DomainError):
    """Raised when domain model validation fails."""


class RecordLockedError(DomainError):
    """Raised when an operation is attempted on a locked record."""
