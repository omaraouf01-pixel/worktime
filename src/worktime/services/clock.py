"""Clock abstraction for time-dependent operations."""

from collections.abc import Callable
from datetime import datetime

Clock = Callable[[], datetime]


def system_clock() -> datetime:
    """Return the current local naive datetime with microsecond precision zeroed."""
    return datetime.now().replace(microsecond=0)
