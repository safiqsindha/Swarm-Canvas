"""Process-wide pacing and a hard HTTP request cap for bounded development runs."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field


class RequestBudgetExceeded(RuntimeError):
    pass


@dataclass
class RequestBudget:
    interval_seconds: float
    max_requests: int
    requests: int = 0
    _next_request: float = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def acquire(self):
        with self._lock:
            if self.requests >= self.max_requests:
                raise RequestBudgetExceeded("Development HTTP request budget exhausted")
            delay = max(0.0, self._next_request - time.monotonic())
            if delay:
                time.sleep(delay)
            self.requests += 1
            self._next_request = time.monotonic() + self.interval_seconds


_active_budget: RequestBudget | None = None
_setup_lock = threading.Lock()


def before_request(request):
    budget = _active_budget
    if budget is not None:
        budget.acquire()


@contextmanager
def model_request_budget(*, interval_seconds: float, max_requests: int):
    global _active_budget
    if (
        not 0 <= interval_seconds <= 60
        or not isinstance(max_requests, int)
        or isinstance(max_requests, bool)
        or max_requests < 1
    ):
        raise ValueError(
            "Request interval must be between 0 and 60 seconds; budget must be positive"
        )
    budget = RequestBudget(interval_seconds, max_requests)
    with _setup_lock:
        if _active_budget is not None:
            raise RuntimeError(
                "Concurrent or nested model budgets in one process are unsupported"
            )
        _active_budget = budget
    try:
        yield budget
    finally:
        with _setup_lock:
            _active_budget = None
