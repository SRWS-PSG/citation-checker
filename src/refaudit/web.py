from __future__ import annotations

from dataclasses import asdict

from .budget import TimeBudget
from .crossref import CrossrefClient, MatchResult


def check_reference_payload(
    ref: str,
    email: str | None = None,
    pause_sec: float = 0.2,
    debug: bool = False,
    budget: TimeBudget | None = None,
) -> dict:
    result = check_reference(ref, email=email, pause_sec=pause_sec, debug=debug, budget=budget)
    return asdict(result)


def check_reference(
    ref: str,
    email: str | None = None,
    pause_sec: float = 0.2,
    debug: bool = False,
    budget: TimeBudget | None = None,
) -> MatchResult:
    client = CrossrefClient(pause_sec=pause_sec, debug=debug, email=email, budget=budget)
    return client.check_one(ref)
