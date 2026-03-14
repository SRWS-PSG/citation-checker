"""
DOI Resolution module with multi-Registration Agency support.

This module provides DOI metadata resolution across different Registration Agencies (RAs):
- Crossref
- DataCite
- JaLC (Japan Link Center)
- And others via doi.org content negotiation

The fallback chain is:
1. Detect RA via doiRA service
2. Try RA-specific API (Crossref, DataCite, JaLC)
3. Fall back to doi.org content negotiation (works for all RAs)
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import requests
from .etiquette import build_user_agent

DOIRA_API = "https://doi.org/doiRA"
DATACITE_API = "https://api.datacite.org/dois"
JALC_API = "https://api.japanlinkcenter.org/dois"


@dataclass
class DOIMetadata:
    """Metadata retrieved from DOI resolution."""
    doi: str
    title: str | None
    authors: list[dict]
    year: int | None
    container_title: str | None
    volume: str | None
    issue: str | None
    page: str | None
    ra: str | None
    method: str


class DOIResolver:
    """
    Resolves DOI metadata across multiple Registration Agencies.
    
    The resolution strategy is:
    1. Detect which RA manages the DOI via doiRA service
    2. Try RA-specific API for best metadata quality
    3. Fall back to doi.org content negotiation (universal)
    """
    
    def __init__(self, pause_sec: float = 0.2, email: str | None = None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": build_user_agent(email)})
        self.pause_sec = pause_sec
    
    def _get_json(self, url: str, params: dict | None = None, headers: dict | None = None) -> dict | None:
        try:
            req_headers = {**self.session.headers}
            if headers:
                req_headers.update(headers)
            r = self.session.get(url, params=params, headers=req_headers, timeout=30)
            r.raise_for_status()
            time.sleep(self.pause_sec)
            return r.json()
        except requests.RequestException:
            return None
    
    def detect_ra(self, doi: str) -> str | None:
        """
        Detect the Registration Agency for a DOI using the doiRA service.
        
        Returns the RA name (e.g., 'Crossref', 'DataCite', 'JaLC') or None if detection fails.
        """
        url = f"{DOIRA_API}/{doi}"
        try:
            r = self.session.get(url, timeout=30)
            r.raise_for_status()
            time.sleep(self.pause_sec)
            data = r.json()
            if isinstance(data, list) and len(data) > 0:
                return data[0].get("RA")
            return None
        except requests.RequestException:
            return None
    
    def resolve_via_content_negotiation(self, doi: str) -> DOIMetadata | None:
        """
        Resolve DOI metadata via doi.org content negotiation.
        
        This works for ALL Registration Agencies and returns CSL-JSON format.
        """
        url = f"https://doi.org/{doi}"
        headers = {"Accept": "application/vnd.citationstyles.csl+json;q=1.0"}
        
        try:
            r = self.session.get(url, headers=headers, timeout=30, allow_redirects=True)
            r.raise_for_status()
            time.sleep(self.pause_sec)
            data = r.json()
            
            return self._parse_csl_json(data, doi, method="content-negotiation")
        except requests.RequestException:
            return None
    
    def resolve_via_crossref(self, doi: str) -> DOIMetadata | None:
        """Resolve DOI metadata via Crossref API."""
        import urllib.parse
        url = f"https://api.crossref.org/works/{urllib.parse.quote(doi)}"
        
        data = self._get_json(url)
        if not data:
            return None
        
        work = data.get("message")
        if not work:
            return None
        
        return self._parse_crossref_work(work, doi)
    
    def resolve_via_datacite(self, doi: str) -> DOIMetadata | None:
        """Resolve DOI metadata via DataCite API."""
        import urllib.parse
        url = f"{DATACITE_API}/{urllib.parse.quote(doi)}"
        
        data = self._get_json(url)
        if not data:
            return None
        
        attrs = data.get("data", {}).get("attributes", {})
        if not attrs:
            return None
        
        return self._parse_datacite_attrs(attrs, doi)
    
    def resolve(self, doi: str) -> DOIMetadata | None:
        """
        Resolve DOI metadata using the optimal strategy based on Registration Agency.
        
        The resolution chain is:
        1. Detect RA via doiRA
        2. Try RA-specific API (Crossref or DataCite)
        3. Fall back to doi.org content negotiation (universal)
        
        Returns DOIMetadata or None if resolution fails completely.
        """
        ra = self.detect_ra(doi)
        
        if ra == "Crossref":
            result = self.resolve_via_crossref(doi)
            if result:
                result.ra = ra
                return result
        elif ra == "DataCite":
            result = self.resolve_via_datacite(doi)
            if result:
                result.ra = ra
                return result
        
        result = self.resolve_via_content_negotiation(doi)
        if result:
            result.ra = ra
        return result
    
    def _parse_csl_json(self, data: dict, doi: str, method: str) -> DOIMetadata:
        """Parse CSL-JSON format (from content negotiation)."""
        title = data.get("title")
        
        authors = []
        for author in data.get("author", []):
            authors.append({
                "family": author.get("family", ""),
                "given": author.get("given", ""),
            })
        
        year = None
        issued = data.get("issued", {})
        if isinstance(issued, dict):
            date_parts = issued.get("date-parts", [])
            if date_parts and date_parts[0]:
                year = date_parts[0][0]
        
        return DOIMetadata(
            doi=doi,
            title=title,
            authors=authors,
            year=year,
            container_title=data.get("container-title"),
            volume=data.get("volume"),
            issue=data.get("issue") or data.get("number"),
            page=data.get("page"),
            ra=None,
            method=method,
        )
    
    def _parse_crossref_work(self, work: dict, doi: str) -> DOIMetadata:
        """Parse Crossref work format."""
        title = (work.get("title") or [None])[0]
        
        authors = []
        for author in work.get("author", []):
            authors.append({
                "family": author.get("family", ""),
                "given": author.get("given", ""),
            })
        
        year = None
        for field in ["published-print", "issued", "published-online"]:
            obj = work.get(field, {})
            if isinstance(obj, dict):
                parts = obj.get("date-parts") or []
                if parts and parts[0]:
                    year = parts[0][0]
                    break
        
        return DOIMetadata(
            doi=doi,
            title=title,
            authors=authors,
            year=year,
            container_title=(work.get("container-title") or [None])[0],
            volume=work.get("volume"),
            issue=work.get("issue"),
            page=work.get("page"),
            ra="Crossref",
            method="crossref-api",
        )
    
    def _parse_datacite_attrs(self, attrs: dict, doi: str) -> DOIMetadata:
        """Parse DataCite attributes format."""
        titles = attrs.get("titles", [])
        title = titles[0].get("title") if titles else None
        
        authors = []
        for creator in attrs.get("creators", []):
            name_parts = creator.get("name", "").split(", ", 1)
            if len(name_parts) == 2:
                authors.append({"family": name_parts[0], "given": name_parts[1]})
            else:
                authors.append({"family": creator.get("familyName", ""), "given": creator.get("givenName", "")})
        
        year = attrs.get("publicationYear")
        
        return DOIMetadata(
            doi=doi,
            title=title,
            authors=authors,
            year=year,
            container_title=attrs.get("publisher"),
            volume=None,
            issue=None,
            page=None,
            ra="DataCite",
            method="datacite-api",
        )
