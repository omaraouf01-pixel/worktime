"""Duration math, end-time resolution, and overlap detection for work sessions."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, time, timedelta

from worktime.domain._validation import require_naive_datetime
from worktime.domain.errors import ValidationError
from worktime.domain.session import Session

_ONE_MINUTE = timedelta(minutes=1)
_ONE_DAY = timedelta(days=1)


def _floor_minute(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def _session_interval(
    session: Session, *, now: datetime | None, allow_unbounded: bool
) -> tuple[datetime, datetime | None]:
    start = _floor_minute(session.start)
    if session.end is not None:
        return start, _floor_minute(session.end)
    if now is None:
        if not allow_unbounded:
            raise ValidationError("now is required for an open session")
        return start, None
    now_dt = require_naive_datetime(now, "now")
    now_floor = _floor_minute(now_dt)
    if now_floor < start:
        raise ValidationError("Field 'now' cannot be before session start.")
    return start, now_floor


def session_minutes(session: Session, *, now: datetime | None = None) -> int:
    """Return session duration in integer minutes, requiring now for open sessions."""
    start = _floor_minute(session.start)
    if session.end is not None:
        end = _floor_minute(session.end)
    else:
        if now is None:
            raise ValidationError("now is required for an open session")
        now_dt = require_naive_datetime(now, "now")
        end = _floor_minute(now_dt)
        if end < start:
            raise ValidationError("Field 'now' cannot be before session start.")
    return (end - start) // _ONE_MINUTE


def total_minutes(sessions: Iterable[Session], *, now: datetime | None = None) -> int:
    """Return total duration in integer minutes across sessions, or zero if empty."""
    return sum(session_minutes(s, now=now) for s in sessions)


def resolve_end(start: datetime, end_clock: time) -> tuple[datetime, bool]:
    """Resolve clock time to a session end datetime and flag whether it crossed midnight."""
    require_naive_datetime(start, "start")
    if isinstance(end_clock, datetime) or not isinstance(end_clock, time):
        raise ValidationError("Field 'end_clock' must be a time.")
    if end_clock.tzinfo is not None:
        raise ValidationError("Field 'end_clock' must be a naive time.")

    candidate = datetime.combine(start.date(), end_clock)
    start_floor = _floor_minute(start)
    candidate_floor = _floor_minute(candidate)

    if candidate_floor > start_floor:
        return candidate, False
    if candidate_floor < start_floor:
        return candidate + _ONE_DAY, True
    raise ValidationError("end equals start")


def sessions_overlap(first: Session, second: Session, *, now: datetime | None = None) -> bool:
    """Return whether two sessions overlap in half-open minutes without checking worker identity."""
    s1, e1 = _session_interval(first, now=now, allow_unbounded=True)
    s2, e2 = _session_interval(second, now=now, allow_unbounded=True)
    if (e1 is not None and s1 == e1) or (e2 is not None and s2 == e2):
        return False
    return (e2 is None or s1 < e2) and (e1 is None or s2 < e1)
