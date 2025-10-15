from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

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

        esum = self._get_json(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            {"db": "pubmed", "retmode": "json", "id": ",".join(ids)},
        )
        results: list[PubMedMatch] = []
        if esum and (res := esum.get("result")):
            for pmid in ids:
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
