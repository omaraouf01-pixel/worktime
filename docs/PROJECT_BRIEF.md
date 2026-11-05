# WorkTime - Project Brief

## Project Context
"WorkTime": a Windows-first desktop app (Python + PySide6 + SQLite) for a shop owner to track part-time workers' hours and settle their pay. UI language: Arabic (RTL). Code, identifiers, comments, and docs: English. Single computer, shared by several people, no internet needed.

Business flow:
1. A worker "clocks in" (button or manual entry) and "clocks out". Duration is stored in integer minutes. Sessions may cross midnight. At most one open session per worker. An open session must survive an app restart.
2. During the period the owner records financial transactions per worker: advance (سلفة), prepayment (تسبيق), or deduction (خصم): positive amount, date, note.
3. At settlement the owner TYPES the hourly rate manually. The rate is NEVER stored anywhere (shared computer). The settlement record stores minutes, wage, totals, paid amount and balances, but not the rate.
4. Settlement formula (all money in integer centimes):
   wage = round_half_up(minutes * rate / 6000) dinars, expressed in centimes (x100), computed with integers only and a single rounding step; rate is in centimes per hour.
   payable = previous_balance + wage - (advances + prepayments + deductions)
   - If payable > 0: the owner enters the amount actually paid (0..payable); new_balance = payable - paid (positive = shop owes the worker).
   - If payable <= 0: paid = 0; new_balance = payable (negative = worker owes the shop). The balance carries to the next settlement.
   Example 1: 100 h at 50 DA = 5000; advances 7000; previous balance 0 -> payable -2000; paid 0; new balance -2000.
   Example 2: next settlement wage 6000, previous balance -2000 -> payable 4000; paid 3000; new balance +1000.
5. After a settlement, the covered sessions and transactions become locked (read-only) and are never counted again. A settlement cannot be deleted. Settlement is refused while the worker has an open session. Settlement is one atomic DB transaction.
6. Workers are archived, never deleted.
7. Excel import (later phase): a monthly attendance file for ONE worker and ONE sheet, columns: date, start, end, duration (ignored, always recomputed), advances. Every money amount in the file is an advance. The worker name is NOT in the file; the owner picks the worker manually. Rows with no start and no end are days off. End earlier than start means past midnight (flag it). Duplicate detection: worker + date + start + end. Preview before saving; the save is atomic.
8. Currency: Algerian dinar (DA / دج). Money is stored as integer centimes (1 DA = 100 centimes). Durations are integer minutes. No floats for money or time.
9. No authentication by default: one open interface. An OPTIONAL owner PIN (disabled by default, set in settings, stored salted with PBKDF2, never in clear text) will be added in a late phase to protect owner-only screens. Architecture must not assume or prevent it: keep worker-facing screens (clock in/out) as separate widgets from owner-facing screens.

## Architecture Rules
- Layer dependencies:
  - `domain`: Pure Python only (no Qt, no `sqlite3` imports).
  - `data`: Depends only on `domain`.
  - `services`: Depend on `domain` and `data`.
  - `ui`: Depends on `services` and `domain` only.
- UI strings: All Arabic UI strings live exclusively in `ui/strings.py`.
- Screen separation: Worker-facing screens (clock in/out) must be separate widgets from owner-facing screens.
- Data rules: Money amounts are integer centimes (1 DA = 100 centimes); durations are integer minutes; no floats for money or time. Timestamps are timezone-naive local time stored as ISO-8601 text.
- Code quality: Full type hints, small functions, no dead code, no commented-out code, no TODO placeholders, no duplicated logic, explicit custom exceptions for business-rule violations (no bare `except`).
- Process rules: Stay strictly within requested scope; add no dependencies without being asked; write or update tests for every behavior change; before finishing run `pytest`, `ruff check .`, `ruff format --check .`, `mypy src` and fix all failures; never weaken or delete an existing test to make it pass; if a requirement is ambiguous, ask instead of guessing.
