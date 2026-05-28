"""Tests for line-numbered PDF cleaning (pdf_cleaner)."""

from __future__ import annotations

from refaudit import main as main_module
from refaudit.parser import split_references
from refaudit.pdf_cleaner import (
    clean_pdf_text,
    detect_line_numbered_pdf,
    split_pdf_references,
)

# 査読原稿PDFからのコピペ相当（行番号が単語に癒着・改行なしのブロブ）。
# 参考文献 27(続き)〜31。行番号 2〜12 が紛れ込み、URL がハイフンで分割されている。
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

# フッター付きの断片（"Page N of M" + 連結した印刷ページ番号・行番号）。
SAMPLE_WITH_FOOTER = (
    "Alcohol36 Use Disorder in COMBINE. J Subst Abuse Treat. 2016;67:38-43."
    "Page 18 of 44161 41. Husserl E. Cartesianische Meditationen. Hamburg: "
    "Felix Meiner; 1977."
)

# 通常の番号付き文献リスト（フッターはあるが行番号の癒着は無い）。
PLAIN_LIST_WITH_FOOTER = (
    "1. Smith J, Doe A. A great study. J Med. 2019;1(1):1-10.\n"
    "2. Jones B. Another study. J Med. 2020;2(2):11-20.\n"
    "Page 1 of 3\n"
    "3. Brown C. Third study. J Med. 2021;3(3):21-30.\n"
    "4. White D. Fourth study. J Med. 2022;4(4):31-40.\n"
)


# --- cleaning -----------------------------------------------------------------

def test_clean_removes_marginal_line_numbers():
    cleaned = clean_pdf_text(SAMPLE_PDF_BLOB)
    assert "Eur J for Pers Cent Healthc" in cleaned
    assert "Pers2" not in cleaned
    assert "Better11" not in cleaned
    assert "Available8" not in cleaned


def test_clean_rejoins_hyphenated_linebreak():
    cleaned = clean_pdf_text(SAMPLE_PDF_BLOB)
    # URL スラッグのハイフンは保持したまま行分割だけ解消される。
    assert "the-picker-principles-of-person-centred-care" in cleaned
    assert "person-5" not in cleaned


def test_clean_removes_footer():
    cleaned = clean_pdf_text(SAMPLE_WITH_FOOTER)
    # フッターと連結した印刷ページ番号・行番号1がまとめて消える。
    assert "Page 18 of 44" not in cleaned
    assert "44161" not in cleaned
    # フッターをまたいだ本文がつながる（"43.Page..." の連結が解消される）。
    assert "2016;67:38-43. 41. Husserl E" in cleaned


# --- splitting ----------------------------------------------------------------

def test_split_pdf_references_uses_reference_numbers():
    refs = split_pdf_references(SAMPLE_PDF_BLOB)
    joined = "\n".join(refs)
    assert any(r.startswith("Picker Institute Europe") for r in refs)
    assert any(r.startswith("University of Minnesota") for r in refs)
    assert any(r.startswith("Evans I, Thornton H") for r in refs)
    assert any(r.startswith("Mandell BF") for r in refs)
    # 行番号や文献番号マーカーが本文に残っていないこと。
    assert "28. Picker" not in joined


def test_split_pdf_references_keeps_leading_fragment():
    refs = split_pdf_references(SAMPLE_PDF_BLOB)
    # 先頭は参照27の続き（文献番号より前の断片）として保持される。
    assert refs[0].startswith("for therapeutic relationships")


def test_split_reference_boundary_is_loose_on_following_char():
    """連番チェックを根拠に、後続が大文字以外でも境界を取れる。"""
    blob = (
        "a14 b15 c16 d17 e18 f19 g20 lead fragment text here. "
        "21. van der Berg J. Lowercase surname study. J Test. 2019;1:1-5. "
        "22. Österreich Institut. Non-ASCII organisation report. 2020. "
        "23. World Health Organization. Patient Safety fact sheet. 2023."
    )
    refs = split_pdf_references(blob)
    assert any(r.startswith("van der Berg") for r in refs)
    assert any(r.startswith("Österreich Institut") for r in refs)
    assert any(r.startswith("World Health Organization") for r in refs)


# --- robustness: COVID-19 must survive ---------------------------------------

def test_covid19_not_stripped_when_value_matches_expected():
    """期待行番号と同じ値(19)の COVID-19 が行中にあっても壊れない。

    改行を保持したテキストでは行末/行頭の数値だけが候補になるため、
    行中の COVID-19 は行番号候補にならない。
    """
    text = (
        "Reference list reconstructed across lines 14\n"
        "spanning several wrapped lines here 15\n"
        "with study content continuing 16\n"
        "more discussion of methods 17\n"
        "Living with COVID-19 a phenomenological study 18\n"
        "of hospitalised patients in cluster transmission 19\n"
        "BMJ Open 2021 e046128 20\n"
    )
    cleaned = clean_pdf_text(text)
    assert "COVID-19" in cleaned
    # 行末の行番号は除去されている。
    assert "transmission 19" not in cleaned


# --- detection ----------------------------------------------------------------

def test_detect_positive_on_pdf_blob():
    assert detect_line_numbered_pdf(SAMPLE_PDF_BLOB) is True


def test_detect_negative_on_plain_list_even_with_footer():
    """フッターはあるが行番号の癒着が無い通常リストは PDF 扱いにしない。"""
    assert detect_line_numbered_pdf(PLAIN_LIST_WITH_FOOTER) is False


def test_detect_negative_on_simple_text():
    assert detect_line_numbered_pdf("Smith J. 2020. Title. Journal.") is False
    assert detect_line_numbered_pdf("") is False


# --- split_references integration & force flags -------------------------------

def test_split_references_auto_detects_pdf():
    refs = split_references(SAMPLE_PDF_BLOB)
    assert any(r.startswith("Picker Institute Europe") for r in refs)


def test_no_pdf_disables_detection():
    auto = split_references(SAMPLE_PDF_BLOB)
    disabled = split_references(SAMPLE_PDF_BLOB, force_pdf=False)
    assert auto != disabled
    # 無効化時は改行ベース処理に落ちるので、行番号が残った1ブロックになる。
    assert any("Pers2" in r for r in disabled)


def test_pdf_forces_cleaning_on_undetected_blob():
    """検出 False の入力にも --pdf 相当で強制適用できる。"""
    blob = "1. Alpha study. 2019. 2. Beta study. 2020. 3. Gamma study. 2021."
    assert detect_line_numbered_pdf(blob) is False
    refs = split_references(blob, force_pdf=True)
    assert any(r.startswith("Alpha study") for r in refs)
    assert any(r.startswith("Gamma study") for r in refs)


def test_split_references_plain_text_still_unchanged():
    """既存の plain-text 動作（自動検出が誤発火しない）を維持する。"""
    refs = split_references("[1] First ref\n2. Second ref\n")
    assert refs == ["First ref", "Second ref"]


# --- CLI: --show-clean fixes output to stdout and skips API -------------------

class _ExplodingClient:
    def __init__(self, *args, **kwargs):  # pragma: no cover - must not run
        raise AssertionError("CrossrefClient must not be constructed for --show-clean")


def test_show_clean_writes_to_stdout_without_api(monkeypatch, capsys):
    # API クライアントが生成されたら即失敗するよう差し替える。
    monkeypatch.setattr("refaudit.crossref.CrossrefClient", _ExplodingClient)
    rc = main_module.run(SAMPLE_PDF_BLOB, None, show_clean=True)
    out = capsys.readouterr().out
    assert rc == 0
    assert "1. for therapeutic relationships" in out
    assert "Picker Institute Europe" in out
    # stdout に Markdown レポートは出ていない。
    assert "# Reference Audit Report" not in out
    assert "Reference Audit" not in out


def test_show_clean_emits_numbered_list(capsys):
    main_module.run("1. Alpha. 2. Beta. 3. Gamma.", None, force_pdf=True, show_clean=True)
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.strip()]
    assert all(line[0].isdigit() for line in lines)
