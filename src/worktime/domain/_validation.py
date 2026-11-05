"""Internal validation helpers for domain entities."""

from datetime import date, datetime

from worktime.domain.errors import ValidationError


def require_int(value: object, field: str, *, minimum: int | None = None) -> int:
    """Validate that value is an integer meeting the optional minimum bound."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"Field '{field}' must be an integer.")
    if minimum is not None and value < minimum:
        raise ValidationError(f"Field '{field}' must be at least {minimum}.")
    return value


def require_optional_id(value: object, field: str) -> int | None:
    """Validate that value is None or a positive ID integer."""
    if value is None:
        return None
    return require_int(value, field, minimum=1)


def require_naive_datetime(value: object, field: str) -> datetime:
    """Validate that value is a timezone-naive datetime."""
    if not isinstance(value, datetime):
        raise ValidationError(f"Field '{field}' must be a datetime.")
    if value.tzinfo is not None:
        raise ValidationError(f"Field '{field}' must be a naive datetime.")
    return value


def require_date(value: object, field: str) -> date:
    """Validate that value is a date and not a datetime instance."""
    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValidationError(f"Field '{field}' must be a date.")
    return value


def require_text(value: object, field: str, *, max_length: int, allow_empty: bool) -> str:
    """Validate that value is a string within length bounds and return stripped text."""
    if not isinstance(value, str):
        raise ValidationError(f"Field '{field}' must be a string.")
    stripped = value.strip()
    if not allow_empty and not stripped:
        raise ValidationError(f"Field '{field}' cannot be empty.")
    if len(stripped) > max_length:
        raise ValidationError(f"Field '{field}' must be at most {max_length} characters.")
    return stripped


def require_bool(value: object, field: str) -> bool:
    """Validate that value is a boolean."""
    if not isinstance(value, bool):
        raise ValidationError(f"Field '{field}' must be a boolean.")
    return value
