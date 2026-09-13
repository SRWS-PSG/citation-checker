"""Colon-author reference format (EndNote BMC/Vancouver output).

Covers ``parse_reference_metadata`` for references shaped like:

    Authors: Title. Journal Year, Vol(Issue):Pages.

The individual pattern tests below are picked from a real 48-reference batch of
EndNote BMC/Vancouver output where the parser previously failed on every single
line before this fix. The full batch (with a downstream-app-specific request
prefix already stripped from its first line) is checked separately as a
fixture in ``test_all_batch_references_parse_correctly`` below, with expected
titles and venues written out by hand rather than derived from the parser's
own regex.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from refaudit.parser import parse_reference_metadata

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "colon_author_refs.txt"


def test_et_al_before_colon_is_recognized_as_authors():
    record = parse_reference_metadata(
        "Treede RD, Rief W, Barke A, Aziz Q, Bennett MI, Benoliel R, Cohen M, Evers S, "
        "Finnerup NB, First MB et al: A classification of chronic pain for ICD-11. "
        "Pain 2015, 156(6):1003-1007."
    )
    assert record.title == "A classification of chronic pain for ICD-11"
    assert record.venue == "Pain"
    assert record.year == 2015
    assert record.volume == "156"
    assert record.issue == "6"
    assert record.page == "1003-1007"
    assert record.authors == [
        "treede", "rief", "barke", "aziz", "bennett", "benoliel",
        "cohen", "evers", "finnerup", "first",
    ]


def test_jr_suffix_is_dropped_from_authors_and_title_stays_clean():
    record = parse_reference_metadata(
        "McKenna RJ, Jr., Houck W, Fuller CB: Video-assisted thoracic surgery lobectomy: "
        "experience with 1,100 cases. Ann Thorac Surg 2006, 81(2):421-425; discussion 425-426."
    )
    assert record.title == "Video-assisted thoracic surgery lobectomy: experience with 1,100 cases"
    assert record.venue == "Ann Thorac Surg"
    # "Jr." must not leak in as a pseudo-author, and the "; discussion ..." suffix
    # must not leak into the page.
    assert record.authors == ["mckenna", "houck", "fuller"]
    assert record.page == "421-425"


def test_single_author_with_colon_inside_the_title():
    record = parse_reference_metadata(
        "Lee S: Dexmedetomidine: present and future directions. "
        "Korean journal of anesthesiology 2019, 72(4):323-330."
    )
    assert record.title == "Dexmedetomidine: present and future directions"
    assert record.authors == ["lee"]
    assert record.venue == "Korean journal of anesthesiology"
    assert record.year == 2019
    assert record.volume == "72"
    assert record.issue == "4"
    assert record.page == "323-330"


def test_single_author_without_colon_inside_the_title():
    record = parse_reference_metadata(
        "Batchelor TJP: Enhanced recovery after surgery and chest tube management. "
        "J Thorac Dis 2023, 15(2):901-908."
    )
    assert record.title == "Enhanced recovery after surgery and chest tube management"
    assert record.authors == ["batchelor"]
    assert record.venue == "J Thorac Dis"


def test_multi_word_surname_in_author_list_is_still_recognized():
    """A comma-separated author list may contain a tussenvoegsel-style surname
    ("Van de Velde M"); this must not make the whole author segment fail
    validation and fall back to the old (title-mangling) code path."""
    record = parse_reference_metadata(
        "Feray S, Lubach J, Joshi GP, Bonnet F, Van de Velde M: PROSPECT guidelines for "
        "video-assisted thoracoscopic surgery: a systematic review and procedure-specific "
        "postoperative pain management recommendations. Anaesthesia 2022, 77(3):311-325."
    )
    assert record.title == (
        "PROSPECT guidelines for video-assisted thoracoscopic surgery: a systematic "
        "review and procedure-specific postoperative pain management recommendations"
    )
    assert record.venue == "Anaesthesia"
    assert record.authors[-1] == "van"


def test_no_issue_with_article_number_after_colon():
    record = parse_reference_metadata(
        "Lin J, Liao Y, Gong C, Yu L, Gao F, Yu J, Chen J, Chen X, Zheng T, Zheng X: "
        "Regional Analgesia in Video-Assisted Thoracic Surgery: A Bayesian Network "
        "Meta-Analysis. Front Med (Lausanne) 2022, 9:842332."
    )
    assert record.venue == "Front Med (Lausanne)"
    assert record.year == 2022
    assert record.volume == "9"
    assert record.issue is None
    assert record.page == "842332"
    assert record.article_number == "842332"


def test_no_issue_with_page_range_does_not_swap_year_and_volume():
    """Regression guard: the old generic volume/issue/page extractor picked the
    LAST year-shaped number in the string as the year, so "2024, 18:2089-2101"
    produced year=2089 / volume=2024 instead of year=2024 / volume=18."""
    record = parse_reference_metadata(
        "Chen Z, Gao C, Zhang Y, Gao Y, Zhang L, Zhao S, Zhang H, Zhao X, Jin Y: Effects of "
        "Ultrasound-Guided Thoracic Paravertebral Nerve Block Combined with Perineural or IV "
        "Dexmedetomidine on Acute and Chronic Pain After Thoracoscopic Resection of Lung "
        "Lesions: A Double-Blind Randomized Trial. Drug Des Devel Ther 2024, 18:2089-2101."
    )
    assert record.year == 2024
    assert record.volume == "18"
    assert record.issue is None
    assert record.page == "2089-2101"


def test_issue_present_without_page():
    record = parse_reference_metadata(
        "Borys M, Hanych A, Czuczwar M: Paravertebral Block Versus Preemptive Ketamine "
        "Effect on Pain Intensity after Posterolateral Thoracotomies: A Randomized "
        "Controlled Trial. J Clin Med 2020, 9(3)."
    )
    assert record.venue == "J Clin Med"
    assert record.volume == "9"
    assert record.issue == "3"
    assert record.page is None
    assert record.article_number is None


def test_page_range_starting_with_uppercase_letter():
    record = parse_reference_metadata(
        "Zeng J, Tang ZH, Liang JQ, Wang F, Ma WH, Yu C, Xiong H, Chen Q: Comparison of "
        "Various Regional Analgesia Methods for Postoperative Analgesic Effects in "
        "Video-assisted Thoracoscopic Surgery: A Systematic Review and Network "
        "Meta-analysis. Pain physician 2022, 25(7):E917-e930."
    )
    assert record.page == "E917-e930"


def test_article_number_with_mixed_case_letter_prefix():
    record = parse_reference_metadata(
        "Pehora C, Pearson AM, Kaushal A, Crawford MW, Johnston B: Dexamethasone as an "
        "adjuvant to peripheral nerve block. Cochrane Database Syst Rev 2017, 11(11):Cd011770."
    )
    assert record.venue == "Cochrane Database Syst Rev"
    assert record.volume == "11"
    assert record.issue == "11"
    assert record.page == "Cd011770"


def test_decimal_points_in_title_do_not_split_the_sentence():
    """The Asik reference: decimals like "0.2%" must not be treated as sentence
    boundaries, in colon-author form."""
    record = parse_reference_metadata(
        "Asik I, Kocum AI, Goktug A, Turhan KS, Alkis N: Comparison of ropivacaine 0.2% "
        "and 0.25% with lidocaine 0.5% for intravenous regional anesthesia. "
        "Journal of clinical anesthesia 2009, 21(6):401-407."
    )
    assert record.title == (
        "Comparison of ropivacaine 0.2% and 0.25% with lidocaine 0.5% "
        "for intravenous regional anesthesia"
    )
    assert record.venue == "Journal of clinical anesthesia"


def test_decimal_points_in_title_do_not_split_the_sentence_vancouver_form():
    """Same Asik reference rewritten to plain Vancouver form (no colon after the
    author list) must also keep the decimal-bearing title intact -- this path
    goes through `_title_from_segments`, not the colon-author splitter."""
    record = parse_reference_metadata(
        "Asik I, Kocum AI, Goktug A, Turhan KS, Alkis N. Comparison of ropivacaine 0.2% "
        "and 0.25% with lidocaine 0.5% for intravenous regional anesthesia. "
        "Journal of clinical anesthesia. 2009;21(6):401-407."
    )
    assert record.title == (
        "Comparison of ropivacaine 0.2% and 0.25% with lidocaine 0.5% "
        "for intravenous regional anesthesia"
    )


def test_apa_style_reference_with_colon_in_title_is_not_misdetected():
    """A colon inside a title must not be mistaken for the colon-author format's
    author/title boundary when the text before it is not a plausible author list."""
    record = parse_reference_metadata("Smith J. COVID-19: a review. Lancet. 2020;1:1-2.")
    assert record.title == "COVID-19: a review"


def test_barteit_reference_with_mid_title_colon_is_unaffected():
    """Existing regression coverage (test_miscitation_detection.py) already pins this
    reference's title; this test only pins that it is NOT routed through the new
    colon-author path (there is no comma-separated author list before its first
    colon -- the colon sits inside the title after "et al.")."""
    record = parse_reference_metadata(
        "Barteit S, Kyaw BM, Muller A, et al. The Effectiveness of Digital Game-Based "
        "Learning in Health Professions Education: Systematic Review and Meta-Analysis. "
        "JMIR Serious Games 2021; 9(3): e29080."
    )
    assert record.venue == "JMIR Serious Games"
    assert record.volume == "9"
    assert record.issue == "3"
    assert record.page == "e29080"


# --- Full 48-reference batch -------------------------------------------------
# Titles and venues below are transcribed by hand from the source references
# (tests/fixtures/colon_author_refs.txt), not produced by the parser or by
# re-running the parser's own regex, so this is a genuine correctness check
# rather than a self-consistency check.

_EXPECTED_TITLES = [
    "Chronic post-surgical pain: 10 years on",
    "A classification of chronic pain for ICD-11",
    "Predicting chronic pain after major traumatic injury",
    "VATS versus open surgery for lung cancer resection: moving toward a minimally "
    "invasive approach",
    "Video-assisted thoracic surgery lobectomy: experience with 1,100 cases",
    "Incidence and risk factors for chronic postsurgical pain following "
    "video-assisted thoracoscopic surgery: a retrospective study",
    "Prevalence and Predictors of Chronic Postsurgical Pain After Video-Assisted "
    "Thoracoscopic Surgery: A Systematic Review and Meta-analysis",
    "PROSPECT guidelines for video-assisted thoracoscopic surgery: a systematic "
    "review and procedure-specific postoperative pain management recommendations",
    "Comparison of Various Regional Analgesia Methods for Postoperative Analgesic "
    "Effects in Video-assisted Thoracoscopic Surgery: A Systematic Review and "
    "Network Meta-analysis",
    "Regional Analgesia in Video-Assisted Thoracic Surgery: A Bayesian Network "
    "Meta-Analysis",
    "Regional analgesia techniques for video-assisted thoracic surgery: a "
    "frequentist network meta-analysis",
    "Effects of ultrasound-guided erector spinae plane block on postoperative "
    "acute pain and chronic post-surgical pain in patients underwent "
    "video-assisted thoracoscopic lobectomy: a prospective randomized, "
    "controlled trial",
    "Postoperative recovery with continuous erector spinae plane block or "
    "video-assisted paravertebral block after minimally invasive thoracic "
    "surgery: a prospective, randomised controlled trial",
    "Dexmedetomidine Added to Ropivacaine for Ultrasound-guided Erector Spinae "
    "Plane Block Prolongs Analgesia Duration and Reduces Perioperative Opioid "
    "Consumption After Thoracotomy: A Randomized, Controlled Clinical Study",
    "Efficacy of Bilateral Erector Spinae Plane Block in Management of Acute "
    "Postoperative Surgical Pain After Pediatric Cardiac Surgeries Through a "
    "Midline Sternotomy",
    "Safety of Continuous Erector Spinae Catheters in Chest Trauma: A "
    "Retrospective Cohort Study",
    "The analgetic effect of adjuvants in local infiltration analgesia - a "
    "systematic review with network meta-analysis of randomized trials",
    "The Facilitatory Effects of Adjuvant Pharmaceutics to Prolong the Duration "
    "of Local Anesthetic for Peripheral Nerve Block: A Systematic Review and "
    "Network Meta-analysis",
    "Dexamethasone as an adjuvant to peripheral nerve block",
    "Preventive analgesia by local anesthetics: the reduction of postoperative "
    "pain by peripheral nerve blocks and intravenous drugs",
    "Dexmedetomidine in Enhanced Recovery After Surgery (ERAS) Protocols for "
    "Postoperative Pain",
    "Transverse abdominis plane injection of bupivacaine with dexmedetomidine or "
    "a bupivacaine liposomal suspension yielded lower pain scores and "
    "requirement for rescue analgesia in a controlled, randomized trial in dogs "
    "undergoing elective ovariohysterectomy",
    "Paravertebral Dexmedetomidine in Video-Assisted Thoracic Surgeries for "
    "Acute and Chronic Pain Prevention",
    "Effects of Ultrasound-Guided Thoracic Paravertebral Nerve Block Combined "
    "with Perineural or IV Dexmedetomidine on Acute and Chronic Pain After "
    "Thoracoscopic Resection of Lung Lesions: A Double-Blind Randomized Trial",
    "Determination of moderate-to-severe postoperative pain on the numeric "
    "rating scale: a cut-off point analysis applying four different methods",
    "Efficacy of Single-shot Thoracic Paravertebral Block Combined with "
    "Intravenous Analgesia Versus Continuous Thoracic Epidural Analgesia for "
    "Chronic Pain After Thoracotomy",
    "Paravertebral Block Versus Preemptive Ketamine Effect on Pain Intensity "
    "after Posterolateral Thoracotomies: A Randomized Controlled Trial",
    "Risk stratification for the development of chronic postsurgical pain",
    "Psychosocial predictors and correlates for chronic post-surgical pain "
    "(CPSP) - a systematic review",
    "Dexmedetomidine as an Adjuvant in Peripheral Nerve Block",
    "Effects of dexmedetomidine as an adjuvant to ropivacaine or ropivacaine "
    "alone on duration of postoperative analgesia: A systematic review and "
    "meta-analysis of randomized controlled trials",
    "Facilitatory effects of perineural dexmedetomidine on neuraxial and "
    "peripheral nerve block: a systematic review and meta-analysis",
    "Repeated intrathecal administration of ropivacaine causes neurotoxicity "
    "in rats",
    "Ropivacaine mesylate exerts neurotoxicity via up-regulation of Fas/FasL "
    "expression in rat pheochromocytoma PC12 cells",
    "Comparison of ropivacaine 0.2% and 0.25% with lidocaine 0.5% for "
    "intravenous regional anesthesia",
    "A systematic review and meta-analysis of three risk factors for chronic "
    "postsurgical pain: age, sex and preoperative pain",
    "Dexmedetomidine: present and future directions",
    "Moderate-severe postoperative pain in patients undergoing video-assisted "
    "thoracoscopic surgery: A retrospective study",
    "Erector Spinae Plane Block Decreases Chronic Postoperative Pain Severity "
    "in Patients Undergoing Coronary Artery Bypass Grafting",
    "The Efficacy and Safety of Ultrasound-Guided, Bi-Level, Erector Spinae "
    "Plane Block With Different Doses of Dexmedetomidine for Patients "
    "Undergoing Video-Assisted Thoracic Surgery: A Randomized Controlled Trial",
    "Chronic postsurgical pain and transitional pain services: a narrative "
    "review highlighting European perspectives",
    "Identifying risk factors for chronic postsurgical pain and preventive "
    "measures: a comprehensive update",
    "Thoracic Paravertebral Block with Adjuvant Dexmedetomidine in "
    "Video-Assisted Thoracoscopic Surgery: A Randomized, Double-Blind Study",
    "Enhanced recovery after surgery and chest tube management",
    "The effect and safety of dexmedetomidine as an adjuvant to local "
    "anesthetics in erector spinae plane block: a systematic review and "
    "meta-analysis of randomized controlled trials",
    "Dexmedetomidine as an Adjuvant to Nerve Block for Cancer Surgery: A "
    "Systematic Review and Meta-Analysis",
    "Chronic postsurgical pain increases postoperative depression risk",
    "Preoperative psychological symptoms and chronic postsurgical pain: "
    "analysis of the prospective China Surgery and Anaesthesia Cohort study",
]

_EXPECTED_VENUES = [
    "British journal of anaesthesia",
    "Pain",
    "Scand J Pain",
    "J Natl Compr Canc Netw",
    "Ann Thorac Surg",
    "BMC surgery",
    "Pain Ther",
    "Anaesthesia",
    "Pain physician",
    "Front Med (Lausanne)",
    "Korean journal of anesthesiology",
    "BMC anesthesiology",
    "British journal of anaesthesia",
    "The Clinical journal of pain",
    "J Cardiothorac Vasc Anesth",
    "Anesthesia and analgesia",
    "Journal of clinical anesthesia",
    "Anesthesia and analgesia",
    "Cochrane Database Syst Rev",
    "Anesthesia and analgesia",
    "Curr Pain Headache Rep",
    "Am J Vet Res",
    "Pain physician",
    "Drug Des Devel Ther",
    "British journal of anaesthesia",
    "Pain physician",
    "J Clin Med",
    "Pain Rep",
    "Eur J Pain",
    "Drug Des Devel Ther",
    "PloS one",
    "British journal of anaesthesia",
    "Anaesth Intensive Care",
    "Am J Transl Res",
    "Journal of clinical anesthesia",
    "Minerva anestesiologica",
    "Korean journal of anesthesiology",
    "Scientific reports",
    "J Clin Med",
    "Front Med (Lausanne)",
    "Reg Anesth Pain Med",
    "Expert Rev Neurother",
    "J Clin Med",
    "J Thorac Dis",
    "BMC anesthesiology",
    "J Clin Med",
    "J Epidemiol Community Health",
    "British journal of anaesthesia",
]


def _load_fixture_lines() -> list[str]:
    lines = [
        line.strip()
        for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 48
    return lines


_FIXTURE_LINES = _load_fixture_lines()
assert len(_EXPECTED_TITLES) == 48
assert len(_EXPECTED_VENUES) == 48


@pytest.mark.parametrize(
    "ref_line,expected_title,expected_venue",
    list(zip(_FIXTURE_LINES, _EXPECTED_TITLES, _EXPECTED_VENUES)),
    ids=[str(i) for i in range(1, 49)],
)
def test_all_batch_references_parse_correctly(ref_line, expected_title, expected_venue):
    record = parse_reference_metadata(ref_line)
    assert record.title == expected_title
    assert record.venue == expected_venue
