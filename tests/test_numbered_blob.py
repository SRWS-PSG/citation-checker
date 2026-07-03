"""改行が失われた番号付き文献ブロブ（split_numbered_blob）のテスト。

実際の投稿原稿からのコピペを模した合成データを使う:
- 区切りは全角「．」＋空白なし（"1．Aoki"）
- 番号の直前が DOI 末尾のピリオドに癒着（"…j0001-2.2．Suzuki"）
- ページ範囲 "1230-5." / 巻号 "23(1): 6." が次のマーカー値と一致するデコイ
- 末尾は全角「．」で終わる和文文献
"""

from __future__ import annotations

from refaudit.parser import split_references
from refaudit.pdf_cleaner import split_numbered_blob

ZEN_BLOB = (
    "1．Aoki T, Sato K, Tanaka H. Alpha reflective practice in test education: "
    "asystematic review. J Test Educ 2009; 14(4): 595-621. doi: 10.1000/j0001-2."
    "2．Suzuki M. Beta practitioner handbook. Osaka: Test Press; 1983."
    "3．Yamada R, Kimura S, et al. Gamma pedagogy of realistic testing. Kyoto: Mock House; 2001."
    "4．Watanabe K, Ito J, et al. Delta portfolios in test education. "
    "Test Educ 2005; 39(12): 1230-5. doi: 10.1000/j.0002.x."
    "5．Kobayashi Y, et al. Epsilon portfolios mixed success review. "
    "Test Educ 2007; 23(1): 6. doi: 10.1000/j.0003."
    "6．Kato D. Zeta ritual to meaningful development. Arch Test 2014; 99(3): 279-83. "
    "doi: 10.1000/at-0004."
    "7．試験太郎,検証花子,評価次郎．テスト評価という新たなパラダイム．試験教育 2023:54(4):389-399．"
)

ASCII_BLOB = (
    "1. Alpha study of first things. J Test A 2019."
    "2. Beta study of second things. J Test B 2020."
    "3. Gamma study of third things. J Test C 2021."
    "4. Delta study of fourth things. J Test D 2022."
)


# --- 全角「．」区切り ----------------------------------------------------------

def test_zen_blob_splits_all_refs():
    refs = split_numbered_blob(ZEN_BLOB)
    assert len(refs) == 7
    assert refs[0].startswith("Aoki T, Sato K")
    assert refs[1].startswith("Suzuki M")
    assert refs[6].startswith("試験太郎")


def test_zen_blob_ignores_page_and_issue_decoys():
    """"1230-5." や "23(1): 6." の半角数字を境界と誤認しない。"""
    refs = split_numbered_blob(ZEN_BLOB)
    assert refs[4].startswith("Kobayashi Y")
    assert "1230-5" in refs[3]
    assert refs[5].startswith("Kato D")
    assert "23(1): 6" in refs[4]


def test_zen_blob_marker_glued_to_doi():
    """DOI 末尾のピリオドに癒着した番号（"…j0001-2.2．"）でも境界を取れる。"""
    refs = split_numbered_blob(ZEN_BLOB)
    assert refs[0].endswith("doi: 10.1000/j0001-2")
    assert refs[1] == "Suzuki M. Beta practitioner handbook. Osaka: Test Press; 1983"


def test_zen_blob_trailing_fullwidth_period_stripped():
    refs = split_numbered_blob(ZEN_BLOB)
    assert refs[6].endswith("389-399")


# --- 半角フォールバック --------------------------------------------------------

def test_ascii_blob_fallback():
    refs = split_numbered_blob(ASCII_BLOB)
    assert len(refs) == 4
    assert refs[0].startswith("Alpha study")
    assert refs[3].startswith("Delta study")


# --- 誤発火の抑止 --------------------------------------------------------------

def test_single_reference_not_split():
    ref = "Smith J, Doe A. A study of 1. things and 2. stuff. J Med 2020; 1(1): 1-10."
    assert split_numbered_blob(ref) == []


def test_chain_must_start_at_one_or_two():
    text = "5. Fifth item here. 6. Sixth item here. 7. Seventh item here."
    assert split_numbered_blob(text) == []


def test_empty_input():
    assert split_numbered_blob("") == []
    assert split_numbered_blob("   ") == []


# --- split_references への統合 -------------------------------------------------

def test_split_references_falls_back_to_blob():
    refs = split_references(ZEN_BLOB)
    assert len(refs) == 7
    assert refs[0].startswith("Aoki T")


def test_split_references_plain_lines_unaffected():
    refs = split_references("[1] First ref\n2. Second ref\n")
    assert refs == ["First ref", "Second ref"]


def test_split_references_three_plain_lines_unaffected():
    """3行以上の通常リストはフォールバック対象外（行分割の結果を維持）。"""
    text = "1. First ref about 2. things\n2. Second ref\n3. Third ref\n"
    refs = split_references(text)
    assert len(refs) == 3
    assert refs[0] == "First ref about 2. things"


def test_force_pdf_handles_zen_blob():
    """--pdf 強制時も全角ブロブを分割できる。"""
    refs = split_references(ZEN_BLOB, force_pdf=True)
    assert len(refs) == 7
    assert refs[1].startswith("Suzuki M")
