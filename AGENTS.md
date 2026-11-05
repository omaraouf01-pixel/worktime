# Agent Guidelines for WorkTime

WorkTime is a Windows-first desktop application (Python, PySide6, SQLite) for tracking part-time workers' hours and settling pay with an Arabic (RTL) interface on a shared offline computer. See `docs/PROJECT_BRIEF.md` as the definitive source of truth for full business rules and specifications.

## Architecture
- Enforce strict layer boundaries:
  - `domain`: Pure Python only. No Qt, no `sqlite3` imports.
  - `data`: Depends only on `domain`.
  - `services`: Depend on `domain` and `data`.
  - `ui`: Depends on `services` and `domain` only.
- Place all Arabic UI strings exclusively in `ui/strings.py`.
- Keep worker-facing screens (clock in/out) as separate widgets from owner-facing screens.

## Data Rules
- Represent money as integer centimes (1 DA = 100 centimes); never use floats.
- Represent durations as integer minutes; never use floats.
- Store timestamps as timezone-naive local time in ISO-8601 text format.

## Code Quality
- Provide full type hints across all code (`mypy --strict`).
- Write small, single-responsibility functions.
- Keep zero dead code, zero commented-out code, and zero TODO placeholders.
- Do not duplicate logic.
- Use explicit custom exceptions for business-rule violations; never use bare `except`.

## Process Rules
- Stay strictly within requested scope; add no unrequested code or dependencies.
- Write or update tests for every behavior change.
- Never weaken or delete an existing test to make it pass.
- Before finishing any task, run and pass:
  - `pytest`
  - `ruff check .`
  - `ruff format --check .`
  - `mypy src`
- If a requirement is ambiguous, ask instead of guessing.

## Data Layer
- Use parameterized SQL only; never interpolate data into SQL strings.
- Store timestamps as `YYYY-MM-DDTHH:MM:SS` and dates as `YYYY-MM-DD`.
- Enforce locking and invariants in the database as a second line of defense.
- Apply schema changes only through a new migration; never edit a shipped migration.
- Database file never lives inside the project folder.
