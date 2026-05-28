"""Tests for the /api/clean reconstruction endpoint (mirrors CLI split_references)."""

from __future__ import annotations

import pytest

from api.clean import MAX_TEXT_LENGTH, handle_clean, validate_payload
from refaudit.parser import split_references

# 行番号付きPDFからのコピペ相当（行番号が癒着・改行なし）。pdf_cleaner が
# 連番の行番号(2〜12)を除去し、文献番号(28〜31)で区切って再構成する。
SAMPLE_PDF_BLOB = (
    "for therapeutic relationships: a literature review of common themes. "
    "Eur J for Pers2 Cent Healthc. 2017;5(3):362-372.3 28. Picker Institute "
    "Europe. The Picker Principles of Person Centred Care (2026).4 Available "
    "from https://picker.org/who-we-are/the-picker-principles-of-person-5 "
    "centred-care/ [accessed 20 January 2026].6 29. University of Minnesota, "
    "College of Continuing and Professional Studies. 10 Must-7 have "
    "Characteristics for Health Care Professionals (September 20, 2023). "
    "Available8 from: https://ccaps.umn.edu/story/10-must-have-characteristics-"
    "health-care-9 professionals [accessed 20 January 2026].10 30. Evans I, "
    "Thornton H, Chalmers I, et al. Testing Treatments: Better research for "
    "Better11 Healthcare, 2nd edition. London: Pinter & Martin; 2011.12 31. "
    "Mandell BF. Medical Treatment Decisions. Merck Manual; 2024."
)

PLAIN_NUMBERED_LIST = (
    "1. Smith J, Doe A. A great study. J Med. 2019;1(1):1-10.\n"
    "2. Jones B. Another study. J Med. 2020;2(2):11-20."
)

BIBTEX = (
    "@article{key1,\n"
    "  author = {Smith, John},\n"
    "  title = {A great study},\n"
    "  journal = {J Med},\n"
    "  year = {2019}\n"
    "}"
)


def test_handle_clean_returns_ok_and_refs():
    status, payload = handle_clean({"text": PLAIN_NUMBERED_LIST})
    assert status == 200
    assert payload["ok"] is True
    assert payload["refs"] == split_references(PLAIN_NUMBERED_LIST)


def test_handle_clean_strips_numbering():
    _, payload = handle_clean({"text": PLAIN_NUMBERED_LIST})
    refs = payload["refs"]
    assert len(refs) == 2
    assert refs[0].startswith("Smith J")
    assert not refs[0].startswith("1.")


def test_handle_clean_reconstructs_line_numbered_pdf():
    _, payload = handle_clean({"text": SAMPLE_PDF_BLOB})
    refs = payload["refs"]
    # 文献番号 28〜31 の4件に区切られ、行番号(2〜12)は紛れ込まない。
    assert len(refs) >= 4
    joined = " ".join(refs)
    assert "Pers2 Cent" not in joined  # 癒着行番号が除去されている
    assert "Picker" in joined
    assert "Merck Manual" in joined


def test_handle_clean_detects_bibtex():
    _, payload = handle_clean({"text": BIBTEX})
    refs = payload["refs"]
    assert len(refs) == 1
    assert "great study" in refs[0].lower()


@pytest.mark.parametrize("payload", [{}, {"text": ""}, {"text": "   "}, {"text": 123}])
def test_validate_payload_rejects_empty(payload):
    with pytest.raises(ValueError, match="text is required"):
        validate_payload(payload)


def test_validate_payload_rejects_oversized():
    with pytest.raises(ValueError, match="50000"):
        validate_payload({"text": "x" * (MAX_TEXT_LENGTH + 1)})
