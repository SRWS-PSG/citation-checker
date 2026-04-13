from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import time
from typing import Literal
import urllib.parse

import requests

from .arxiv import ArxivClient, ArxivMatch
from .budget import NO_BUDGET, TimeBudget
from .doi_resolver import DOIResolver
from .jalc import JALCClient
from .nlm import NLMCatalogClient
from .etiquette import build_user_agent
from .parser import (
    contains_japanese_text,
    extract_arxiv_id,
    extract_doi,
    extract_title_candidate,
    is_website_reference,
    parse_reference_metadata,
)
from .pubmed import PubMedClient, PubMedMatch
from .scoring import (
    CandidateScore,
    ReferenceRecord,
    normalize_author_name,
    score_candidate,
    year_similarity,
)

API = "https://api.crossref.org/works"
RETRACTION_TYPES = {"retraction", "withdrawal", "removal", "partial_retraction"}


@dataclass
class MatchResult:
    input_text: str
    doi: str | None
    title: str | None
    found: bool
    retracted: bool
    retraction_details: list[dict]
    status: Literal["found", "likely_wrong", "not_found", "website"] = "not_found"
    method: str | None = None
    note: str | None = None
    candidates: list[dict] | None = None
    suggestions: list[str] | None = None
    input_authors: list[str] | None = None
    matched_authors: list[str] | None = None
    arxiv_id: str | None = None
    arxiv_doi: str | None = None
    journal_ref: str | None = None
    is_website: bool = False
    best_candidate: dict | None = None
    comparison_summary: str | None = None
    field_signals: dict[str, str] | None = None
    field_diffs: dict[str, dict] | None = None


@dataclass
class CandidateMatch:
    record: ReferenceRecord
    method: str
    score: CandidateScore


def _published_year(work: dict) -> int | None:
    for field in ("published-print", "issued", "published-online"):
        value = work.get(field)
        if isinstance(value, dict):
            parts = value.get("date-parts") or []
            if parts and parts[0]:
                return parts[0][0]
    return None


def _extract_crossref_authors(work: dict) -> list[str]:
    authors: list[str] = []
    for author in work.get("author", []):
        family = normalize_author_name(author.get("family") or author.get("name") or "")
        if family:
            authors.append(family)
    return authors


def _page_to_article_number(page: str | None) -> str | None:
    if not page:
        return None
    if "-" in page:
        return None
    return page.strip()


def _is_preprint_work(work: dict) -> bool:
    work_type = (work.get("type") or "").lower()
    container = " ".join(work.get("container-title") or []).lower()
    return work_type == "posted-content" or "preprint" in container or "arxiv" in container


def _merge_records(primary: ReferenceRecord, secondary: ReferenceRecord | None) -> ReferenceRecord:
    if secondary is None:
        return primary
    venue_aliases: list[str] = []
    seen_aliases: set[str] = set()
    for value in [*primary.venue_aliases, *secondary.venue_aliases]:
        cleaned = (value or "").strip()
        if cleaned and cleaned not in seen_aliases:
            seen_aliases.add(cleaned)
            venue_aliases.append(cleaned)
    return ReferenceRecord(
        title=primary.title or secondary.title,
        authors=primary.authors or secondary.authors,
        year=primary.year or secondary.year,
        venue=primary.venue or secondary.venue,
        venue_aliases=venue_aliases,
        volume=primary.volume or secondary.volume,
        issue=primary.issue or secondary.issue,
        page=primary.page or secondary.page,
        article_number=primary.article_number or secondary.article_number,
        doi=primary.doi or secondary.doi,
        source=primary.source or secondary.source,
        source_id=primary.source_id or secondary.source_id,
        is_preprint=primary.is_preprint and secondary.is_preprint,
    )


class CrossrefClient:
    def __init__(
        self,
        pause_sec: float = 0.2,
        strict: bool = True,
        debug: bool = False,
        email: str | None = None,
        budget: TimeBudget | None = None,
    ):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": build_user_agent(email)})
        self.pause_sec = pause_sec
        self.strict = strict
        self.debug = debug
        self.email = email
        self.budget = budget or NO_BUDGET
        self._doi_cache: dict[str, tuple[dict | None, str]] = {}
        self._nlm = NLMCatalogClient(pause_sec=pause_sec, email=email, budget=self.budget)

    def _get(self, url: str, params: dict | None = None):
        if self.budget.expired:
            return None
        try:
            response = self.session.get(url, params=params, timeout=self.budget.http_timeout(10.0))
            response.raise_for_status()
            time.sleep(self.pause_sec)
            return response.json()
        except requests.RequestException:
            return None

    def search_bibliographic(self, ref: str) -> dict | None:
        items = self.search_bibliographic_items(ref)
        return items[0] if items else None

    def search_bibliographic_items(self, ref: str, rows: int = 5) -> list[dict]:
        params = {
            "query.bibliographic": ref,
            "rows": rows,
            "select": "DOI,title,issued,published-print,published-online,container-title,ISSN,volume,issue,page,type,author",
        }
        payload = self._get(API, params)
        if not payload:
            return []
        return payload.get("message", {}).get("items", [])

    def get_work(self, doi: str) -> dict | None:
        payload = self._get(f"{API}/{urllib.parse.quote(doi)}")
        if not payload:
            return None
        return payload.get("message")

    def find_updates_for(self, doi: str) -> list[dict]:
        payload = self._get(API, {"filter": f"updates:{doi},is-update:true", "rows": 1000})
        if not payload:
            return []
        return payload.get("message", {}).get("items", [])

    def is_retracted(self, doi: str | None) -> tuple[bool, list[dict]]:
        if not doi:
            return False, []
        notices = self.find_updates_for(doi)
        hits: list[dict] = []
        seen: set[tuple[str | None, str | None]] = set()
        for notice in notices:
            for update in notice.get("update-to", []):
                update_type = (update.get("type") or "").lower()
                if update_type not in RETRACTION_TYPES:
                    continue
                key = (notice.get("DOI"), update_type)
                if key in seen:
                    continue
                seen.add(key)
                hits.append(
                    {
                        "notice_doi": notice.get("DOI"),
                        "update_type": update.get("type"),
                        "source": update.get("source"),
                        "updated": update.get("updated", {}),
                        "label": update.get("label"),
                    }
                )
        return bool(hits), hits

    def _doi_metadata_to_work(self, doi_meta) -> dict:
        work = {
            "DOI": doi_meta.doi,
            "title": [doi_meta.title] if doi_meta.title else [],
            "author": [
                {"family": author.get("family", ""), "given": author.get("given", "")}
                for author in doi_meta.authors
            ],
            "container-title": [doi_meta.container_title] if doi_meta.container_title else [],
            "volume": doi_meta.volume,
            "issue": doi_meta.issue,
            "page": doi_meta.page,
            "type": "journal-article",
        }
        if doi_meta.year:
            work["issued"] = {"date-parts": [[doi_meta.year]]}
        return work

    def _resolve_doi_work(self, doi: str) -> tuple[dict | None, str]:
        if doi in self._doi_cache:
            return self._doi_cache[doi]

        resolver = DOIResolver(pause_sec=self.pause_sec, email=self.email, budget=self.budget)
        ra = resolver.detect_ra(doi)
        if ra == "Crossref":
            result = (self.get_work(doi), "doi-crossref")
            self._doi_cache[doi] = result
            return result
        if ra == "DataCite":
            doi_meta = resolver.resolve_via_datacite(doi)
            result = ((self._doi_metadata_to_work(doi_meta) if doi_meta else None), "doi-datacite")
            self._doi_cache[doi] = result
            return result
        if ra == "JaLC":
            doi_meta = resolver.resolve_via_content_negotiation(doi)
            result = ((self._doi_metadata_to_work(doi_meta) if doi_meta else None), "doi-jalc")
            self._doi_cache[doi] = result
            return result
        if ra:
            doi_meta = resolver.resolve_via_content_negotiation(doi)
            result = ((self._doi_metadata_to_work(doi_meta) if doi_meta else None), f"doi-{ra.lower()}")
            self._doi_cache[doi] = result
            return result

        work = self.get_work(doi)
        if work:
            result = (work, "doi-crossref")
            self._doi_cache[doi] = result
            return result
        doi_meta = resolver.resolve_via_content_negotiation(doi)
        result = ((self._doi_metadata_to_work(doi_meta) if doi_meta else None), "doi-content-negotiation")
        self._doi_cache[doi] = result
        return result

    def _work_to_record(self, work: dict, source: str, source_id: str | None = None) -> ReferenceRecord:
        page = work.get("page")
        venue = (work.get("container-title") or [None])[0]
        issns = work.get("ISSN") or []
        venue_aliases = self._nlm.journal_aliases(title=venue, issns=issns)
        return ReferenceRecord(
            title=(work.get("title") or [None])[0],
            authors=_extract_crossref_authors(work),
            year=_published_year(work),
            venue=venue,
            venue_aliases=venue_aliases,
            volume=work.get("volume"),
            issue=work.get("issue"),
            page=page,
            article_number=_page_to_article_number(page),
            doi=work.get("DOI"),
            source=source,
            source_id=source_id,
            is_preprint=_is_preprint_work(work),
        )

    def _pubmed_to_record(self, hit: PubMedMatch) -> ReferenceRecord:
        venue_aliases = [value for value in (hit.journal, hit.journal_full) if value]
        return ReferenceRecord(
            title=hit.title,
            authors=[normalize_author_name(author) for author in hit.authors if normalize_author_name(author)],
            year=hit.year,
            venue=hit.journal,
            venue_aliases=venue_aliases,
            volume=hit.volume,
            issue=hit.issue,
            page=hit.pages,
            article_number=_page_to_article_number(hit.pages),
            doi=hit.doi,
            source="pubmed",
            source_id=hit.pmid,
        )

    def _arxiv_to_record(self, match: ArxivMatch) -> ReferenceRecord:
        year = None
        if match.published:
            try:
                year = datetime.fromisoformat(match.published.replace("Z", "+00:00")).year
            except ValueError:
                year = None
        authors = [normalize_author_name(author) for author in match.authors if normalize_author_name(author)]
        return ReferenceRecord(
            title=match.title,
            authors=authors,
            year=year,
            venue=match.journal_ref or "arXiv",
            page=None,
            article_number=None,
            doi=match.doi,
            source="arxiv",
            source_id=match.arxiv_id,
            is_preprint=True,
        )

    def _candidate_payload(self, candidate: CandidateMatch) -> dict:
        record = candidate.record
        return {
            "title": record.title,
            "doi": record.doi,
            "source": record.source,
            "method": candidate.method,
            "score": candidate.score.total,
            "decision": candidate.score.decision,
            "field_summary": candidate.score.summary,
            "field_states": candidate.score.field_states,
            "field_diffs": candidate.score.field_diffs,
            "signals": candidate.score.signals,
            "year": record.year,
            "container": record.venue,
            "page": record.page,
            "volume": record.volume,
            "issue": record.issue,
        }

    def _result_from_candidate(
        self,
        input_text: str,
        input_record: ReferenceRecord,
        candidate: CandidateMatch,
        status: Literal["found", "likely_wrong"],
        note: str | None,
        extra_candidates: list[CandidateMatch] | None = None,
        arxiv_id: str | None = None,
        arxiv_doi: str | None = None,
        journal_ref: str | None = None,
    ) -> MatchResult:
        retracted, details = self.is_retracted(candidate.record.doi)
        candidates_payload = [self._candidate_payload(item) for item in (extra_candidates or [])] or None
        suggestions = None
        if candidates_payload:
            suggestions = [
                f"{item['title']} ({item.get('doi') or 'DOIなし'})"
                for item in candidates_payload
                if item.get("title")
            ] or None
        return MatchResult(
            input_text=input_text,
            doi=candidate.record.doi,
            title=candidate.record.title,
            found=status == "found",
            retracted=retracted,
            retraction_details=details,
            status=status,
            method=candidate.method,
            note=note,
            candidates=candidates_payload,
            suggestions=suggestions,
            input_authors=input_record.authors or None,
            matched_authors=candidate.record.authors[:5] or None,
            arxiv_id=arxiv_id,
            arxiv_doi=arxiv_doi,
            journal_ref=journal_ref,
            best_candidate=self._candidate_payload(candidate),
            comparison_summary=candidate.score.summary,
            field_signals=candidate.score.field_states,
            field_diffs=candidate.score.field_diffs,
        )

    def _sort_candidates(self, candidates: list[CandidateMatch]) -> list[CandidateMatch]:
        decision_rank = {"accept": 2, "suggest": 1, "reject": 0}
        return sorted(
            candidates,
            key=lambda candidate: (
                decision_rank[candidate.score.decision],
                candidate.score.total,
                0 if candidate.record.is_preprint else 1,
            ),
            reverse=True,
        )

    def _enrich_pubmed_candidate(
        self,
        input_record: ReferenceRecord,
        candidate: CandidateMatch,
        mode: Literal["verification", "correction"],
    ) -> CandidateMatch:
        if not candidate.method.startswith("pubmed") or not candidate.record.doi:
            return candidate

        work, doi_method = self._resolve_doi_work(candidate.record.doi)
        if not work:
            return candidate

        enriched_record = _merge_records(
            candidate.record,
            self._work_to_record(work, source="pubmed-doi", source_id=candidate.record.source_id),
        )
        enriched_score = score_candidate(
            input_record,
            enriched_record,
            mode=mode,
            strict=self.strict,
        )
        return CandidateMatch(
            record=enriched_record,
            method=f"{candidate.method}+{doi_method}",
            score=enriched_score,
        )

    def _collect_crossref_candidates(self, input_text: str) -> list[tuple[ReferenceRecord, str]]:
        items = self.search_bibliographic_items(input_text, rows=5)
        return [(self._work_to_record(item, source="crossref"), "bibliographic") for item in items]

    def _collect_pubmed_candidates(self, input_text: str, title_guess: str | None) -> list[tuple[ReferenceRecord, str]]:
        pubmed = PubMedClient(email=self.email, budget=self.budget)
        seen: set[tuple[str | None, str | None]] = set()
        collected: list[tuple[ReferenceRecord, str]] = []
        for hit in pubmed.search_full_citation(input_text):
            record = self._pubmed_to_record(hit)
            key = (record.doi, record.title)
            if key not in seen:
                seen.add(key)
                collected.append((record, "pubmed-full-citation"))
        if title_guess:
            for hit in pubmed.search_title_exact(title_guess):
                record = self._pubmed_to_record(hit)
                key = (record.doi, record.title)
                if key not in seen:
                    seen.add(key)
                    collected.append((record, "pubmed-title"))
        return collected

    def _collect_arxiv_candidates(
        self,
        arxiv_id: str | None,
        title_guess: str | None,
        input_authors: list[str],
    ) -> tuple[list[tuple[ReferenceRecord, str]], str | None, str | None, str | None]:
        if not arxiv_id and not title_guess:
            return [], None, None, None

        arxiv = ArxivClient(pause_sec=max(self.pause_sec, 3.0), budget=self.budget)
        collected: list[tuple[ReferenceRecord, str]] = []
        match: ArxivMatch | None = None
        method = "arxiv-no-query"
        if arxiv_id:
            match, method = arxiv.verify_reference(arxiv_id=arxiv_id)
        elif title_guess:
            match, method = arxiv.verify_reference(title=title_guess, authors=input_authors)

        if not match:
            return [], arxiv_id, None, None

        arxiv_record = self._arxiv_to_record(match)
        collected.append((arxiv_record, method))
        if match.doi:
            work, doi_method = self._resolve_doi_work(match.doi)
            if work:
                collected.insert(0, (self._work_to_record(work, source="arxiv-published"), doi_method))
        elif match.title:
            query = f"{match.title} {' '.join(input_authors[:2])}".strip()
            for item in self.search_bibliographic_items(query, rows=3):
                collected.append((self._work_to_record(item, source="arxiv-crossref"), "arxiv-crossref"))
        return collected, match.arxiv_id, match.doi, match.journal_ref

    def _collect_jalc_candidates(self, title_guess: str | None) -> list[tuple[ReferenceRecord, str]]:
        if not title_guess or not contains_japanese_text(title_guess):
            return []

        jalc = JALCClient(pause_sec=self.pause_sec, email=self.email, budget=self.budget)
        collected: list[tuple[ReferenceRecord, str]] = []
        for hit in jalc.search_title(title_guess, rows=5):
            doi = hit.get("doi")
            title = hit.get("title")
            if not doi:
                continue
            work, doi_method = self._resolve_doi_work(doi)
            if work:
                collected.append((self._work_to_record(work, source="jalc", source_id=doi), f"jalc-title+{doi_method}"))
                continue
            collected.append(
                (
                    ReferenceRecord(
                        title=title,
                        doi=doi,
                        source="jalc-search",
                        source_id=doi,
                    ),
                    "jalc-title",
                )
            )
        return collected

    def _evaluate_candidates(
        self,
        input_record: ReferenceRecord,
        raw_candidates: list[tuple[ReferenceRecord, str]],
        mode: Literal["verification", "correction"] = "verification",
    ) -> list[CandidateMatch]:
        deduped: list[tuple[ReferenceRecord, str]] = []
        seen: set[tuple[str | None, str | None, str | None]] = set()
        for record, method in raw_candidates:
            key = (record.doi, record.title, record.source_id)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((record, method))

        evaluated = [
            CandidateMatch(
                record=record,
                method=method,
                score=score_candidate(input_record, record, mode=mode, strict=self.strict),
            )
            for record, method in deduped
        ]
        if mode == "verification":
            enriched: list[CandidateMatch] = []
            for candidate in evaluated:
                if candidate.score.decision == "accept":
                    candidate = self._enrich_pubmed_candidate(input_record, candidate, mode)
                enriched.append(candidate)
            evaluated = enriched
        return self._sort_candidates(evaluated)

    def check_one(self, input_text: str) -> MatchResult:
        input_record = parse_reference_metadata(input_text)
        input_doi = extract_doi(input_text)
        input_arxiv_id = extract_arxiv_id(input_text)
        title_guess = input_record.title or extract_title_candidate(input_text)

        if is_website_reference(input_text):
            return MatchResult(
                input_text=input_text,
                doi=None,
                title=None,
                found=True,
                retracted=False,
                retraction_details=[],
                status="website",
                method="website",
                note="website_reference",
                is_website=True,
                input_authors=input_record.authors or None,
            )

        if input_doi:
            work, method = self._resolve_doi_work(input_doi)
            if not work:
                return MatchResult(
                    input_text=input_text,
                    doi=input_doi,
                    title=None,
                    found=False,
                    retracted=False,
                    retraction_details=[],
                    status="not_found",
                    method=method,
                    note="doi_not_resolved",
                    input_authors=input_record.authors or None,
                    suggestions=[
                        f"DOI解決失敗: {input_doi}",
                        f"doi.orgで確認: https://doi.org/{input_doi}",
                    ],
                )

            record = self._work_to_record(work, source="doi", source_id=input_doi)
            score = score_candidate(input_record, record, mode="verification", strict=self.strict)
            note = None
            if input_record.year is not None and record.year is not None and year_similarity(input_record.year, record.year) == 0.7:
                note = "year_warning"
            candidate = CandidateMatch(record=record, method=method, score=score)
            status: Literal["found", "likely_wrong"] = "found" if score.decision == "accept" else "likely_wrong"
            if status == "likely_wrong":
                note = score.note or note or "candidate_mismatch"
            return self._result_from_candidate(input_text, input_record, candidate, status, note)

        raw_candidates = self._collect_crossref_candidates(input_text)
        arxiv_id, arxiv_doi, journal_ref = None, None, None
        if not self.budget.expired:
            raw_candidates.extend(self._collect_pubmed_candidates(input_text, title_guess))
        else:
            self.budget.skipped.append("pubmed")
        if not self.budget.expired or input_arxiv_id:
            arxiv_candidates, arxiv_id, arxiv_doi, journal_ref = self._collect_arxiv_candidates(
                input_arxiv_id,
                title_guess if not self.budget.expired else None,
                input_record.authors,
            )
            raw_candidates.extend(arxiv_candidates)
        else:
            self.budget.skipped.append("arxiv")
        if not self.budget.expired:
            raw_candidates.extend(self._collect_jalc_candidates(title_guess))
        else:
            self.budget.skipped.append("jalc")

        verified = self._evaluate_candidates(input_record, raw_candidates, mode="verification")
        accepted = [candidate for candidate in verified if candidate.score.decision == "accept"]
        if accepted:
            chosen = accepted[0]
            note = None
            if input_record.year is not None and chosen.record.year is not None and year_similarity(input_record.year, chosen.record.year) == 0.7:
                note = "year_warning"
            return self._result_from_candidate(
                input_text,
                input_record,
                chosen,
                "found",
                note,
                arxiv_id=arxiv_id,
                arxiv_doi=arxiv_doi,
                journal_ref=journal_ref,
            )

        correction = self._evaluate_candidates(input_record, raw_candidates, mode="correction")
        suggestions = [candidate for candidate in correction if candidate.score.decision == "suggest"]
        if suggestions:
            chosen = suggestions[0]
            top = suggestions[:3]
            note = chosen.score.note or "candidate_mismatch"
            return self._result_from_candidate(
                input_text,
                input_record,
                chosen,
                "likely_wrong",
                note,
                extra_candidates=top,
                arxiv_id=arxiv_id,
                arxiv_doi=arxiv_doi,
                journal_ref=journal_ref,
            )

        debug_candidates = None
        if self.debug and correction:
            debug_candidates = [self._candidate_payload(candidate) for candidate in correction[:3]]
        suggestions_text = None
        if title_guess:
            suggestions_text = [
                f"タイトル候補でウェブ検索: \"{title_guess}\"",
                "Google検索: https://www.google.com/search?q=" + urllib.parse.quote_plus(title_guess),
            ]
        return MatchResult(
            input_text=input_text,
            doi=None,
            title=None,
            found=False,
            retracted=False,
            retraction_details=[],
            status="not_found",
            method="bibliographic",
            note="no_match",
            candidates=debug_candidates,
            suggestions=suggestions_text,
            input_authors=input_record.authors or None,
            arxiv_id=arxiv_id,
            arxiv_doi=arxiv_doi,
            journal_ref=journal_ref,
        )
