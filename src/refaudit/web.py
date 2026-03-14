from __future__ import annotations

from dataclasses import asdict

from .crossref import CrossrefClient, MatchResult


def check_reference_payload(
    ref: str,
    email: str | None = None,
    pause_sec: float = 0.2,
    debug: bool = False,
) -> dict:
    result = check_reference(ref, email=email, pause_sec=pause_sec, debug=debug)
    return asdict(result)


def check_reference(
    ref: str,
    email: str | None = None,
    pause_sec: float = 0.2,
    debug: bool = False,
) -> MatchResult:
    client = CrossrefClient(pause_sec=pause_sec, debug=debug, email=email)
    return client.check_one(ref)
