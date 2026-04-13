"""Time budget management for API calls within serverless function limits."""

from __future__ import annotations

import time
from threading import Lock


class TimeBudget:
    """Track remaining time and provide dynamic HTTP timeouts."""

    def __init__(self, total_seconds: float = 55.0):
        self._start = time.monotonic()
        self._total = total_seconds
        self.skipped: list[str] = []
        self.source_errors: dict[str, str] = {}
        self._lock = Lock()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start

    @property
    def remaining(self) -> float:
        return max(0.0, self._total - self.elapsed)

    @property
    def expired(self) -> bool:
        return self.remaining <= 1.0

    def http_timeout(self, default: float = 10.0) -> float:
        """Return timeout for next HTTP call, capped by remaining budget."""
        remaining = self.remaining - 1.0  # keep 1s buffer
        if remaining <= 0:
            return 0.5
        return min(default, remaining)

    def diagnostics(self) -> dict:
        """Return diagnostics dict to embed in API response."""
        with self._lock:
            skipped = list(self.skipped)
            source_errors = dict(self.source_errors)
        return {
            "elapsed_sec": round(self.elapsed, 2),
            "budget_sec": self._total,
            "skipped": skipped,
            "source_errors": source_errors,
        }

    def mark_skipped(self, source: str) -> None:
        with self._lock:
            if source not in self.skipped:
                self.skipped.append(source)

    def mark_source_error(self, source: str, error: str) -> None:
        with self._lock:
            self.source_errors[source] = error


# Sentinel: no budget constraint (CLI usage).
NO_BUDGET = TimeBudget(total_seconds=600.0)
