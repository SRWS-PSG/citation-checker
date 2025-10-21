from __future__ import annotations

import os
import time
import urllib.parse
from dataclasses import dataclass
import re
import unicodedata

import requests
from dotenv import load_dotenv
from .parser import extract_title_candidate
from .pubmed import PubMedClient

API = "https://api.crossref.org/works"
RETRACTION_TYPES = {"retraction", "withdrawal", "removal", "partial_retraction"}

load_dotenv()
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "you@example.com")
UA = {"User-Agent": f"ref-audit/0.1 (mailto:{CONTACT_EMAIL})"}


@dataclass
class MatchResult:
    input_text: str
    doi: str | None
    title: str | None
    found: bool
    retracted: bool
    retraction_details: list[dict]
    method: str | None = None  # 'doi', 'bibliographic', or 'doi->bibliographic'
    note: str | None = None    # reason/hint when not found
    candidates: list[dict] | None = None  # optional debug candidates
    suggestions: list[str] | None = None  # follow-up actions for operators


_SYNONYMS = [
    (r"\bcaeserean\b", "cesarean"),
    (r"\bcaesarean\b", "cesarean"),
    (r"\banaesthesia\b", "anesthesia"),
    (r"\banaesthetic\b", "anesthetic"),
    (r"\bhaemodynamics?\b", "hemodynamic"),
    (r"\bhaemoglobin\b", "hemoglobin"),
    (r"\bfoetus\b", "fetus"),
    (r"\bfoetal\b", "fetal"),
    (r"\brandomised\b", "randomized"),
]


def _apply_synonyms(s: str) -> str:
    out = s
    for pat, rep in _SYNONYMS:
        out = re.sub(pat, rep, out)
    return out


def _normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"\s+", " ", s)
    s = _apply_synonyms(s)
    # remove punctuation-like characters but keep spaces and alnum
    s = re.sub(r"[^\w\s]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_year(text: str) -> int | None:
    m = re.search(r"\b(19|20)\d{2}\b", text)
    return int(m.group(0)) if m else None


def _title_matches_strict(ref_line: str, candidate_title: str) -> bool:
    ref_n = _normalize_text(ref_line)
    tit_n = _normalize_text(candidate_title or "")
    if not tit_n:
        return False
    # exact-ish: title substring contained either way
    if tit_n in ref_n or ref_n in tit_n:
        return True
    # fallback: require high token overlap (all candidate tokens appear in ref)
    tit_tokens = [t for t in tit_n.split() if len(t) > 2]
    if not tit_tokens:
        return False
    missing = [t for t in tit_tokens if t not in ref_n]
    return len(missing) == 0


class CrossrefClient:
    def __init__(self, pause_sec: float = 0.2, strict: bool = True, debug: bool = False):
        self.session = requests.Session()
        self.session.headers.update(UA)
        self.pause_sec = pause_sec
        self.strict = strict
        self.debug = debug

    def _get(self, url: str, params: dict | None = None):
        try:
            r = self.session.get(url, params=params, timeout=30)
            r.raise_for_status()
            time.sleep(self.pause_sec)
            return r.json()
        except requests.RequestException:
            # Network/API failure: degrade gracefully so pipeline can complete
            return None

    def search_bibliographic(self, ref: str) -> dict | None:
        # Backward compatible: return top item if any
        items = self.search_bibliographic_items(ref)
        return items[0] if items else None

    def search_bibliographic_items(self, ref: str, rows: int = 5) -> list[dict]:
        params = {
            "query.bibliographic": ref,
            "rows": rows,
            "select": "DOI,title,issued,published-print,published-online,container-title,volume,issue,page,type",
        }
        js = self._get(API, params)
        if not js:
            return []
        return js.get("message", {}).get("items", [])

    def get_work(self, doi: str) -> dict | None:
        url = f"{API}/{urllib.parse.quote(doi)}"
        # 'select' is not supported on works/{doi}; fetch full and pick fields
        js = self._get(url, params=None)
        if not js:
            return None
        return js.get("message", None)

    def find_updates_for(self, doi: str) -> list[dict]:
        params = {
            "filter": f"updates:{doi},is-update:true",
            "rows": 1000,
        }
        js = self._get(API, params)
        if not js:
            return []
        return js.get("message", {}).get("items", [])

    def is_retracted(self, doi: str) -> tuple[bool, list[dict]]:
        notices = self.find_updates_for(doi)
        hits: list[dict] = []
        for n in notices:
            for ut in n.get("update-to", []):
                ut_type = (ut.get("type") or "").lower()
                if ut_type in RETRACTION_TYPES:
                    hits.append(
                        {
                            "notice_doi": n.get("DOI"),
                            "update_type": ut.get("type"),
                            "source": ut.get("source"),
                            "updated": ut.get("updated", {}),
                            "label": ut.get("label"),
                        }
                    )
        return (len(hits) > 0, hits)

    def check_one(self, input_text: str) -> MatchResult:
        from .parser import extract_doi

        doi = extract_doi(input_text)
        work = None
        method: str | None = None
        if doi:
            method = "doi"
            work = self.get_work(doi)
            if not work:
                # Fallback to bibliographic match when direct DOI lookup fails
                method = "doi->bibliographic"
                # Try multiple candidates and choose strict match if enabled
                for cand in self.search_bibliographic_items(input_text):
                    title = (cand.get("title") or [None])[0]
                    if not self.strict or _title_matches_strict(input_text, title):
                        work = cand
                        break
        else:
            method = "bibliographic"
            # Try multiple candidates and pick first strict match if required
            for cand in self.search_bibliographic_items(input_text):
                title = (cand.get("title") or [None])[0]
                if not self.strict or _title_matches_strict(input_text, title):
                    work = cand
                    break

        if not work:
            # Fallback: try PubMed exact title match when Crossref has no hit
            title_guess = extract_title_candidate(input_text) or ""
            if title_guess:
                pm = PubMedClient()
                pm_hits = pm.search_title_exact(title_guess)
                chosen = None
                for hit in pm_hits:
                    if _normalize_text(hit.title) == _normalize_text(title_guess):
                        chosen = hit
                        break
                if chosen:
                    retracted, details = (False, [])
                    if chosen.doi:
                        retracted, details = self.is_retracted(chosen.doi)
                    return MatchResult(
                        input_text,
                        chosen.doi,
                        chosen.title,
                        found=True,
                        retracted=retracted,
                        retraction_details=details,
                        method="pubmed-title",
                        note=None,
                        candidates=None,
                    )
            cands = None
            suggestions: list[str] = []
            if title_guess:
                suggestions.append(f"タイトル候補でウェブ検索: \"{title_guess}\"")
                search_url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(title_guess)
                suggestions.append(f"Google検索: {search_url}")
            suggestions = suggestions or None
            if self.debug:
                # collect top 3 candidates for troubleshooting
                cands = []
                for cand in self.search_bibliographic_items(input_text, rows=3):
                    cands.append({
                        "DOI": cand.get("DOI"),
                        "title": (cand.get("title") or [None])[0],
                        "year": (cand.get("published-print") or cand.get("issued") or {}).get("date-parts", [[None]])[0][0],
                        "container": (cand.get("container-title") or [None])[0],
                        "page": cand.get("page"),
                    })
            return MatchResult(
                input_text,
                None,
                None,
                found=False,
                retracted=False,
                retraction_details=[],
                method=method,
                note="no_match",
                candidates=cands,
                suggestions=suggestions,
            )

        # If strict (and not direct DOI), enforce title and year checks
        title = (work.get("title") or [None])[0]
        if self.strict and method != "doi" and title and not _title_matches_strict(input_text, title):
            return MatchResult(
                input_text,
                None,
                None,
                found=False,
                retracted=False,
                retraction_details=[],
                method=method,
                note="title_mismatch",
                candidates=None,
            )

        ref_year = _extract_year(input_text)
        work_year = None
        # Prefer published-print year if available, else issued, else published-online
        def year_from(field: str) -> int | None:
            obj = work.get(field, {})
            if isinstance(obj, dict):
                parts = obj.get("date-parts") or []
                if parts and parts[0]:
                    return parts[0][0]
            return None

        work_year = year_from("published-print") or year_from("issued") or year_from("published-online")

        if self.strict and method != "doi" and ref_year and work_year and ref_year != work_year:
            return MatchResult(
                input_text,
                None,
                None,
                found=False,
                retracted=False,
                retraction_details=[],
                method=method,
                note="year_mismatch",
                candidates=None,
            )

        doi = work.get("DOI")
        retracted, details = self.is_retracted(doi)
        return MatchResult(
            input_text,
            doi,
            title,
            found=True,
            retracted=retracted,
            retraction_details=details,
            method=method,
            note=None,
            candidates=None,
        )
