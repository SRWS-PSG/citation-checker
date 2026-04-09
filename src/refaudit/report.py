from __future__ import annotations

from typing import Iterable

from .crossref import MatchResult


FIELD_LABEL = {
    "title": "📄 タイトル",
    "authors": "👤 著者",
    "year": "📅 出版年",
    "venue": "📚 掲載先",
    "pages": "📖 巻号・ページ",
}
FIELD_ORDER = ("title", "authors", "year", "venue", "pages")
ATTENTION_STATES = {"mismatch", "abbrev", "near", "missing_input", "missing_candidate"}


def _field_diffs(result: MatchResult) -> dict[str, dict] | None:
    if result.field_diffs:
        return result.field_diffs
    if result.best_candidate:
        return result.best_candidate.get("field_diffs")
    return None


def _render_field_diffs(diffs: dict[str, dict] | None) -> list[str]:
    if not diffs:
        return []
    needs: list[tuple[str, dict]] = []
    oks: list[str] = []
    for key in FIELD_ORDER:
        d = diffs.get(key)
        if not d:
            continue
        state = d.get("state")
        if state == "ok":
            oks.append(FIELD_LABEL[key])
        elif state in ATTENTION_STATES:
            needs.append((key, d))
    lines: list[str] = []
    if needs:
        lines.append(f"- ⚠ 要確認 ({len(needs)}件):")
        for key, d in needs:
            label = FIELD_LABEL[key]
            iv = d.get("input_value") or "(なし)"
            cv = d.get("candidate_value") or "(取得不可)"
            state = d.get("state")
            if state in {"missing_input", "missing_candidate"}:
                lines.append(f"  - {label}: 入力={iv} / Crossref={cv}")
            else:
                lines.append(f'  - {label}: "{iv}" → Crossref では "{cv}"')
            if d.get("reason"):
                lines.append(f"    （{d['reason']}）")
    if oks:
        lines.append(f"- ✓ 一致 ({len(oks)}件): {', '.join(oks)}")
    return lines


def _candidate_lines(result: MatchResult) -> list[str]:
    lines: list[str] = []
    for candidate in result.candidates or []:
        title = candidate.get("title") or "(no title)"
        lines.append(f"- **{title}**")
        if candidate.get("doi"):
            lines.append(f"- DOI: `{candidate['doi']}`")
        if candidate.get("field_summary"):
            lines.append(f"- 比較: {candidate['field_summary']}")
        if candidate.get("container") or candidate.get("year"):
            venue = candidate.get("container") or "N/A"
            year = candidate.get("year") or "N/A"
            lines.append(f"- 書誌: {venue} / {year}")
        lines.append("")
    return lines


def _section_year_warning(result: MatchResult) -> list[str]:
    lines = [
        "## △ 出版年注意",
        "",
        f"- 入力: `{result.input_text}`",
    ]
    if result.title:
        lines.append(f"- マッチ: **{result.title}**")
    if result.doi:
        lines.append(f"- DOI: `{result.doi}`")
    diff_lines = _render_field_diffs(_field_diffs(result))
    if diff_lines:
        lines.extend(diff_lines)
    else:
        lines.append("- 注: タイトル・著者は一致していますが、出版年が参照と異なる可能性があります。")
    lines.append("")
    return lines


def _section_not_found(result: MatchResult) -> list[str]:
    lines = [
        "## ❌ 未発見",
        "",
        f"- 入力: `{result.input_text}`",
        f"- 理由: {result.note or '候補なし'}",
        "",
    ]
    if result.candidates:
        lines += ["### 候補", ""]
        lines += _candidate_lines(result)
    if result.suggestions:
        lines += ["### 次のチェック候補", ""]
        lines.extend(f"- {item}" for item in result.suggestions)
        lines.append("")
    return lines


def _section_likely_wrong(result: MatchResult) -> list[str]:
    lines = [
        "## ⚠️ Likely Wrong Citation",
        "",
        f"- 入力: `{result.input_text}`",
    ]
    if result.title:
        lines.append(f"- 最有力候補: **{result.title}**")
    if result.doi:
        lines.append(f"- DOI: `{result.doi}`")
    lines.extend(_render_field_diffs(_field_diffs(result)))
    if result.note:
        lines.append(f"- 注記: {result.note}")
    lines.append("")
    if result.candidates:
        lines += ["### 修正候補", ""]
        lines += _candidate_lines(result)
    return lines


def _section_retracted(result: MatchResult) -> list[str]:
    lines = [
        "## 🚩 撤回・撤回相当（Crossref 更新通知）",
        "",
        f"- 入力: `{result.input_text}`",
        f"- マッチ: **{result.title or '(no title)'}**",
        f"- DOI: `{result.doi}`",
        "",
        "### 参照された更新（通知）",
        "",
    ]
    for detail in result.retraction_details:
        updated = detail.get("updated", {}).get("date-time") or "N/A"
        lines.append(
            f"- 種別: **{detail.get('update_type')}**, 通知DOI: `{detail.get('notice_doi')}`, "
            f"source: `{detail.get('source') or 'N/A'}`, date: `{updated}`"
        )
    lines.append("")
    return lines


def _section_website(result: MatchResult) -> list[str]:
    return [
        "### 🌐 ウェブサイト参照",
        f"- 入力: `{result.input_text}`",
        "- 説明: ソフトウェア/ウェブサイト参照のため学術DB検索はスキップしました。",
        "",
    ]


def make_markdown_bad_only(results: Iterable[MatchResult]) -> str:
    bad = [
        result
        for result in results
        if result.status in {"likely_wrong", "not_found"} or result.retracted or result.note == "year_warning"
    ]
    lines = [
        "# Reference Audit Report",
        "",
        "対象：貼り付けテキストのうち **問題があった書誌**（未発見／誤引用候補／撤回系）だけを列挙しています。",
        "",
    ]
    if not bad:
        lines.append("_問題のある書誌は見つかりませんでした。_")
        return "\n".join(lines)

    for result in bad:
        if result.retracted:
            lines += _section_retracted(result)
        elif result.note == "year_warning" and result.status == "found":
            lines += _section_year_warning(result)
        elif result.status == "likely_wrong":
            lines += _section_likely_wrong(result)
        else:
            lines += _section_not_found(result)
    return "\n".join(lines)


def make_markdown_full(results: Iterable[MatchResult]) -> str:
    results = list(results)
    bad = [
        result
        for result in results
        if result.status in {"likely_wrong", "not_found"} or result.retracted or result.note == "year_warning"
    ]
    ok = [
        result
        for result in results
        if result.status == "found" and not result.retracted and result.note != "year_warning"
    ]
    websites = [result for result in results if result.status == "website"]
    lines = [
        "# Reference Audit Report (Full)",
        "",
        f"合計: {len(results)}、正常: {len(ok)}、問題あり: {len(bad)}、ウェブサイト: {len(websites)}",
        "",
        "## 問題あり",
        "",
    ]
    if not bad:
        lines.append("_問題のある書誌は見つかりませんでした。_")
    else:
        for result in bad:
            if result.retracted:
                lines += _section_retracted(result)
            elif result.note == "year_warning" and result.status == "found":
                lines += _section_year_warning(result)
            elif result.status == "likely_wrong":
                lines += _section_likely_wrong(result)
            else:
                lines += _section_not_found(result)

    lines += ["## 正常", ""]
    if not ok:
        lines.append("_該当なし_")
    else:
        for result in ok:
            lines += [
                "### ✅ 正常",
                f"- 入力: `{result.input_text}`",
                f"- マッチ: **{result.title or '(no title)'}**",
            ]
            if result.doi:
                lines.append(f"- DOI: `{result.doi}`")
            if result.comparison_summary:
                lines.append(f"- 比較: {result.comparison_summary}")
            lines.append("")

    if websites:
        lines += ["## ウェブサイト/ソフトウェア参照（検証対象外）", ""]
        for result in websites:
            lines += _section_website(result)
    return "\n".join(lines)
