"""Process-wide pacing and durable, conservative HTTP attempt accounting."""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path


class RequestBudgetExceeded(RuntimeError):
    pass


class BudgetLedgerError(RuntimeError):
    pass


class DurableLedger:
    """Exclusive SQLite ledger. A reservation is committed before HTTP transport.

    A reserved row without a response remains consumed: the provider may have
    processed it even if the client died before receiving a reply.
    """
    def __init__(self, path, *, interval_seconds, max_requests, resume):
        import fcntl
        self.path = Path(path).resolve()
        self.lock_fd = os.open(str(self.path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600)
        self.db = None
        try:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise BudgetLedgerError('budget ledger is already in use') from exc
            if resume:
                if not self.path.is_file():
                    raise BudgetLedgerError('budget ledger is missing')
            else:
                try:
                    fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError as exc:
                    raise BudgetLedgerError('budget ledger already exists') from exc
                os.close(fd)
            self.db = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            self.db.execute('PRAGMA synchronous=FULL')
            if not resume:
                self.db.executescript('''CREATE TABLE settings (cap INTEGER NOT NULL, interval REAL NOT NULL);
                    CREATE TABLE attempts (id INTEGER PRIMARY KEY, status TEXT NOT NULL, http_status INTEGER);
                ''')
                self.db.execute('INSERT INTO settings VALUES (?, ?)', (max_requests, interval_seconds))
                self.db.commit()
            row = self.db.execute('SELECT cap, interval FROM settings').fetchall()
            if row != [(max_requests, float(interval_seconds))]:
                raise BudgetLedgerError('budget settings do not match the original ledger')
            bad = self.db.execute("SELECT COUNT(*) FROM attempts WHERE status NOT IN ('reserved', 'response_received')").fetchone()[0]
            if bad or self.count() > max_requests:
                raise BudgetLedgerError('budget ledger contents are inconsistent')
        except BaseException:
            self.close()
            raise

    def count(self):
        return self.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]

    def reserve(self):
        with self.db:
            if self.count() >= self.db.execute('SELECT cap FROM settings').fetchone()[0]:
                raise RequestBudgetExceeded('Development HTTP request budget exhausted')
            cur = self.db.execute("INSERT INTO attempts (status) VALUES ('reserved')")
            return cur.lastrowid

    def received(self, attempt_id, status):
        with self.db:
            cur = self.db.execute("UPDATE attempts SET status='response_received', http_status=? WHERE id=? AND status='reserved'", (status, attempt_id))
            if cur.rowcount != 1:
                raise BudgetLedgerError('attempt reservation was not found or already completed')

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None


@dataclass
class RequestBudget:
    interval_seconds: float
    max_requests: int
    requests: int = 0
    _next_request: float = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    ledger: DurableLedger | None = field(default=None, repr=False)

    def acquire(self):
        with self._lock:
            if self.requests >= self.max_requests:
                raise RequestBudgetExceeded('Development HTTP request budget exhausted')
            delay = max(0.0, self._next_request - time.monotonic())
            if delay:
                time.sleep(delay)
            attempt_id = self.ledger.reserve() if self.ledger is not None else None
            self.requests += 1
            self._next_request = time.monotonic() + self.interval_seconds
            return attempt_id

    def response_received(self, attempt_id, status):
        if self.ledger is not None and attempt_id is not None:
            with self._lock:
                self.ledger.received(attempt_id, status)


_active_budget: RequestBudget | None = None
_setup_lock = threading.Lock()


def before_request(request):
    budget = _active_budget
    if budget is not None:
        attempt_id = budget.acquire()
        request.extensions['swarm_canvas_budget'] = (budget, attempt_id)
        if attempt_id is not None:
            from swarm_canvas.tracing import record_budget_attempt
            record_budget_attempt(attempt_id, 'reserved')


def after_response(response):
    value = response.request.extensions.get('swarm_canvas_budget')
    if value is not None:
        budget, attempt_id = value
        budget.response_received(attempt_id, response.status_code)
        if attempt_id is not None:
            from swarm_canvas.tracing import record_budget_attempt
            record_budget_attempt(attempt_id, 'response', response.status_code)


@contextmanager
def model_request_budget(*, interval_seconds: float, max_requests: int, ledger_path=None, resume=False):
    global _active_budget
    if (not 0 <= interval_seconds <= 60 or not isinstance(max_requests, int)
            or isinstance(max_requests, bool) or max_requests < 1):
        raise ValueError('Request interval must be between 0 and 60 seconds; budget must be positive')
    if resume and ledger_path is None:
        raise ValueError('resuming a budget requires its existing ledger')
    with _setup_lock:
        if _active_budget is not None:
            raise RuntimeError('Concurrent or nested model budgets in one process are unsupported')
        ledger = DurableLedger(ledger_path, interval_seconds=interval_seconds,
                               max_requests=max_requests, resume=resume) if ledger_path is not None else None
        budget = RequestBudget(interval_seconds, max_requests, ledger=ledger)
        if ledger is not None:
            budget.requests = ledger.count()
            if resume and budget.requests:
                # The previous monotonic clock may belong to another process.
                budget._next_request = time.monotonic() + interval_seconds
        _active_budget = budget
    try:
        yield budget
    finally:
        with _setup_lock:
            _active_budget = None
            if ledger is not None:
                ledger.close()


def inspect_ledger(path):
    """Read aggregate accounting without changing or reclaiming reservations."""
    path = Path(path).resolve()
    if not path.is_file():
        raise BudgetLedgerError('budget ledger is missing')
    with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
        settings = db.execute('SELECT cap, interval FROM settings').fetchall()
        if len(settings) != 1:
            raise BudgetLedgerError('budget settings are inconsistent')
        cap, interval = settings[0]
        counts = dict(db.execute('SELECT status, COUNT(*) FROM attempts GROUP BY status'))
        if any(key not in ('reserved', 'response_received') for key in counts):
            raise BudgetLedgerError('budget ledger contents are inconsistent')
        used = sum(counts.values())
        if used > cap:
            raise BudgetLedgerError('budget ledger exceeds its cap')
        return {'max_requests': cap, 'interval_seconds': interval, 'attempts_reserved': used,
                'responses_received': counts.get('response_received', 0),
                'without_recorded_response': counts.get('reserved', 0),
                'remaining_attempts': cap - used}


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Inspect a durable model request ledger')
    parser.add_argument('ledger')
    print(json.dumps(inspect_ledger(parser.parse_args().ledger), indent=2))
