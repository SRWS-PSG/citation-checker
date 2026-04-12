"""Time budget management for API calls within serverless function limits."""

from __future__ import annotations

import time


class TimeBudget:
    """Track remaining time and provide dynamic HTTP timeouts."""

    def __init__(self, total_seconds: float = 55.0):
        self._start = time.monotonic()
        self._total = total_seconds
        self.skipped: list[str] = []

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
        return {
            "elapsed_sec": round(self.elapsed, 2),
            "budget_sec": self._total,
            "skipped": self.skipped,
        }


# Sentinel: no budget constraint (CLI usage).
NO_BUDGET = TimeBudget(total_seconds=600.0)
