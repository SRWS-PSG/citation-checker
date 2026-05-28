"""行番号付きPDF（査読原稿など）からコピペしたテキストのクリーニング。

対象とするノイズ:
- 余白の行番号（ノンブル）が単語に癒着: ``Eur J for Pers2 Cent``,
  ``362-372.3``, ``person-5 centred``, ``References9 1.``
- ページフッター: ``Page 18 of 44``（印刷ページ番号・行番号と連結することがある）
- ハイフンで行分割された語: ``person-5 centred-care`` → ``person-centred-care``
- 1件の文献が改行・ページをまたいで連続し、文献番号(``28.`` ``29.``)だけが区切り

中心となる安全策は「単調増加列に乗った数値だけを削除する」こと。フラットな
正規表現単独では COVID-19・年・ページ範囲などを誤って消すため、候補を抽出した
うえで連番チェック（前回+1）に採用されたものだけを元位置で削除する。
"""

from __future__ import annotations

import re

# フッター "Page 18 of 44"。末尾の貪欲な \d+ が、連結した印刷ページ番号と
# その後の行番号1（例 "Page 18 of 44161"）もまとめて吸収する。
FOOTER_REGEX = re.compile(r"Page\s+\d+\s+of\s+\d+", re.IGNORECASE)

# 行番号候補。直前は非空白かつ非数字（長い数値の途中を拾わない）、1〜2桁。
# ブロブ用: トークンに癒着し直後が空白/終端（"Pers2 Cent", "372.3 28.",
# "person-5 centred", "References9 1."）。
_GLUED_NUM_REGEX = re.compile(r"(?<=\S)(?<!\d)(\d{1,2})(?=\s|$)")
# 物理行の末尾にある数値（行末＝直後が改行）。癒着・空白区切りどちらも可。
# 行中の COVID-19 等は行末ではないため対象外。
_LINE_END_NUM_REGEX = re.compile(r"(?<!\d)(\d{1,2})(?=[ \t]*\r?\n)")
# 物理行の先頭に置かれた数値（余白番号が行頭にコピーされた形）。
# 直後が空白のものに限定（"12." のような文献番号は直後が "." なので除外）。
_LEADING_NUM_REGEX = re.compile(r"(?:^|\n)[ \t]*(\d{1,2})(?=\s)")

# これ以上の改行があれば「物理行が保持されている」とみなす。
_MIN_NEWLINES_FOR_BOUNDARY_MODE = 3

# 文献番号マーカー "28. " 。直前は語・"."以外（"S75." や "2017." を除外）、
# 直後は空白でも数字でもない文字（小文字姓 van der・引用符・括弧・非ASCIIを許容）。
_REF_MARKER_REGEX = re.compile(r"(?<![\w.])(\d{1,3})\.[ \t]+(?=[^\s\d])")

MIN_LINENUM_RUN = 6  # この長さ以上の行番号列が無ければクリーニングしない
MIN_REF_BOUNDARIES = 3  # フッターが無い場合に必要な連番文献境界の数
_MAX_LINENUM_VALUE = 60  # 1ページあたりの行数の上限目安


def _longest_run(values: list[int], allow_reset: bool) -> list[int]:
    """各要素が直前の採用値+1（連番）になる最長部分列のインデックスを返す。

    ``allow_reset`` が True のときは、大きい値から小さい値への低下を
    ページ境界（行番号のリセット）として連結を許可する。O(n^2)。
    """
    n = len(values)
    if n == 0:
        return []
    best_len = [1] * n
    parent = [-1] * n
    for i in range(n):
        for j in range(i):
            step_ok = values[i] == values[j] + 1
            reset_ok = allow_reset and values[i] <= 2 and values[j] >= 5
            if (step_ok or reset_ok) and best_len[j] + 1 > best_len[i]:
                best_len[i] = best_len[j] + 1
                parent[i] = j
    end = max(range(n), key=lambda k: best_len[k])
    chain: list[int] = []
    while end != -1:
        chain.append(end)
        end = parent[end]
    chain.reverse()
    return chain


def _line_number_candidates(text: str) -> list[tuple[int, int, int]]:
    """行番号らしい数値の候補 (start, end, value) を集める。

    改行が保持されているテキストでは行境界（行末/行頭）の数値だけを候補にし、
    行中に埋もれた COVID-19・年・ページ範囲などを構造的に除外する。
    改行が無いブロブでは癒着した数値を候補にする（ベストエフォート）。
    """
    cands: set[tuple[int, int, int]] = set()
    regexes = (
        (_LINE_END_NUM_REGEX, _LEADING_NUM_REGEX)
        if text.count("\n") >= _MIN_NEWLINES_FOR_BOUNDARY_MODE
        else (_GLUED_NUM_REGEX,)
    )
    for regex in regexes:
        for m in regex.finditer(text):
            value = int(m.group(1))
            if value <= _MAX_LINENUM_VALUE:
                cands.add((m.start(1), m.end(1), value))
    return sorted(cands)


def _line_number_chain(text: str) -> list[tuple[int, int, int]]:
    """行番号と判定できる数値（単調増加列に乗ったもの）の列を返す。"""
    ordered = _line_number_candidates(text)
    chain_idx = _longest_run([c[2] for c in ordered], allow_reset=True)
    return [ordered[i] for i in chain_idx]


def clean_pdf_text(text: str) -> str:
    """フッター・行番号を除去し、折り返し行を結合した連続テキストを返す。"""
    text = FOOTER_REGEX.sub(" ", text or "")
    chain = _line_number_chain(text)
    if len(chain) >= MIN_LINENUM_RUN:
        for start, end, _ in sorted(chain, reverse=True):
            text = text[:start] + text[end:]
    # ハイフン行分割の結合: ハイフンは残し、後続の空白/改行だけ詰める
    # （URLスラッグや person-centred のような複合語を壊さないため）。
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "-", text)
    # 残った折り返し改行を空白へ。
    text = re.sub(r"\s*\n\s*", " ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _reference_marker_chain(cleaned: str) -> list[tuple[int, int]]:
    """連番に乗る文献番号マーカーの (digit_start, value) 列を返す。"""
    markers = [(m.start(1), int(m.group(1))) for m in _REF_MARKER_REGEX.finditer(cleaned)]
    chain_idx = _longest_run([v for _, v in markers], allow_reset=False)
    return [markers[i] for i in chain_idx]


def _strip_references_heading(text: str) -> str:
    return re.sub(r"^\s*references\s*", "", text, flags=re.IGNORECASE).strip(" .,:;")


def split_pdf_references(text: str) -> list[str]:
    """行番号付きPDFテキストを個々の文献文字列へ再構成する。"""
    cleaned = clean_pdf_text(text)
    boundaries = _reference_marker_chain(cleaned)

    if len(boundaries) < 2:
        # 連番の文献境界が確立できない場合は1ブロックとして返す。
        stripped = _strip_references_heading(cleaned)
        return [stripped] if stripped else []

    refs: list[str] = []
    first_start = boundaries[0][0]
    lead = _strip_references_heading(cleaned[:first_start])
    if lead:
        refs.append(lead)

    for k, (start, _value) in enumerate(boundaries):
        end = boundaries[k + 1][0] if k + 1 < len(boundaries) else len(cleaned)
        segment = cleaned[start:end]
        segment = re.sub(r"^\d{1,3}\.\s*", "", segment).strip(" .,:;")
        if segment:
            refs.append(segment)
    return refs


def detect_line_numbered_pdf(text: str) -> bool:
    """行番号付きPDFテキストらしさを保守的に判定する。

    True の条件: 行番号の単調列が存在し（必須）、かつ
    フッターが存在するか、クリーニング後に連番文献境界が複数成立すること。
    フッター単独や通常の番号付き文献リストでは True にならない。
    """
    if not text:
        return False
    footerless = FOOTER_REGEX.sub(" ", text)
    if len(_line_number_chain(footerless)) < MIN_LINENUM_RUN:
        return False
    if FOOTER_REGEX.search(text):
        return True
    return len(_reference_marker_chain(clean_pdf_text(text))) >= MIN_REF_BOUNDARIES
