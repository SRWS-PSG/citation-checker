"""
arXiv API client for bibliographic verification.

Uses the arXiv ATOM API (export.arxiv.org/api/query) to:
1. Look up papers by arXiv ID (authoritative)
2. Search by title as fallback
3. Return structured metadata for comparison

Rate limit: arXiv recommends max 1 request per 3 seconds.
"""
from __future__ import annotations

import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests

ARXIV_API = "https://export.arxiv.org/api/query"
ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"


@dataclass
class ArxivMatch:
    """Metadata retrieved from arXiv API."""
    arxiv_id: str
    title: str | None
    authors: list[str]
    published: str | None
    updated: str | None
    doi: str | None
    journal_ref: str | None
    categories: list[str] = field(default_factory=list)
    abstract: str | None = None


def _strip_version(arxiv_id: str) -> str:
    """Remove version suffix (e.g., v1, v2) from arXiv ID."""
    return re.sub(r"v\d+$", "", arxiv_id)


def _normalize_arxiv_text(s: str) -> str:
    """Normalize text for comparison: lowercase, strip whitespace, remove TeX."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s).lower()
    # Remove common TeX patterns: $\alpha$, \textbf{...}, etc.
    s = re.sub(r"\$[^$]*\$", "", s)
    s = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+", "", s)
    # Remove punctuation, keep spaces and alnum
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


class ArxivClient:
    """Client for arXiv ATOM API."""

    def __init__(self, pause_sec: float = 3.0):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "ref-audit/0.1 (citation checker tool)"
        })
        self.pause_sec = pause_sec

    def _get_xml(self, params: dict) -> ET.Element | None:
        """Fetch arXiv API and parse XML response."""
        try:
            r = self.session.get(ARXIV_API, params=params, timeout=30)
            r.raise_for_status()
            time.sleep(self.pause_sec)
            return ET.fromstring(r.text)
        except (requests.RequestException, ET.ParseError):
            return None

    def _parse_entry(self, entry: ET.Element) -> ArxivMatch | None:
        """Parse a single ATOM entry into ArxivMatch."""
        # Extract arXiv ID from the <id> element (e.g., http://arxiv.org/abs/2307.06464v1)
        id_elem = entry.find(f"{{{ATOM_NS}}}id")
        if id_elem is None or id_elem.text is None:
            return None
        raw_id = id_elem.text.strip()
        # Extract just the ID part
        arxiv_id = re.sub(r"^https?://arxiv\.org/abs/", "", raw_id)

        title_elem = entry.find(f"{{{ATOM_NS}}}title")
        title = title_elem.text.strip() if title_elem is not None and title_elem.text else None
        # Normalize whitespace in title (arXiv API sometimes has newlines)
        if title:
            title = re.sub(r"\s+", " ", title).strip()

        authors = []
        for author_elem in entry.findall(f"{{{ATOM_NS}}}author"):
            name_elem = author_elem.find(f"{{{ATOM_NS}}}name")
            if name_elem is not None and name_elem.text:
                authors.append(name_elem.text.strip())

        published_elem = entry.find(f"{{{ATOM_NS}}}published")
        published = published_elem.text.strip() if published_elem is not None and published_elem.text else None

        updated_elem = entry.find(f"{{{ATOM_NS}}}updated")
        updated = updated_elem.text.strip() if updated_elem is not None and updated_elem.text else None

        # arXiv-specific fields
        doi_elem = entry.find(f"{{{ARXIV_NS}}}doi")
        doi = doi_elem.text.strip() if doi_elem is not None and doi_elem.text else None

        journal_ref_elem = entry.find(f"{{{ARXIV_NS}}}journal_ref")
        journal_ref = (
            journal_ref_elem.text.strip()
            if journal_ref_elem is not None and journal_ref_elem.text
            else None
        )

        categories = []
        for cat_elem in entry.findall(f"{{{ATOM_NS}}}category"):
            term = cat_elem.get("term")
            if term:
                categories.append(term)

        summary_elem = entry.find(f"{{{ATOM_NS}}}summary")
        abstract = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else None

        return ArxivMatch(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            published=published,
            updated=updated,
            doi=doi,
            journal_ref=journal_ref,
            categories=categories,
            abstract=abstract,
        )

    def lookup_by_id(self, arxiv_id: str) -> ArxivMatch | None:
        """Look up a paper by arXiv ID (most reliable method).

        Args:
            arxiv_id: arXiv identifier (e.g., "2307.06464" or "hep-th/9901001")

        Returns:
            ArxivMatch if found, None otherwise.
        """
        clean_id = _strip_version(arxiv_id)
        root = self._get_xml({"id_list": clean_id, "max_results": "1"})
        if root is None:
            return None

        # Check totalResults
        total_elem = root.find(".//{http://a9.com/-/spec/opensearch/1.1/}totalResults")
        if total_elem is not None and total_elem.text == "0":
            return None

        entry = root.find(f"{{{ATOM_NS}}}entry")
        if entry is None:
            return None

        # Check if arXiv returned an error entry (no title means not found)
        title_elem = entry.find(f"{{{ATOM_NS}}}title")
        if title_elem is None or not title_elem.text or title_elem.text.strip() == "Error":
            return None

        return self._parse_entry(entry)

    def search_by_title(self, title: str, max_results: int = 5) -> list[ArxivMatch]:
        """Search arXiv by title text.

        Args:
            title: Title text to search for.
            max_results: Maximum number of results.

        Returns:
            List of ArxivMatch results.
        """
        # Use ti: field for title search
        # URL-encode the title and use quotes for phrase matching
        query = f'ti:"{title}"'
        root = self._get_xml({
            "search_query": query,
            "max_results": str(max_results),
            "sortBy": "relevance",
            "sortOrder": "descending",
        })
        if root is None:
            return []

        results = []
        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            match = self._parse_entry(entry)
            if match:
                results.append(match)
        return results

    def search_by_title_and_author(
        self, title: str, first_author: str | None = None, max_results: int = 5
    ) -> list[ArxivMatch]:
        """Search arXiv by title and optionally first author.

        Args:
            title: Title text to search for.
            first_author: First author's family name (optional).
            max_results: Maximum number of results.

        Returns:
            List of ArxivMatch results.
        """
        query_parts = [f'ti:"{title}"']
        if first_author:
            query_parts.append(f'au:"{first_author}"')
        query = " AND ".join(query_parts)

        root = self._get_xml({
            "search_query": query,
            "max_results": str(max_results),
            "sortBy": "relevance",
            "sortOrder": "descending",
        })
        if root is None:
            return []

        results = []
        for entry in root.findall(f"{{{ATOM_NS}}}entry"):
            match = self._parse_entry(entry)
            if match:
                results.append(match)
        return results

    def verify_reference(
        self,
        arxiv_id: str | None = None,
        title: str | None = None,
        authors: list[str] | None = None,
    ) -> tuple[ArxivMatch | None, str]:
        """Verify a reference against arXiv.

        Strategy:
        1. If arXiv ID is provided, do ID lookup (most reliable)
        2. If no ID, search by title + first author
        3. Validate the result matches input

        Args:
            arxiv_id: arXiv ID if available.
            title: Title text for search.
            authors: List of author family names.

        Returns:
            Tuple of (ArxivMatch or None, method_string).
        """
        if arxiv_id:
            match = self.lookup_by_id(arxiv_id)
            if match:
                return match, "arxiv-id"
            return None, "arxiv-id-not-found"

        if title:
            first_author = authors[0] if authors else None
            results = self.search_by_title_and_author(title, first_author)
            if not results:
                # Try without author constraint
                results = self.search_by_title(title)

            # Score results by title similarity
            title_norm = _normalize_arxiv_text(title)
            for result in results:
                result_title_norm = _normalize_arxiv_text(result.title or "")
                if title_norm and result_title_norm:
                    # Check containment or high overlap
                    if title_norm in result_title_norm or result_title_norm in title_norm:
                        return result, "arxiv-title-search"
                    # Token-based comparison
                    title_tokens = set(title_norm.split())
                    result_tokens = set(result_title_norm.split())
                    if title_tokens and result_tokens:
                        overlap = len(title_tokens & result_tokens) / max(
                            len(title_tokens), len(result_tokens)
                        )
                        if overlap >= 0.8:
                            return result, "arxiv-title-search"

            return None, "arxiv-title-not-found"

        return None, "arxiv-no-query"
