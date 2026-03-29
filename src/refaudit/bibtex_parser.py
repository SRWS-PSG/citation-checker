"""BibTeX file parser for citeguard.

Parses BibTeX entries and converts them into citation text lines
compatible with the existing check_one() pipeline.
"""

from __future__ import annotations

import re

import bibtexparser


def parse_bibtex(text: str) -> list[dict]:
    """Parse BibTeX text into a list of entry dicts."""
    db = bibtexparser.loads(text)
    return db.entries


def _format_authors(author_field: str) -> str:
    """Convert BibTeX author field ('Last, First and Last, First') to compact form."""
    authors = [a.strip() for a in author_field.split(" and ")]
    names = []
    for a in authors:
        if "," in a:
            # "Last, First" -> "Last"
            names.append(a.split(",")[0].strip())
        else:
            # "First Last" -> "Last"
            parts = a.split()
            names.append(parts[-1] if parts else a)
    return ", ".join(names)


def entry_to_citation_text(entry: dict) -> str:
    """Convert a single BibTeX entry dict to a citation text line.

    Produces a string like:
        Imai, Kataoka, Watanabe. 2025. Title here. J Anesth. DOI: 10.1007/xxx
    """
    parts: list[str] = []

    author = entry.get("author", "")
    if author:
        parts.append(_format_authors(author))

    year = entry.get("year", "")
    if year:
        parts.append(year)

    title = entry.get("title", "")
    if title:
        # Remove LaTeX braces
        title = re.sub(r"[{}]", "", title)
        parts.append(title)

    journal = entry.get("journal", "") or entry.get("booktitle", "")
    if journal:
        parts.append(journal)

    doi = entry.get("doi", "")
    if doi:
        parts.append(f"DOI: {doi}")

    arxiv = entry.get("eprint", "")
    if arxiv and "arxiv" in entry.get("archiveprefix", "").lower():
        parts.append(f"arXiv:{arxiv}")

    return ". ".join(parts)


def load_bibtex_references(text: str) -> list[str]:
    """Parse BibTeX text and return a list of citation text lines.

    Each line is formatted for the existing check_one() pipeline.
    """
    entries = parse_bibtex(text)
    refs: list[str] = []
    for entry in entries:
        line = entry_to_citation_text(entry)
        if line.strip():
            refs.append(line)
    return refs
