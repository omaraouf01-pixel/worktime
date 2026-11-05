"""Database schema definitions and version migrations."""

SCHEMA_VERSION: int = 1

MIGRATIONS: tuple[tuple[str, ...], ...] = (
    (
        """CREATE TABLE workers (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100 AND name = trim(name)),
  phone TEXT NOT NULL DEFAULT '' CHECK (length(phone) <= 30),
  note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
  archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
)""",
        (
            "CREATE UNIQUE INDEX ux_workers_active_name "
            "ON workers (name COLLATE NOCASE) WHERE archived = 0"
        ),
        """CREATE TABLE settlements (
  id INTEGER PRIMARY KEY,
  worker_id INTEGER NOT NULL REFERENCES workers (id),
  settled_on TEXT NOT NULL CHECK (settled_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  total_minutes INTEGER NOT NULL CHECK (total_minutes >= 0),
  wage INTEGER NOT NULL CHECK (wage >= 0),
  advances_total INTEGER NOT NULL CHECK (advances_total >= 0),
  prepayments_total INTEGER NOT NULL CHECK (prepayments_total >= 0),
  deductions_total INTEGER NOT NULL CHECK (deductions_total >= 0),
  previous_balance INTEGER NOT NULL,
  payable INTEGER NOT NULL,
  paid INTEGER NOT NULL CHECK (paid >= 0),
  new_balance INTEGER NOT NULL,
  note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
  CHECK (
    payable = previous_balance + wage
    - (advances_total + prepayments_total + deductions_total)
  ),
  CHECK (
    (payable > 0 AND paid <= payable AND new_balance = payable - paid)
    OR (payable <= 0 AND paid = 0 AND new_balance = payable)
  )
)""",
        "CREATE INDEX ix_settlements_worker ON settlements (worker_id, id)",
        """CREATE TABLE sessions (
  id INTEGER PRIMARY KEY,
  worker_id INTEGER NOT NULL REFERENCES workers (id),
  start_at TEXT NOT NULL CHECK (
    start_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
  ),
  end_at TEXT CHECK (
    end_at IS NULL
    OR (
      end_at GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]'
      AND end_at > start_at
    )
  ),
  note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
  settlement_id INTEGER REFERENCES settlements (id)
)""",
        "CREATE UNIQUE INDEX ux_sessions_one_open ON sessions (worker_id) WHERE end_at IS NULL",
        "CREATE INDEX ix_sessions_worker_start ON sessions (worker_id, start_at)",
        "CREATE INDEX ix_sessions_settlement ON sessions (settlement_id)",
        """CREATE TABLE money_transactions (
  id INTEGER PRIMARY KEY,
  worker_id INTEGER NOT NULL REFERENCES workers (id),
  kind TEXT NOT NULL CHECK (kind IN ('advance', 'prepayment', 'deduction')),
  amount INTEGER NOT NULL CHECK (amount > 0),
  occurred_on TEXT NOT NULL CHECK (occurred_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 500),
  settlement_id INTEGER REFERENCES settlements (id)
)""",
        "CREATE INDEX ix_money_worker_date ON money_transactions (worker_id, occurred_on)",
        "CREATE INDEX ix_money_settlement ON money_transactions (settlement_id)",
        """CREATE TABLE app_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
)""",
        """CREATE TRIGGER trg_sessions_locked_update
BEFORE UPDATE ON sessions
WHEN OLD.settlement_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'record locked');
END""",
        """CREATE TRIGGER trg_sessions_locked_delete
BEFORE DELETE ON sessions
WHEN OLD.settlement_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'record locked');
END""",
        """CREATE TRIGGER trg_money_locked_update
BEFORE UPDATE ON money_transactions
WHEN OLD.settlement_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'record locked');
END""",
        """CREATE TRIGGER trg_money_locked_delete
BEFORE DELETE ON money_transactions
WHEN OLD.settlement_id IS NOT NULL
BEGIN
  SELECT RAISE(ABORT, 'record locked');
END""",
        """CREATE TRIGGER trg_sessions_lock_needs_closed
BEFORE UPDATE OF settlement_id ON sessions
WHEN NEW.settlement_id IS NOT NULL AND NEW.end_at IS NULL
BEGIN
  SELECT RAISE(ABORT, 'cannot lock an open session');
END""",
        """CREATE TRIGGER trg_sessions_lock_same_worker
BEFORE UPDATE OF settlement_id ON sessions
WHEN NEW.settlement_id IS NOT NULL
  AND (SELECT worker_id FROM settlements WHERE id = NEW.settlement_id) IS NOT NEW.worker_id
BEGIN
  SELECT RAISE(ABORT, 'settlement belongs to another worker');
END""",
        """CREATE TRIGGER trg_money_lock_same_worker
BEFORE UPDATE OF settlement_id ON money_transactions
WHEN NEW.settlement_id IS NOT NULL
  AND (SELECT worker_id FROM settlements WHERE id = NEW.settlement_id) IS NOT NEW.worker_id
BEGIN
  SELECT RAISE(ABORT, 'settlement belongs to another worker');
END""",
        """CREATE TRIGGER trg_settlements_immutable_update
BEFORE UPDATE ON settlements
BEGIN
  SELECT RAISE(ABORT, 'settlement is immutable');
END""",
        """CREATE TRIGGER trg_settlements_immutable_delete
BEFORE DELETE ON settlements
BEGIN
  SELECT RAISE(ABORT, 'settlement is immutable');
END""",
        """CREATE TRIGGER trg_workers_no_delete
BEFORE DELETE ON workers
BEGIN
  SELECT RAISE(ABORT, 'workers are archived, not deleted');
END""",
    ),
)
