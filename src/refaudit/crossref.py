from __future__ import annotations

import os
import time
import urllib.parse
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

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


class CrossrefClient:
    def __init__(self, pause_sec: float = 0.2):
        self.session = requests.Session()
        self.session.headers.update(UA)
        self.pause_sec = pause_sec

    def _get(self, url: str, params: dict | None = None):
        r = self.session.get(url, params=params, timeout=30)
        r.raise_for_status()
        time.sleep(self.pause_sec)
        return r.json()

    def search_bibliographic(self, ref: str) -> dict | None:
        params = {
            "query.bibliographic": ref,
            "rows": 3,
            "select": "DOI,title,issued,type",
        }
        js = self._get(API, params)
        items = js.get("message", {}).get("items", [])
        return items[0] if items else None

    def get_work(self, doi: str) -> dict | None:
        url = f"{API}/{urllib.parse.quote(doi)}"
        js = self._get(url, params={"select": "DOI,title,issued,type,update-to,relation"})
        return js.get("message", None)

    def find_updates_for(self, doi: str) -> list[dict]:
        params = {
            "filter": f"updates:{doi},is-update:true",
            "rows": 1000,
        }
        js = self._get(API, params)
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
        work = self.get_work(doi) if doi else self.search_bibliographic(input_text)

        if not work:
            return MatchResult(
                input_text, None, None, found=False, retracted=False, retraction_details=[]
            )

        doi = work.get("DOI")
        title = (work.get("title") or [None])[0]
        retracted, details = self.is_retracted(doi)
        return MatchResult(
            input_text, doi, title, found=True, retracted=retracted, retraction_details=details
        )

