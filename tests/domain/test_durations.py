"""Tests for domain duration math, end-time resolution, and session overlap detection."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from datetime import UTC, datetime, time
from pathlib import Path

import pytest

import worktime.domain
from worktime.domain.durations import (
    resolve_end,
    session_minutes,
    sessions_overlap,
    total_minutes,
)
from worktime.domain.errors import ValidationError
from worktime.domain.session import Session


def _make_session(start: datetime, end: datetime | None = None, *, worker_id: int = 1) -> Session:
    return Session(worker_id=worker_id, start=start, end=end)


# ---------------------------------------------------------------------------
# session_minutes tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 14, 30), 150),
        (datetime(2026, 1, 1, 10, 30), datetime(2026, 1, 1, 12, 30), 120),
        (datetime(2026, 1, 1, 10, 0, 59), datetime(2026, 1, 1, 10, 1, 0), 1),
        (datetime(2026, 1, 1, 10, 0, 30), datetime(2026, 1, 1, 10, 59, 59), 59),
        (datetime(2026, 1, 1, 22, 0), datetime(2026, 1, 2, 2, 0), 240),
        (datetime(2026, 1, 1, 8, 0), datetime(2026, 1, 3, 9, 30), 2970),
        (datetime(2026, 1, 1, 8, 0), datetime(2026, 1, 3, 11, 30), 3090),
        (datetime(2026, 1, 1, 6, 0), datetime(2026, 1, 3, 9, 30), 3090),
    ],
)
def test_session_minutes_closed_sessions(start: datetime, end: datetime, expected: int) -> None:
    session = _make_session(start, end)
    result = session_minutes(session)
    assert result == expected
    assert type(result) is int


def test_session_minutes_closed_session_ignores_now() -> None:
    session = _make_session(datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 12, 0))
    # Naive now
    assert session_minutes(session, now=datetime(2026, 1, 1, 18, 0)) == 120
    # Aware now should also be ignored for closed sessions
    aware_now = datetime(2026, 1, 1, 18, 0, tzinfo=UTC)
    assert session_minutes(session, now=aware_now) == 120  # type: ignore[arg-type]


def test_session_minutes_open_session_without_now_raises() -> None:
    session = _make_session(datetime(2026, 1, 1, 10, 0))
    with pytest.raises(ValidationError, match="now is required for an open session"):
        session_minutes(session)


def test_session_minutes_open_session_with_now() -> None:
    session = _make_session(datetime(2026, 1, 1, 10, 0))
    now = datetime(2026, 1, 1, 11, 30)
    result = session_minutes(session, now=now)
    assert result == 90
    assert type(result) is int


def test_session_minutes_open_session_now_before_start_raises() -> None:
    session = _make_session(datetime(2026, 1, 1, 10, 0))
    now = datetime(2026, 1, 1, 9, 30)
    with pytest.raises(ValidationError, match="Field 'now' cannot be before session start"):
        session_minutes(session, now=now)


def test_session_minutes_open_session_aware_now_raises() -> None:
    session = _make_session(datetime(2026, 1, 1, 10, 0))
    now = datetime(2026, 1, 1, 11, 30, tzinfo=UTC)
    with pytest.raises(ValidationError, match="Field 'now' must be a naive datetime"):
        session_minutes(session, now=now)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# total_minutes tests
# ---------------------------------------------------------------------------


def test_total_minutes_empty() -> None:
    result = total_minutes([])
    assert result == 0
    assert type(result) is int


def test_total_minutes_multiple_closed_sessions() -> None:
    s1 = _make_session(datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 14, 30))  # 150
    s2 = _make_session(datetime(2026, 1, 1, 10, 30), datetime(2026, 1, 1, 12, 30))  # 120
    assert total_minutes([s1, s2]) == 270


def test_total_minutes_includes_open_session_with_now() -> None:
    s1 = _make_session(datetime(2026, 1, 1, 10, 30), datetime(2026, 1, 1, 12, 30))  # 120
    s2 = _make_session(datetime(2026, 1, 1, 14, 0))  # open
    now = datetime(2026, 1, 1, 15, 0)  # 60
    assert total_minutes([s1, s2], now=now) == 180


def test_total_minutes_open_session_without_now_raises() -> None:
    s1 = _make_session(datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 11, 0))
    s2 = _make_session(datetime(2026, 1, 1, 12, 0))
    with pytest.raises(ValidationError, match="now is required for an open session"):
        total_minutes([s1, s2])


def test_total_minutes_accepts_generator() -> None:
    s1 = _make_session(datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 14, 30))
    s2 = _make_session(datetime(2026, 1, 1, 10, 30), datetime(2026, 1, 1, 12, 30))

    def gen() -> Iterator[Session]:
        yield s1
        yield s2

    assert total_minutes(gen()) == 270


# ---------------------------------------------------------------------------
# resolve_end tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end_clock", "expected_end", "expected_crossed"),
    [
        (
            datetime(2026, 1, 1, 9, 0),
            time(13, 30),
            datetime(2026, 1, 1, 13, 30),
            False,
        ),
        (
            datetime(2026, 1, 1, 22, 0),
            time(2, 0),
            datetime(2026, 1, 2, 2, 0),
            True,
        ),
        (
            datetime(2026, 1, 1, 23, 30),
            time(0, 0),
            datetime(2026, 1, 2, 0, 0),
            True,
        ),
        (
            datetime(2026, 1, 1, 0, 0),
            time(23, 59),
            datetime(2026, 1, 1, 23, 59),
            False,
        ),
    ],
)
def test_resolve_end_valid_cases(
    start: datetime,
    end_clock: time,
    expected_end: datetime,
    expected_crossed: bool,
) -> None:
    resolved_end, crossed = resolve_end(start, end_clock)
    assert resolved_end == expected_end
    assert crossed is expected_crossed
    # Returned end can always be used to build a valid Session with start
    session = Session(worker_id=1, start=start, end=resolved_end)
    assert session.end == resolved_end


@pytest.mark.parametrize(
    ("start", "end_clock"),
    [
        (datetime(2026, 1, 1, 9, 0), time(9, 0)),
        (datetime(2026, 1, 1, 9, 0, 15), time(9, 0, 45)),
        (datetime(2026, 1, 1, 9, 0, 45), time(9, 0, 15)),
        (datetime(2026, 1, 1, 23, 59, 10), time(23, 59, 50)),
        (datetime(2026, 1, 1, 9, 30, 45, 123456), time(9, 30)),
    ],
)
def test_resolve_end_equal_at_minute_precision_raises(start: datetime, end_clock: time) -> None:
    with pytest.raises(ValidationError, match="end equals start"):
        resolve_end(start, end_clock)


def test_resolve_end_aware_clock_raises() -> None:
    start = datetime(2026, 1, 1, 9, 0)
    aware_clock = time(10, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="Field 'end_clock' must be a naive time"):
        resolve_end(start, aware_clock)


@pytest.mark.parametrize(
    "invalid_clock",
    [
        datetime(2026, 1, 1, 10, 0),
        "10:00",
        10,
        None,
    ],
)
def test_resolve_end_invalid_clock_type_raises(invalid_clock: object) -> None:
    start = datetime(2026, 1, 1, 9, 0)
    with pytest.raises(ValidationError, match="Field 'end_clock' must be a time"):
        resolve_end(start, invalid_clock)  # type: ignore[arg-type]


def test_resolve_end_aware_start_raises() -> None:
    start = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)
    with pytest.raises(ValidationError, match="Field 'start' must be a naive datetime"):
        resolve_end(start, time(10, 0))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# sessions_overlap tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first_start", "first_end", "second_start", "second_end", "expected"),
    [
        # Partial overlap
        (
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 12, 0),
            datetime(2026, 1, 1, 11, 0),
            datetime(2026, 1, 1, 13, 0),
            True,
        ),
        # Containment (first contains second)
        (
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 13, 0),
            datetime(2026, 1, 1, 11, 0),
            datetime(2026, 1, 1, 12, 0),
            True,
        ),
        # Identical sessions
        (
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 12, 0),
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 12, 0),
            True,
        ),
        # Adjacent sessions (end of first == start of second) -> False
        (
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 11, 0),
            datetime(2026, 1, 1, 11, 0),
            datetime(2026, 1, 1, 12, 0),
            False,
        ),
        # Disjoint sessions
        (
            datetime(2026, 1, 1, 10, 0),
            datetime(2026, 1, 1, 11, 0),
            datetime(2026, 1, 1, 12, 0),
            datetime(2026, 1, 1, 13, 0),
            False,
        ),
    ],
)
def test_sessions_overlap_closed_and_symmetric(
    first_start: datetime,
    first_end: datetime,
    second_start: datetime,
    second_end: datetime,
    expected: bool,
) -> None:
    s1 = _make_session(first_start, first_end)
    s2 = _make_session(second_start, second_end)
    assert sessions_overlap(s1, s2) is expected
    # Symmetry: (second, first) must yield the exact same result
    assert sessions_overlap(s2, s1) is expected


def test_sessions_overlap_open_unbounded_overlaps_later_closed() -> None:
    open_session = _make_session(datetime(2026, 1, 1, 10, 0))
    later_closed = _make_session(datetime(2026, 1, 1, 12, 0), datetime(2026, 1, 1, 14, 0))
    assert sessions_overlap(open_session, later_closed) is True
    assert sessions_overlap(later_closed, open_session) is True


def test_sessions_overlap_both_open_without_now() -> None:
    s1 = _make_session(datetime(2026, 1, 1, 9, 0))
    s2 = _make_session(datetime(2026, 1, 1, 14, 0))
    assert sessions_overlap(s1, s2) is True
    assert sessions_overlap(s2, s1) is True


def test_sessions_overlap_open_unbounded_does_not_overlap_earlier_closed() -> None:
    open_session = _make_session(datetime(2026, 1, 1, 12, 0))
    earlier_closed = _make_session(datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 11, 0))
    assert sessions_overlap(open_session, earlier_closed) is False
    assert sessions_overlap(earlier_closed, open_session) is False


def test_sessions_overlap_open_unbounded_adjacent_earlier_closed() -> None:
    open_session = _make_session(datetime(2026, 1, 1, 11, 0))
    earlier_closed = _make_session(datetime(2026, 1, 1, 10, 0), datetime(2026, 1, 1, 11, 0))
    assert sessions_overlap(open_session, earlier_closed) is False
    assert sessions_overlap(earlier_closed, open_session) is False


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 1, 1, 11, 30), True),  # Overlaps [11:00, 12:00)
        (datetime(2026, 1, 1, 11, 0), False),  # Adjacent at 11:00
        (datetime(2026, 1, 1, 10, 45), False),  # Disjoint, ends before 11:00
    ],
)
def test_sessions_overlap_open_with_now_bounds_correctly(now: datetime, expected: bool) -> None:
    open_session = _make_session(datetime(2026, 1, 1, 10, 0))
    closed_session = _make_session(datetime(2026, 1, 1, 11, 0), datetime(2026, 1, 1, 12, 0))
    assert sessions_overlap(open_session, closed_session, now=now) is expected
    assert sessions_overlap(closed_session, open_session, now=now) is expected


def test_sessions_overlap_zero_minute_session_never_overlaps() -> None:
    # A closed session where truncated start equals truncated end
    zero_session = _make_session(datetime(2026, 1, 1, 10, 0, 10), datetime(2026, 1, 1, 10, 0, 50))
    spanning_session = _make_session(datetime(2026, 1, 1, 9, 0), datetime(2026, 1, 1, 12, 0))
    assert sessions_overlap(zero_session, spanning_session) is False
    assert sessions_overlap(spanning_session, zero_session) is False

    # An open session bounded by now in the same minute as start
    open_zero = _make_session(datetime(2026, 1, 1, 10, 0, 10))
    now = datetime(2026, 1, 1, 10, 0, 50)
    assert sessions_overlap(open_zero, spanning_session, now=now) is False
    assert sessions_overlap(spanning_session, open_zero, now=now) is False


def test_sessions_overlap_open_now_before_start_raises() -> None:
    open_session = _make_session(datetime(2026, 1, 1, 10, 0))
    other = _make_session(datetime(2026, 1, 1, 11, 0), datetime(2026, 1, 1, 12, 0))
    now = datetime(2026, 1, 1, 9, 0)
    with pytest.raises(ValidationError, match="Field 'now' cannot be before session start"):
        sessions_overlap(open_session, other, now=now)
    with pytest.raises(ValidationError, match="Field 'now' cannot be before session start"):
        sessions_overlap(other, open_session, now=now)


# ---------------------------------------------------------------------------
# No-float guard test
# ---------------------------------------------------------------------------


def test_no_float_guard() -> None:
    source_path = Path("src/worktime/domain/durations.py")
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))

    for node in ast.walk(tree):
        assert not isinstance(node, ast.Div), "Found ast.Div operator (/)"
        if isinstance(node, ast.Name):
            assert node.id != "float", "Found 'float' identifier"
        elif isinstance(node, ast.Attribute):
            assert node.attr != "total_seconds", "Found 'total_seconds' attribute"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id != "round", "Found call to 'round'"


# ---------------------------------------------------------------------------
# Package export tests
# ---------------------------------------------------------------------------


def test_package_exports_duration_functions() -> None:
    expected_new = {"session_minutes", "total_minutes", "resolve_end", "sessions_overlap"}
    for name in expected_new:
        assert name in worktime.domain.__all__
        assert hasattr(worktime.domain, name)
