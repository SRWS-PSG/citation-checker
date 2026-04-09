from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Literal


ACCEPT_THRESHOLD = 0.74
SUGGEST_THRESHOLD = 0.45
AUTHOR_OVERLAP_ACCEPT = 0.5
AUTHOR_OVERLAP_SUGGEST = 0.25
TITLE_ACCEPT = 0.72
TITLE_SUGGEST = 0.45
YEAR_WARNING_DELTA = 1
PREPRINT_PENALTY = 0.1


@dataclass
class ReferenceRecord:
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    volume: str | None = None
    issue: str | None = None
    page: str | None = None
    article_number: str | None = None
    doi: str | None = None
    source: str | None = None
    source_id: str | None = None
    is_preprint: bool = False


@dataclass
class CandidateScore:
    total: float
    decision: Literal["accept", "suggest", "reject"]
    signals: dict[str, float]
    field_states: dict[str, str]
    summary: str
    note: str | None = None


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_token(value: str | None) -> str:
    token = unicodedata.normalize("NFKC", value or "").strip().lower()
    token = re.sub(r"[^\w\u3040-\u30ff\u3400-\u9fff-]", "", token)
    return token


def normalize_author_name(name: str | None) -> str:
    raw = unicodedata.normalize("NFKC", name or "").strip()
    token = normalize_token(raw)
    if not token:
        return ""
    if re.fullmatch(r"[\u3040-\u30ff\u3400-\u9fff]+", token):
        return token[:2] if len(token) >= 2 else token
    if "," in raw:
        token = normalize_token(raw.split(",", 1)[0])
        if token:
            return token
    raw = raw.replace(".", " ")
    parts = [normalize_token(part) for part in re.split(r"\s+", raw) if len(normalize_token(part)) > 1]
    if not parts:
        return token
    return parts[0]


def _token_overlap(left: str | None, right: str | None) -> float:
    left_tokens = {token for token in normalize_text(left).split() if len(token) > 1}
    right_tokens = {token for token in normalize_text(right).split() if len(token) > 1}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(len(left_tokens), len(right_tokens))


def _sequence_similarity(left: str | None, right: str | None) -> float:
    a = normalize_text(left)
    b = normalize_text(right)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def title_similarity(left: str | None, right: str | None) -> float:
    overlap = _token_overlap(left, right)
    seq = _sequence_similarity(left, right)
    return round(max(overlap, seq), 3)


def author_overlap(input_authors: list[str], candidate_authors: list[str]) -> float:
    left = {normalize_author_name(author) for author in input_authors if normalize_author_name(author)}
    right = {normalize_author_name(author) for author in candidate_authors if normalize_author_name(author)}
    if not left or not right:
        return 0.0
    return round(len(left & right) / max(len(left), len(right)), 3)


def first_author_match(input_authors: list[str], candidate_authors: list[str]) -> float:
    if not input_authors or not candidate_authors:
        return 0.0
    left = normalize_author_name(input_authors[0])
    right = normalize_author_name(candidate_authors[0])
    return 1.0 if left and right and left == right else 0.0


def year_similarity(input_year: int | None, candidate_year: int | None) -> float:
    if input_year is None or candidate_year is None:
        return 0.0
    delta = abs(input_year - candidate_year)
    if delta == 0:
        return 1.0
    if delta == 1:
        return 0.7
    if delta == 2:
        return 0.3
    return 0.0


def venue_similarity(left: str | None, right: str | None) -> float:
    overlap = _token_overlap(left, right)
    seq = _sequence_similarity(left, right)
    return round(max(overlap, seq), 3)


def _normalize_numeric(value: str | None) -> str:
    return re.sub(r"[^\w]", "", normalize_text(value))


def volume_issue_similarity(
    input_volume: str | None,
    input_issue: str | None,
    candidate_volume: str | None,
    candidate_issue: str | None,
) -> float:
    if not input_volume and not input_issue:
        return 0.0
    if input_volume and candidate_volume and _normalize_numeric(input_volume) != _normalize_numeric(candidate_volume):
        return 0.0
    if input_issue and candidate_issue and _normalize_numeric(input_issue) != _normalize_numeric(candidate_issue):
        return 0.0
    score = 0.0
    if input_volume and candidate_volume:
        score += 0.7
    elif input_volume or candidate_volume:
        score += 0.2
    if input_issue and candidate_issue:
        score += 0.3
    elif input_issue or candidate_issue:
        score += 0.1
    return round(min(score, 1.0), 3)


def page_similarity(
    input_page: str | None,
    input_article_number: str | None,
    candidate_page: str | None,
    candidate_article_number: str | None,
) -> float:
    left_values = [_normalize_numeric(input_page), _normalize_numeric(input_article_number)]
    right_values = [_normalize_numeric(candidate_page), _normalize_numeric(candidate_article_number)]
    left_values = [value for value in left_values if value]
    right_values = [value for value in right_values if value]
    if not left_values or not right_values:
        return 0.0
    for left in left_values:
        for right in right_values:
            if left == right:
                return 1.0
            if left in right or right in left:
                return 0.8
    return 0.0


def is_preprint_like(record: ReferenceRecord) -> bool:
    if record.is_preprint:
        return True
    source = normalize_text(record.source)
    venue = normalize_text(record.venue)
    title = normalize_text(record.title)
    preprint_markers = {"arxiv", "preprints", "biorxiv", "medrxiv"}
    return any(marker in source or marker in venue or marker in title for marker in preprint_markers)


def _field_state(score: float, available: bool) -> str:
    if not available:
        return "?"
    if score >= 0.7:
        return "ok"
    if score >= 0.35:
        return "~"
    return "x"


def _build_summary(field_states: dict[str, str]) -> str:
    keys = ("title", "authors", "year", "venue", "pages")
    return " / ".join(f"{key} {field_states.get(key, '?')}" for key in keys)


def score_candidate(
    reference: ReferenceRecord,
    candidate: ReferenceRecord,
    mode: Literal["verification", "correction"] = "verification",
    strict: bool = True,
) -> CandidateScore:
    title_score = title_similarity(reference.title, candidate.title)
    author_score = author_overlap(reference.authors, candidate.authors)
    first_author_score = first_author_match(reference.authors, candidate.authors)
    year_score = year_similarity(reference.year, candidate.year)
    venue_score = venue_similarity(reference.venue, candidate.venue)
    volume_issue_score = volume_issue_similarity(
        reference.volume,
        reference.issue,
        candidate.volume,
        candidate.issue,
    )
    page_score = page_similarity(
        reference.page,
        reference.article_number,
        candidate.page,
        candidate.article_number,
    )

    signals = {
        "title_similarity": title_score,
        "author_overlap": author_score,
        "first_author_match": first_author_score,
        "year_similarity": year_score,
        "venue_similarity": venue_score,
        "volume_issue_similarity": volume_issue_score,
        "page_similarity": page_score,
    }

    total = (
        title_score * 0.3
        + author_score * 0.2
        + first_author_score * 0.1
        + year_score * 0.1
        + venue_score * 0.1
        + volume_issue_score * 0.08
        + page_score * 0.12
    )
    note = None
    if is_preprint_like(candidate):
        total -= PREPRINT_PENALTY
        note = "preprint_only"
    total = round(max(total, 0.0), 3)

    field_states = {
        "title": _field_state(title_score, bool(reference.title and candidate.title)),
        "authors": _field_state(
            max(author_score, first_author_score),
            bool(reference.authors and candidate.authors),
        ),
        "year": _field_state(year_score, reference.year is not None and candidate.year is not None),
        "venue": _field_state(venue_score, bool(reference.venue and candidate.venue)),
        "pages": _field_state(
            max(volume_issue_score, page_score),
            bool(reference.page or reference.article_number or reference.volume or reference.issue)
            and bool(candidate.page or candidate.article_number or candidate.volume or candidate.issue),
        ),
    }

    accept_threshold = ACCEPT_THRESHOLD if strict else ACCEPT_THRESHOLD - 0.06
    hard_title_threshold = TITLE_ACCEPT if strict else TITLE_SUGGEST
    hard_author_threshold = AUTHOR_OVERLAP_ACCEPT if strict else AUTHOR_OVERLAP_SUGGEST
    hard_title_ok = title_score >= hard_title_threshold
    hard_author_ok = first_author_score == 1.0 or author_score >= hard_author_threshold
    strong_support_count = sum(
        score >= threshold
        for score, threshold in (
            (title_score, TITLE_SUGGEST),
            (author_score, AUTHOR_OVERLAP_SUGGEST),
            (first_author_score, 1.0),
            (year_score, 0.7),
            (venue_score, 0.6),
            (page_score, 0.8),
            (volume_issue_score, 0.7),
        )
    )
    conflicting_year = reference.year is not None and candidate.year is not None and year_score == 0.0

    if (
        total >= accept_threshold
        and hard_title_ok
        and hard_author_ok
        and not conflicting_year
        and not is_preprint_like(candidate)
    ):
        decision: Literal["accept", "suggest", "reject"] = "accept"
    elif total >= SUGGEST_THRESHOLD and strong_support_count >= 2:
        decision = "suggest"
        note = note or "candidate_mismatch"
    else:
        decision = "reject"

    if mode == "correction" and decision == "reject" and total >= SUGGEST_THRESHOLD and strong_support_count >= 2:
        decision = "suggest"
        note = note or "candidate_mismatch"

    return CandidateScore(
        total=total,
        decision=decision,
        signals=signals,
        field_states=field_states,
        summary=_build_summary(field_states),
        note=note,
    )
