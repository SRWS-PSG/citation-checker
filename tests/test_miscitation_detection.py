from __future__ import annotations

from refaudit.crossref import CrossrefClient, MatchResult, _merge_records
from refaudit.main import run
from refaudit.parser import extract_authors, parse_reference_metadata
from refaudit.pubmed import PubMedMatch
from refaudit.report import make_markdown_bad_only
from refaudit.scoring import ReferenceRecord, score_candidate


def _work(
    doi: str,
    title: str,
    authors: list[str],
    year: int,
    container: str,
    volume: str | None,
    issue: str | None,
    page: str | None,
    work_type: str = "journal-article",
) -> dict:
    return {
        "DOI": doi,
        "title": [title],
        "author": [{"family": author} for author in authors],
        "issued": {"date-parts": [[year]]},
        "container-title": [container],
        "volume": volume,
        "issue": issue,
        "page": page,
        "type": work_type,
    }


def test_field_diffs_classify_venue_abbrev_year_near_and_missing_pages():
    reference = ReferenceRecord(
        title="Norepinephrine vs phenylephrine for spinal hypotension",
        authors=["imai", "kataoka"],
        year=2024,
        venue="J Anesth",
    )
    candidate = ReferenceRecord(
        title="Norepinephrine vs phenylephrine for spinal hypotension",
        authors=["imai", "kataoka"],
        year=2025,
        venue="Journal of Anesthesia",
        volume="39",
        page="100-110",
    )
    diffs = score_candidate(reference, candidate, mode="verification").field_diffs

    assert diffs["title"]["state"] == "ok"
    assert diffs["authors"]["state"] == "ok"
    assert diffs["year"]["state"] == "near"
    assert diffs["year"]["reason"] and "1年" in diffs["year"]["reason"]
    assert diffs["venue"]["state"] == "ok"
    assert "略誌名" in (diffs["venue"]["reason"] or "")
    assert diffs["pages"]["state"] == "missing_input"
    assert diffs["pages"]["reason"] == "入力に記載なし"


def test_field_diffs_accept_medium_suffix_as_same_venue():
    reference = ReferenceRecord(
        title="Imaging paper",
        authors=["smith"],
        year=2024,
        venue="Radiology [Internet]",
    )
    candidate = ReferenceRecord(
        title="Imaging paper",
        authors=["smith"],
        year=2024,
        venue="Radiology",
    )

    diffs = score_candidate(reference, candidate, mode="verification").field_diffs
    assert diffs["venue"]["state"] == "ok"


def test_field_diffs_accept_pubmed_journal_aliases():
    reference = ReferenceRecord(
        title="Digital therapeutics paper",
        authors=["smith"],
        year=2024,
        venue="Digit Health [Internet]",
    )
    candidate = ReferenceRecord(
        title="Digital therapeutics paper",
        authors=["smith"],
        year=2024,
        venue="DIGITAL HEALTH",
        venue_aliases=["Digit Health", "Digital health"],
    )

    diffs = score_candidate(reference, candidate, mode="verification").field_diffs
    assert diffs["venue"]["state"] == "ok"
    assert "許容" in (diffs["venue"]["reason"] or "") or diffs["venue"]["reason"] is None


def test_field_diffs_downgrade_venue_only_difference_when_identity_is_strong():
    reference = ReferenceRecord(
        title="Strongly matching paper",
        authors=["smith", "doe"],
        year=2024,
        venue="Obscure Imaging Reports [Internet]",
        volume="12",
        issue="3",
        page="101-110",
    )
    candidate = ReferenceRecord(
        title="Strongly matching paper",
        authors=["smith", "doe"],
        year=2024,
        venue="Journal of Diagnostic Imaging",
        volume="12",
        issue="3",
        page="101-110",
    )

    diffs = score_candidate(reference, candidate, mode="verification").field_diffs
    assert diffs["venue"]["state"] == "unverified"
    assert "別表記" in (diffs["venue"]["reason"] or "")


def test_merge_records_preserves_venue_aliases():
    primary = ReferenceRecord(venue="Nat Med", venue_aliases=["Nat Med", "Nature medicine"])
    secondary = ReferenceRecord(venue="Nature Medicine", venue_aliases=["Nature Medicine", "Nature medicine"])

    merged = _merge_records(primary, secondary)

    assert merged.venue == "Nat Med"
    assert merged.venue_aliases == ["Nat Med", "Nature medicine", "Nature Medicine"]


def test_extract_authors_handles_and_and_japanese_separator():
    assert extract_authors("Rudolph JW, Simon R, Raemer DB and Eppich WJ. Debriefing ...") == [
        "rudolph",
        "simon",
        "raemer",
        "eppich",
    ]
    assert extract_authors("松村千佳子・矢野義孝. 患者との医療コミュニケーションの重要性.") == ["松村", "矢野"]


def test_parse_reference_metadata_extracts_core_fields():
    record = parse_reference_metadata(
        "Barteit S, Kyaw BM, Muller A, et al. The Effectiveness of Digital Game-Based Learning in Health Professions Education: Systematic Review and Meta-Analysis. JMIR Serious Games 2021; 9(3): e29080."
    )
    assert record.year == 2021
    assert record.venue == "JMIR Serious Games"
    assert record.volume == "9"
    assert record.issue == "3"
    assert record.page == "e29080"
    assert record.article_number == "e29080"


def test_parse_reference_metadata_normalizes_japanese_spacing():
    record = parse_reference_metadata(
        "松村千佳子・矢野義孝．患者との医療コミュニ ケーションの重要性とその客観的評価研究．医 学教育 2020；51(3)：123-30．"
    )

    assert record.title == "患者との医療コミュニケーションの重要性とその客観的評価研究"
    assert record.venue == "医学教育"
    assert record.page == "123-30"


def test_scorer_accepts_exact_match_and_suggests_miscitation():
    good_input = ReferenceRecord(
        title="Virtual Reality for Medical Training: Systematic Review and Meta-Analysis",
        authors=["kyaw", "saxena", "posadzki"],
        year=2019,
        venue="J Med Internet Res",
        volume="21",
        issue="1",
        page="e12959",
        article_number="e12959",
    )
    exact = ReferenceRecord(
        title=good_input.title,
        authors=good_input.authors,
        year=2019,
        venue="J Med Internet Res",
        volume="21",
        issue="1",
        page="e12959",
        article_number="e12959",
        doi="10.2196/12959",
    )
    miscited = ReferenceRecord(
        title="Augmented, mixed, and virtual reality-based head-mounted devices for medical education: systematic review",
        authors=["barteit", "lanfermann", "barnighausen"],
        year=2021,
        venue="JMIR Serious Games",
        volume="9",
        issue="3",
        page="e29080",
        article_number="e29080",
        doi="10.2196/29080",
    )
    wrong_input = parse_reference_metadata(
        "Barteit S, Kyaw BM, Muller A, et al. The Effectiveness of Digital Game-Based Learning in Health Professions Education: Systematic Review and Meta-Analysis. JMIR Serious Games2021; 9(3): e29080."
    )

    assert score_candidate(good_input, exact, mode="verification").decision == "accept"
    assert score_candidate(wrong_input, miscited, mode="correction").decision == "suggest"


def test_crossref_client_flags_miscitations_with_suggestions(monkeypatch):
    references = {
        "1": "Barteit S, Kyaw BM, Muller A, et al. The Effectiveness of Digital Game-Based Learning in Health Professions Education: Systematic Review and Meta-Analysis. JMIR Serious Games2021; 9(3): e29080.",
        "2": "Kyaw BM, Saxena N, Posadzki P, et al. Virtual Reality for Medical Training: Systematic Review and Meta-Analysis by the Digital Health Education Collaboration. J Med Internet Res 2019; 21(1): e12959.",
        "3": "Motola I, Devine LA, Chung HS, et al. Simulation in Healthcare Education: A Best Evidence Practical Guide. Med Teach 2013; 35(10),e1511-e1530.",
        "4": "Cheng A, Morse K, Rudolph J, et al. Strategies to Enhance Engagement in Healthcare Simulation. Simul Healthc 2017; 12(5): 319-25.",
        "5": "Rudolph JW, Simon R, Raemer DB and Eppich WJ. Debriefing as Formative Assessment: Translating Medical Simulation into Effective Learning. Anesthesiol Clin 2007; 25(2): 361-76.",
        "6": "Gonzalez-Erena PV, Fernandez-Guinea S and Kourtesis P. Cognitive Assessment and Training in Extended Reality: Multimodal Systems, Clinical Utility, and Current Challenges, arXiv,2025, 2501(08237). Available from.",
        "7": "Pekrun R. The Impact of Academic Emotions on Learning and Achievement. Educ Psychol Rev 2006; 18: 315-41.",
        "8": "Nomura O, Fukui T, Shimizu K, et al. The Role of Emotional Intelligence in Medical Education: Insights from a Longitudinal Study. Adv Health Sci Educ 2021; 26: 1255-76.",
        "9": "松村千佳子・矢野義孝. 患者との医療コミュニケーションの重要性とその客観的評価研究. 医学教育 2020; 51(3): 123-30.",
    }

    candidate_map = {
        references["1"]: [
            _work(
                "10.2196/29080",
                "Augmented, mixed, and virtual reality-based head-mounted devices for medical education: systematic review",
                ["Barteit", "Lanfermann", "Barnighausen"],
                2021,
                "JMIR Serious Games",
                "9",
                "3",
                "e29080",
            )
        ],
        references["2"]: [
            _work(
                "10.2196/12959",
                "Virtual Reality for Medical Training: Systematic Review and Meta-Analysis by the Digital Health Education Collaboration",
                ["Kyaw", "Saxena", "Posadzki"],
                2019,
                "J Med Internet Res",
                "21",
                "1",
                "e12959",
            )
        ],
        references["3"]: [
            _work(
                "10.3109/0142159X.2013.818632",
                "Simulation in Healthcare Education: A Best Evidence Practical Guide",
                ["Motola", "Devine", "Chung"],
                2013,
                "Med Teach",
                "35",
                "10",
                "e1511-e1530",
            )
        ],
        references["4"]: [
            _work(
                "10.1111/medu.12432",
                "Clinical debriefing patterns for engaged simulation teams",
                ["Cheng", "Rudolph", "Morse"],
                2017,
                "Simul Healthc",
                "12",
                "5",
                "319-25",
            )
        ],
        references["5"]: [
            _work(
                "10.1016/j.anclin.2007.03.007",
                "Debriefing with good judgment: combining rigorous feedback with genuine inquiry",
                ["Rudolph", "Simon", "Rivard"],
                2007,
                "Anesthesiol Clin",
                "25",
                "2",
                "361-76",
            )
        ],
        references["6"]: [
            _work(
                "10.20944/preprints202411.0740.v1",
                "Cognitive assessment and training in extended reality: multimodal systems, clinical utility, and current challenges",
                ["Gonzalez-Erena", "Fernandez-Guinea", "Kourtesis"],
                2024,
                "Preprints.org",
                None,
                None,
                None,
                "posted-content",
            ),
            _work(
                "10.3390/encyclopedia5010008",
                "Cognitive assessment and training in extended reality: multimodal systems, clinical utility, and current challenges",
                ["Gonzalez-Erena", "Fernandez-Guinea", "Kourtesis"],
                2025,
                "Encyclopedia",
                "5",
                "1",
                "8",
            ),
        ],
        references["7"]: [
            _work(
                "10.1007/s10648-006-9029-9",
                "The control-value theory of achievement emotions: assumptions, corollaries, and implications for educational research and practice",
                ["Pekrun"],
                2006,
                "Educ Psychol Rev",
                "18",
                None,
                "315-41",
            )
        ],
        references["8"]: [
            _work(
                "10.1007/s10459-021-10049-3",
                "Japanese medical learners' achievement emotions: accounting for culture in translating western medical educational theories and instruments into an asian context",
                ["Nomura", "Wiseman", "Sunohara"],
                2021,
                "Adv Health Sci Educ Theory Pract",
                "26",
                "4",
                "1255-76",
            )
        ],
        references["9"]: [
            _work(
                "10.14988/0002000420",
                "患者との医療コミュニケーションの重要性とその客観的評価研究",
                ["松村", "矢野"],
                2020,
                "京都薬科大学紀要",
                "1",
                "2",
                "113-8",
            )
        ],
    }

    monkeypatch.setattr(
        CrossrefClient,
        "search_bibliographic_items",
        lambda self, ref, rows=5: candidate_map.get(ref, []),
    )
    monkeypatch.setattr(CrossrefClient, "is_retracted", lambda self, doi: (False, []))
    monkeypatch.setattr("refaudit.crossref.PubMedClient.search_full_citation", lambda self, citation, retmax=5: [])
    monkeypatch.setattr("refaudit.crossref.PubMedClient.search_title_exact", lambda self, title, retmax=5: [])
    monkeypatch.setattr("refaudit.crossref.ArxivClient.verify_reference", lambda self, **kwargs: (None, "arxiv-no-query"))

    client = CrossrefClient(pause_sec=0, debug=True)
    statuses = {key: client.check_one(ref).status for key, ref in references.items()}

    assert statuses["2"] == "found"
    assert statuses["3"] == "found"
    for key in ("1", "4", "5", "6", "7", "8", "9"):
        assert statuses[key] == "likely_wrong"

    result = client.check_one(references["1"])
    assert result.comparison_summary == "title ~ / authors ok / year ok / venue ok / pages ok"
    assert result.field_diffs is not None
    assert result.field_diffs["title"]["state"] in {"near", "mismatch", "abbrev"}
    assert result.field_diffs["authors"]["state"] == "ok"
    assert result.field_diffs["year"]["state"] == "ok"
    assert result.field_diffs["venue"]["state"] == "ok"
    assert result.field_diffs["pages"]["state"] == "ok"
    assert result.candidates
    assert result.candidates[0]["doi"] == "10.2196/29080"


def test_doi_input_can_be_flagged_as_likely_wrong(monkeypatch):
    input_ref = (
        "Wrong title example. J Med Internet Res 2019; 21(1): e12959. "
        "DOI: 10.2196/12959"
    )
    monkeypatch.setattr(
        CrossrefClient,
        "_resolve_doi_work",
        lambda self, doi: (
            _work(
                doi,
                "Virtual Reality for Medical Training: Systematic Review and Meta-Analysis by the Digital Health Education Collaboration",
                ["Kyaw", "Saxena", "Posadzki"],
                2019,
                "J Med Internet Res",
                "21",
                "1",
                "e12959",
            ),
            "doi-crossref",
        ),
    )
    monkeypatch.setattr(CrossrefClient, "is_retracted", lambda self, doi: (False, []))

    result = CrossrefClient(pause_sec=0).check_one(input_ref)
    assert result.status == "likely_wrong"
    assert result.found is False
    assert result.doi == "10.2196/12959"


def test_pubmed_candidates_do_not_resolve_every_doi(monkeypatch):
    input_ref = (
        "Kyaw BM, Saxena N, Posadzki P, et al. "
        "Virtual Reality for Medical Training: Systematic Review and Meta-Analysis by the Digital Health Education Collaboration. "
        "J Med Internet Res 2019; 21(1): e12959."
    )
    hits = [
        PubMedMatch(
            pmid="1",
            title="Virtual Reality for Medical Training: Systematic Review and Meta-Analysis by the Digital Health Education Collaboration",
            doi="10.2196/12959",
            authors=["Kyaw BM", "Saxena N", "Posadzki P"],
            year=2019,
            journal="J Med Internet Res",
            volume="21",
            issue="1",
            pages="e12959",
        ),
        PubMedMatch(
            pmid="2",
            title="Unrelated title",
            doi="10.0000/unrelated",
            authors=["Other A"],
            year=2019,
            journal="Other Journal",
            volume="1",
            issue="1",
            pages="1-2",
        ),
    ]
    calls: list[str] = []

    monkeypatch.setattr(CrossrefClient, "search_bibliographic_items", lambda self, ref, rows=5: [])
    monkeypatch.setattr("refaudit.crossref.PubMedClient.search_full_citation", lambda self, citation, retmax=5: hits)
    monkeypatch.setattr("refaudit.crossref.PubMedClient.search_title_exact", lambda self, title, retmax=5: [])
    monkeypatch.setattr("refaudit.crossref.ArxivClient.verify_reference", lambda self, **kwargs: (None, "arxiv-no-query"))
    monkeypatch.setattr(CrossrefClient, "is_retracted", lambda self, doi: (False, []))

    def fake_resolve(self, doi):
        calls.append(doi)
        return (
            _work(
                doi,
                "Virtual Reality for Medical Training: Systematic Review and Meta-Analysis by the Digital Health Education Collaboration",
                ["Kyaw", "Saxena", "Posadzki"],
                2019,
                "J Med Internet Res",
                "21",
                "1",
                "e12959",
            ),
            "doi-crossref",
        )

    monkeypatch.setattr(CrossrefClient, "_resolve_doi_work", fake_resolve)

    result = CrossrefClient(pause_sec=0).check_one(input_ref)
    assert result.status == "found"
    assert calls == ["10.2196/12959"]


def test_crossref_record_uses_nlm_title_fallback_without_issn(monkeypatch):
    aliases_called: list[tuple[str | None, list[str]]] = []

    monkeypatch.setattr(
        "refaudit.crossref.NLMCatalogClient.journal_aliases",
        lambda self, title=None, issns=None: aliases_called.append((title, issns or [])) or ["Nature medicine", "Nat Med"],
    )

    work = _work(
        "10.1000/test",
        "Example title",
        ["Smith"],
        2024,
        "Nature Medicine",
        "1",
        "1",
        "1-5",
    )

    client = CrossrefClient(pause_sec=0)
    record = client._work_to_record(work, source="crossref")

    assert aliases_called == [("Nature Medicine", [])]
    assert "Nat Med" in record.venue_aliases


def test_jalc_title_fallback_flags_japanese_miscitation(monkeypatch):
    input_ref = (
        "松村千佳子・矢野義孝．患者との医療コミュニ ケーションの重要性とその客観的評価研究．"
        "医 学教育 2020；51(3)：123-30．"
    )

    monkeypatch.setattr(CrossrefClient, "search_bibliographic_items", lambda self, ref, rows=5: [])
    monkeypatch.setattr("refaudit.crossref.PubMedClient.search_full_citation", lambda self, citation, retmax=5: [])
    monkeypatch.setattr("refaudit.crossref.PubMedClient.search_title_exact", lambda self, title, retmax=5: [])
    monkeypatch.setattr("refaudit.crossref.ArxivClient.verify_reference", lambda self, **kwargs: (None, "arxiv-no-query"))
    monkeypatch.setattr(
        "refaudit.crossref.JALCClient.search_title",
        lambda self, title, rows=5: [
            {
                "doi": "10.34445/00000224",
                "title": "患者との医療コミュニケーションの重要性とその客観的評価研究",
                "ra": "JaLC",
            }
        ],
    )
    monkeypatch.setattr(CrossrefClient, "is_retracted", lambda self, doi: (False, []))
    monkeypatch.setattr(
        CrossrefClient,
        "_resolve_doi_work",
        lambda self, doi: (
            _work(
                doi,
                "患者との医療コミュニケーションの重要性とその客観的評価研究",
                ["松村", "矢野"],
                2020,
                "京都薬科大学紀要",
                "1",
                "2",
                "113-118",
            ),
            "doi-jalc",
        ),
    )

    result = CrossrefClient(pause_sec=0).check_one(input_ref)

    assert result.status == "likely_wrong"
    assert result.method == "jalc-title+doi-jalc"
    assert result.doi == "10.34445/00000224"
    assert result.comparison_summary == "title ok / authors ok / year ok / venue x / pages x"
    assert result.candidates
    assert result.candidates[0]["doi"] == "10.34445/00000224"


def test_report_renders_likely_wrong_section():
    result = MatchResult(
        input_text="Wrong citation",
        doi="10.2196/29080",
        title="Augmented, mixed, and virtual reality-based head-mounted devices for medical education: systematic review",
        found=False,
        retracted=False,
        retraction_details=[],
        status="likely_wrong",
        note="candidate_mismatch",
        comparison_summary="title x / authors ~ / year ok / venue ok / pages ok",
        field_diffs={
            "title": {
                "state": "mismatch",
                "input_value": "Wrong title",
                "candidate_value": "Augmented, mixed, and virtual reality-based head-mounted devices",
                "reason": None,
                "score": 0.1,
            },
            "authors": {
                "state": "near",
                "input_value": "Barteit",
                "candidate_value": "Barteit, Lanfermann",
                "reason": None,
                "score": 0.5,
            },
            "year": {"state": "ok", "input_value": "2021", "candidate_value": "2021", "reason": None, "score": 1.0},
            "venue": {
                "state": "ok",
                "input_value": "JMIR Serious Games",
                "candidate_value": "JMIR Serious Games",
                "reason": None,
                "score": 1.0,
            },
            "pages": {"state": "ok", "input_value": "9(3): e29080", "candidate_value": "9(3): e29080", "reason": None, "score": 1.0},
        },
        candidates=[
            {
                "title": "Augmented, mixed, and virtual reality-based head-mounted devices for medical education: systematic review",
                "doi": "10.2196/29080",
                "field_summary": "title x / authors ~ / year ok / venue ok / pages ok",
                "container": "JMIR Serious Games",
                "year": 2021,
            }
        ],
    )

    markdown = make_markdown_bad_only([result])
    assert "Likely Wrong Citation" in markdown
    assert "⚠ 要確認" in markdown
    assert "📄 タイトル" in markdown
    assert "✓ 一致" in markdown
    assert "📚 掲載先" in markdown
    assert "10.2196/29080" in markdown


def test_cli_markdown_includes_likely_wrong_section(tmp_path, monkeypatch):
    result = MatchResult(
        input_text="Wrong citation",
        doi="10.2196/29080",
        title="Suggested title",
        found=False,
        retracted=False,
        retraction_details=[],
        status="likely_wrong",
        note="candidate_mismatch",
        comparison_summary="title x / authors ok / year ok / venue ok / pages ok",
        field_diffs={
            "title": {"state": "mismatch", "input_value": "Wrong", "candidate_value": "Suggested title", "reason": None, "score": 0.1},
            "authors": {"state": "ok", "input_value": "A", "candidate_value": "A", "reason": None, "score": 1.0},
            "year": {"state": "ok", "input_value": "2020", "candidate_value": "2020", "reason": None, "score": 1.0},
            "venue": {"state": "ok", "input_value": "X", "candidate_value": "X", "reason": None, "score": 1.0},
            "pages": {"state": "ok", "input_value": "1", "candidate_value": "1", "reason": None, "score": 1.0},
        },
        candidates=[{"title": "Suggested title", "doi": "10.2196/29080", "field_summary": "title x / authors ok / year ok / venue ok / pages ok"}],
    )

    class DummyClient:
        def __init__(self, debug=False, email=None, pause_sec=0.2, strict=True):
            self.debug = debug
            self.email = email

        def check_one(self, line):
            return result

    monkeypatch.setattr("refaudit.crossref.CrossrefClient", DummyClient)
    out_path = tmp_path / "report.md"
    run("Wrong citation", out_path)
    text = out_path.read_text(encoding="utf-8")
    assert "Likely Wrong Citation" in text
    assert "⚠ 要確認" in text
    assert "📄 タイトル" in text
