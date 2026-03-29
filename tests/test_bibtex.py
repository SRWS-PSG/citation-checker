"""Tests for BibTeX parsing support."""

from __future__ import annotations

from refaudit.bibtex_parser import entry_to_citation_text, load_bibtex_references, parse_bibtex
from refaudit.parser import detect_bibtex, split_references

SAMPLE_BIB = """\
@article{imai2025,
  author = {Imai, E and Kataoka, Y and Watanabe, J},
  title = {Norepinephrine vs. phenylephrine for spinal hypotension},
  journal = {J Anesth},
  year = {2025},
  doi = {10.1007/s00540-025-03528-4}
}

@book{smith2020,
  author = {Smith, John},
  title = {A Great Book},
  publisher = {Publisher},
  year = {2020}
}

@inproceedings{doe2023,
  author = {Doe, Jane and Lee, Bob},
  title = {Deep Learning Approaches},
  booktitle = {NeurIPS 2023},
  year = {2023},
  eprint = {2307.06464},
  archivePrefix = {arXiv}
}
"""


def test_detect_bibtex_positive():
    assert detect_bibtex(SAMPLE_BIB) is True
    assert detect_bibtex("@article{key, title={T}}") is True
    assert detect_bibtex("@BOOK{key, title={T}}") is True


def test_detect_bibtex_negative():
    assert detect_bibtex("Smith J. 2020. Title. Journal.") is False
    assert detect_bibtex("") is False
    assert detect_bibtex(None) is False


def test_parse_bibtex_entries():
    entries = parse_bibtex(SAMPLE_BIB)
    assert len(entries) == 3
    assert entries[0]["title"] == "Norepinephrine vs. phenylephrine for spinal hypotension"
    assert entries[0]["doi"] == "10.1007/s00540-025-03528-4"
    assert entries[1]["ENTRYTYPE"] == "book"


def test_entry_to_citation_text_with_doi():
    entry = {
        "author": "Imai, E and Kataoka, Y",
        "title": "Some Title",
        "journal": "J Anesth",
        "year": "2025",
        "doi": "10.1007/s00540-025-03528-4",
    }
    text = entry_to_citation_text(entry)
    assert "Imai, Kataoka" in text
    assert "2025" in text
    assert "Some Title" in text
    assert "J Anesth" in text
    assert "DOI: 10.1007/s00540-025-03528-4" in text


def test_entry_to_citation_text_with_arxiv():
    entry = {
        "author": "Doe, Jane",
        "title": "ML Paper",
        "year": "2023",
        "eprint": "2307.06464",
        "archiveprefix": "arXiv",
    }
    text = entry_to_citation_text(entry)
    assert "arXiv:2307.06464" in text


def test_entry_to_citation_text_strips_braces():
    entry = {"title": "{A} {Great} Title", "year": "2020"}
    text = entry_to_citation_text(entry)
    assert "A Great Title" in text
    assert "{" not in text


def test_load_bibtex_references():
    refs = load_bibtex_references(SAMPLE_BIB)
    assert len(refs) == 3
    assert any("10.1007/s00540-025-03528-4" in r for r in refs)
    assert any("arXiv:2307.06464" in r for r in refs)


def test_split_references_auto_detects_bibtex():
    refs = split_references(SAMPLE_BIB)
    assert len(refs) == 3
    assert any("DOI:" in r for r in refs)


def test_split_references_plain_text_unchanged():
    """Ensure plain text references still work after BibTeX integration."""
    refs = split_references("[1] First ref\n2. Second ref\n")
    assert refs == ["First ref", "Second ref"]
