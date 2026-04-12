from __future__ import annotations

import time
import xml.etree.ElementTree as ET

import requests

from .budget import NO_BUDGET, TimeBudget
from .etiquette import build_user_agent, resolve_contact_email


class NLMCatalogClient:
    def __init__(self, pause_sec: float = 0.2, email: str | None = None, budget: TimeBudget | None = None):
        self.session = requests.Session()
        self.email = resolve_contact_email(email)
        self.session.headers.update({"User-Agent": build_user_agent(self.email)})
        self.pause_sec = pause_sec
        self.budget = budget or NO_BUDGET
        self._alias_cache: dict[tuple[tuple[str, ...], str | None], list[str]] = {}

    def _get_json(self, url: str, params: dict) -> dict | None:
        if self.budget.expired:
            return None
        params = {**params, "tool": "ref-audit", "email": self.email}
        try:
            response = self.session.get(url, params=params, timeout=self.budget.http_timeout(10.0))
            response.raise_for_status()
            time.sleep(self.pause_sec)
            return response.json()
        except requests.RequestException:
            return None

    def _get_text(self, url: str, params: dict) -> str | None:
        if self.budget.expired:
            return None
        params = {**params, "tool": "ref-audit", "email": self.email}
        try:
            response = self.session.get(url, params=params, timeout=self.budget.http_timeout(10.0))
            response.raise_for_status()
            time.sleep(self.pause_sec)
            return response.text
        except requests.RequestException:
            return None

    def journal_aliases(self, title: str | None = None, issns: list[str] | None = None) -> list[str]:
        normalized_issns = tuple(sorted({(issn or "").strip() for issn in (issns or []) if (issn or "").strip()}))
        cache_key = (normalized_issns, (title or "").strip().lower() or None)
        if cache_key in self._alias_cache:
            return self._alias_cache[cache_key]

        terms = [f"{issn}[issn]" for issn in normalized_issns]
        if not terms and title:
            stripped = title.strip().rstrip(".")
            if stripped:
                terms.extend([f"\"{stripped}\"[Title]", f"\"{stripped}\"[Title Abbreviation]"])

        aliases: list[str] = []
        seen: set[str] = set()
        for term in terms[:2]:
            ids = self._search(term)
            if not ids:
                continue
            aliases = self._fetch_aliases(ids[0])
            if aliases:
                break
        for alias in aliases:
            cleaned = alias.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
        result = list(seen)
        self._alias_cache[cache_key] = result
        return result

    def _search(self, term: str) -> list[str]:
        payload = self._get_json(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            {"db": "nlmcatalog", "retmode": "json", "retmax": "1", "term": term},
        )
        if not payload:
            return []
        return (payload.get("esearchresult") or {}).get("idlist", [])

    def _fetch_aliases(self, nlm_id: str) -> list[str]:
        xml = self._get_text(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            {"db": "nlmcatalog", "retmode": "xml", "id": nlm_id},
        )
        if not xml:
            return []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return []

        aliases: list[str] = []
        paths = (
            ".//TitleMain/Title",
            ".//MedlineTA",
            ".//TitleAlternate/Title",
        )
        for path in paths:
            for elem in root.findall(path):
                value = (elem.text or "").strip().rstrip(".")
                if value:
                    aliases.append(value)
        return aliases
