from __future__ import annotations

import re
import time

import requests

from .budget import NO_BUDGET, TimeBudget
from .etiquette import build_user_agent
from .parser import contains_japanese_text

API = "https://api.japanlinkcenter.org/search"


def _normalize_title_query(title: str) -> str:
    text = re.sub(r"\s+", " ", (title or "").strip())
    return re.sub(r"(?<=[\u3040-\u30ff\u3400-\u9fff])\s+(?=[\u3040-\u30ff\u3400-\u9fff])", "", text)


class JALCClient:
    def __init__(self, pause_sec: float = 0.2, email: str | None = None, budget: TimeBudget | None = None):
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": build_user_agent(email)})
        self.pause_sec = pause_sec
        self.budget = budget or NO_BUDGET

    def _get(self, params: dict[str, str | int]) -> dict | None:
        if self.budget.expired:
            return None
        try:
            response = self.session.get(API, params=params, timeout=self.budget.http_timeout(10.0))
            response.raise_for_status()
            time.sleep(self.pause_sec)
            return response.json()
        except requests.RequestException:
            return None

    def search_title(self, title: str, rows: int = 5) -> list[dict]:
        if not title or not contains_japanese_text(title):
            return []

        queries = [_normalize_title_query(title), title.strip()]
        seen_queries: set[str] = set()
        hits: list[dict] = []
        seen_dois: set[str] = set()

        for query in queries:
            if not query or query in seen_queries:
                continue
            seen_queries.add(query)
            payload = self._get(
                {
                    "query.title": query,
                    "select": "doi,title,ra",
                    "page": 1,
                    "rows": rows,
                }
            )
            if not payload:
                continue
            for item in payload.get("data", []):
                doi = item.get("doi")
                if not doi or doi in seen_dois:
                    continue
                seen_dois.add(doi)
                title_list = item.get("title_list") or []
                best_title = None
                if title_list:
                    best_title = title_list[0].get("title")
                hits.append(
                    {
                        "doi": doi,
                        "title": best_title,
                        "ra": item.get("ra"),
                    }
                )
            if hits:
                break

        return hits
