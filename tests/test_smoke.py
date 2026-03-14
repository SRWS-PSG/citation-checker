from __future__ import annotations

from api.check import handle_check, validate_payload
from refaudit.crossref import MatchResult
from refaudit.etiquette import build_user_agent, resolve_contact_email
from refaudit.main import run
from refaudit.parser import split_references


def test_imports():
    import refaudit.crossref  # noqa: F401
    import refaudit.parser  # noqa: F401
    import refaudit.web  # noqa: F401


def test_contact_email_resolution(monkeypatch):
    monkeypatch.setenv("CONTACT_EMAIL", "env@example.com")
    assert resolve_contact_email(None) == "env@example.com"
    assert resolve_contact_email("direct@example.com") == "direct@example.com"
    assert "mailto:direct@example.com" in build_user_agent("direct@example.com")


def test_cli_run_uses_markdown_output(tmp_path, monkeypatch):
    result = MatchResult(
        input_text="Missing reference",
        doi=None,
        title=None,
        found=False,
        retracted=False,
        retraction_details=[],
        note="no_match",
    )

    class DummyClient:
        def __init__(self, debug=False, email=None, pause_sec=0.2, strict=True):
            self.debug = debug
            self.email = email

        def check_one(self, line):
            assert line == "Missing reference"
            return result

    monkeypatch.setenv("CONTACT_EMAIL", "cli@example.com")
    monkeypatch.setattr("refaudit.crossref.CrossrefClient", DummyClient)

    out_path = tmp_path / "report.md"
    assert run("Missing reference", out_path) == 0
    text = out_path.read_text(encoding="utf-8")
    assert "Reference Audit Report" in text
    assert "Missing reference" in text


def test_validate_payload_rejects_invalid_email():
    try:
        validate_payload({"ref": "abc", "email": "bad"})
    except ValueError as exc:
        assert "email format is invalid" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_handle_check_returns_payload(monkeypatch):
    monkeypatch.setattr(
        "api.check.check_reference_payload",
        lambda ref, email, pause_sec=0.05: {
            "input_text": ref,
            "doi": None,
            "title": None,
            "found": False,
            "retracted": False,
            "retraction_details": [],
            "method": "mock",
            "note": None,
            "candidates": None,
            "suggestions": None,
            "input_authors": None,
            "matched_authors": None,
            "arxiv_id": None,
            "arxiv_doi": None,
            "journal_ref": None,
            "is_website": False,
        },
    )
    status, payload = handle_check({"ref": "Ref", "email": "user@example.com"})
    assert status == 200
    assert payload["ok"] is True
    assert payload["result"]["input_text"] == "Ref"


def test_split_references_keeps_cli_behavior():
    refs = split_references("[1] First\nReferences\n2. Second\n")
    assert refs == ["First", "Second"]
