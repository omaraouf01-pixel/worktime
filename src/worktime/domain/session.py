"""Work session domain entity."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from worktime.domain._validation import (
    require_int,
    require_naive_datetime,
    require_optional_id,
    require_text,
)
from worktime.domain.errors import RecordLockedError, ValidationError


@dataclass(frozen=True, slots=True, kw_only=True)
class Session:
    """Work session entity tracking start and end timestamps."""

    worker_id: int
    start: datetime
    end: datetime | None = None
    note: str = ""
    id: int | None = None
    settlement_id: int | None = None

    def __post_init__(self) -> None:
        require_int(self.worker_id, "worker_id", minimum=1)
        require_naive_datetime(self.start, "start")
        if self.end is not None:
            require_naive_datetime(self.end, "end")
            if self.end <= self.start:
                raise ValidationError("Field 'end' must be strictly after 'start'.")
        object.__setattr__(
            self,
            "note",
            require_text(self.note, "note", max_length=500, allow_empty=True),
        )
        require_optional_id(self.id, "id")
        require_optional_id(self.settlement_id, "settlement_id")

    @property
    def is_open(self) -> bool:
        """Return True if session has no end datetime."""
        return self.end is None

    @property
    def is_locked(self) -> bool:
        """Return True if session is locked by a settlement."""
        return self.settlement_id is not None

    def ensure_editable(self) -> None:
        """Raise RecordLockedError if session is locked by a settlement."""
        if self.is_locked:
            raise RecordLockedError("Session is locked by a settlement and cannot be modified.")

    def close(self, end: datetime) -> Session:
        """Return a closed copy of session ending at naive datetime end."""
        self.ensure_editable()
        if not self.is_open:
            raise ValidationError("Session is already closed.")
        return replace(self, end=end)

    def with_settlement(self, settlement_id: int) -> Session:
        """Return a copy of session locked to the given settlement ID."""
        if self.is_open:
            raise ValidationError("Cannot attach an open session to a settlement.")
        if self.is_locked:
            raise RecordLockedError("Session is already locked by a settlement.")
        require_int(settlement_id, "settlement_id", minimum=1)
        return replace(self, settlement_id=settlement_id)
