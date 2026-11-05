"""Worker domain entity."""

from dataclasses import dataclass

from worktime.domain._validation import (
    require_bool,
    require_optional_id,
    require_text,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Worker:
    """Worker entity with contact details and archive status."""

    name: str
    phone: str = ""
    note: str = ""
    archived: bool = False
    id: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "name",
            require_text(self.name, "name", max_length=100, allow_empty=False),
        )
        object.__setattr__(
            self,
            "phone",
            require_text(self.phone, "phone", max_length=30, allow_empty=True),
        )
        object.__setattr__(
            self,
            "note",
            require_text(self.note, "note", max_length=500, allow_empty=True),
        )
        object.__setattr__(
            self,
            "archived",
            require_bool(self.archived, "archived"),
        )
        object.__setattr__(
            self,
            "id",
            require_optional_id(self.id, "id"),
        )
