from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

load_dotenv()

EMAIL = os.getenv("CONTACT_EMAIL", "you@example.com")
UA = {"User-Agent": f"ref-audit/0.1 (mailto:{EMAIL})"}


def _norm(s: str) -> str:
    return " ".join((s or "").lower().split())


@dataclass
class PubMedMatch:
    pmid: str
    title: str
    doi: str | None


class PubMedClient:
    def __init__(self, pause_sec: float = 0.2):
        self.session = requests.Session()
        self.session.headers.update(UA)
        self.pause_sec = pause_sec

    def _get_json(self, url: str, params: dict) -> dict | None:
        # E-utilities etiquette
        params = {**params, "tool": "ref-audit", "email": EMAIL}
        try:
            r = self.session.get(url, params=params, timeout=30)
            r.raise_for_status()
            time.sleep(self.pause_sec)
            return r.json()
        except requests.RequestException:
            return None

    def _get_text(self, url: str, params: dict) -> str | None:
        params = {**params, "tool": "ref-audit", "email": EMAIL}
        try:
            r = self.session.get(url, params=params, timeout=30)
            r.raise_for_status()
            time.sleep(self.pause_sec)
            return r.text
        except requests.RequestException:
            return None

    def search_full_citation(self, citation: str, retmax: int = 5) -> list[PubMedMatch]:
        """
        Search PubMed using the full citation text with multiple fallback strategies.
        This is more flexible than title-only search and can handle various citation formats.
        """
        import re
        
        results = self._try_search(citation, retmax)
        if results:
            return results
        
        cleaned = re.sub(r'[&;,\.\(\)\[\]]', ' ', citation)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        results = self._try_search(cleaned, retmax)
        if results:
            return results
        
        simplified = re.sub(r'\b10\.\d{4,9}/[^\s]+', '', citation)
        simplified = re.sub(r'\b\d+\(\d+\):\d+-\d+', '', simplified)
        simplified = re.sub(r'\b\d+:\d+', '', simplified)
        simplified = re.sub(r'[&;,\.\(\)\[\]]', ' ', simplified)
        simplified = re.sub(r'\s+', ' ', simplified).strip()
        results = self._try_search(simplified, retmax)
        if results:
            return results
        
        key_terms = self._extract_key_terms(citation)
        if key_terms:
            results = self._try_search(key_terms, retmax)
            if results:
                return results
        
        return []
    
    def _extract_key_terms(self, citation: str) -> str:
        """Extract key terms from citation: authors, year, journal, important title words."""
        import re
        
        parts = []
        
        year_match = re.search(r'\b(19|20)\d{2}\b', citation)
        if year_match:
            parts.append(year_match.group(0))
        
        author_part = citation.split('.')[0] if '.' in citation else citation[:50]
        author_words = re.findall(r'\b[A-Z][a-z]+\b', author_part)
        if author_words:
            parts.extend(author_words[:3])
        
        journal_patterns = [
            r'\b(BMC\s+\w+)',
            r'\b(J\s+Pediatr)',
            r'\b(JAMA)',
            r'\b(Lancet)',
            r'\b(N\s+Engl\s+J\s+Med)',
        ]
        for pattern in journal_patterns:
            match = re.search(pattern, citation, re.IGNORECASE)
            if match:
                parts.append(match.group(1))
                break
        
        title_section = citation
        if '.' in citation:
            citation_parts = citation.split('.')
            if len(citation_parts) > 1:
                title_section = '.'.join(citation_parts[1:])
        
        important_words = re.findall(
            r'\b(systematic|review|meta-analysis|randomized|controlled|trial|trials|'
            r'caffeine|therapy|treatment|outcomes|timing|initiation|early|late|'
            r'renal|replacement|kidney|injury|acute|'
            r'birth|weight|infants|infant|neonatal|pediatric|'
            r'association|trends|use|clinical|very|low)\b',
            title_section,
            re.IGNORECASE
        )
        if important_words:
            unique_words = []
            seen = set()
            for word in important_words:
                word_lower = word.lower()
                if word_lower not in seen:
                    unique_words.append(word)
                    seen.add(word_lower)
            parts.extend(unique_words[:8])
        
        return ' '.join(parts)
    
    def _try_search(self, query: str, retmax: int = 5) -> list[PubMedMatch]:
        """Helper method to try a single search query."""
        esearch = self._get_json(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            {"db": "pubmed", "retmode": "json", "retmax": str(retmax), "term": query},
        )
        if not esearch:
            return []
        ids = (esearch.get("esearchresult", {}) or {}).get("idlist", [])
        if not ids:
            return []

        return self._fetch_details(ids)

    def search_title_exact(self, title: str, retmax: int = 5) -> list[PubMedMatch]:
        # Use phrase search limited to Title field
        term = f'"{title}"[Title]'
        esearch = self._get_json(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            {"db": "pubmed", "retmode": "json", "retmax": str(retmax), "term": term},
        )
        if not esearch:
            return []
        ids = (esearch.get("esearchresult", {}) or {}).get("idlist", [])
        if not ids:
            return []

        return self._fetch_details(ids)

    def _fetch_details(self, pmids: list[str]) -> list[PubMedMatch]:
        """Fetch detailed information for a list of PMIDs."""
        esum = self._get_json(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            {"db": "pubmed", "retmode": "json", "id": ",".join(pmids)},
        )
        results: list[PubMedMatch] = []
        if esum and (res := esum.get("result")):
            for pmid in pmids:
                item = res.get(pmid, {})
                title = item.get("title") or ""
                doi = None
                # Try to locate DOI in esummary (not always present)
                for aid in item.get("articleids", []) or []:
                    if (aid.get("idtype") or "").lower() == "doi":
                        doi = aid.get("value")
                        break
                results.append(PubMedMatch(pmid=pmid, title=title, doi=doi))
        # If DOI missing, try efetch XML for the first few
        for i, pm in enumerate(results[:3]):
            if pm.doi:
                continue
            xml = self._get_text(
                "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
                {"db": "pubmed", "retmode": "xml", "id": pm.pmid},
            )
            if not xml:
                continue
            try:
                root = ET.fromstring(xml)
                for aid in root.iterfind(".//ArticleIdList/ArticleId"):
                    if aid.get("IdType", "").lower() == "doi":
                        results[i].doi = (aid.text or "").strip()
                        break
            except ET.ParseError:
                pass
        return results
