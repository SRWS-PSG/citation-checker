from __future__ import annotations

from typing import Iterable

from .crossref import MatchResult


def _section_bad(r: MatchResult) -> list[str]:
    # Handle year_warning case (found=True but year doesn't match)
    if r.note == "year_warning" and r.found:
        lines = [
            "## △ 出版年注意",
            "",
            f"- 入力: `{r.input_text}`",
        ]
        if r.title or r.doi:
            lines.append(f"- マッチ: **{r.title or '(no title)'}**")
            lines.append(f"- DOI: `{r.doi}`")
        lines.append("- 注: タイトル・著者は一致していますが、出版年が参照と異なる可能性があります。")
        lines.append("")
        return lines
    if not r.found:
        if r.note == "author_mismatch":
            lines = [
                "## ⚠️ 著者名不一致",
                "",
                f"- 入力: `{r.input_text}`",
                "- 理由: 著者名が一致しません",
                "",
            ]
            if r.input_authors:
                lines.append(f"- 入力著者: {', '.join(r.input_authors)}")
            if r.matched_authors:
                lines.append(f"- Crossref著者（先頭5名）: {', '.join(r.matched_authors)}")
            lines.append("")
            return lines
        
        reason = "候補なし"
        if r.method == "doi":
            reason = "DOI直参照 `/works/{doi}` 失敗"
        elif r.method == "doi->bibliographic":
            reason = "DOI直参照失敗→`query.bibliographic` でも候補なし"
        elif r.method == "bibliographic":
            reason = "`query.bibliographic` で候補なし"
        if r.note == "title_mismatch":
            reason += "（タイトル不一致）"
        if r.note == "year_mismatch":
            reason += "（年不一致）"
        lines = [
            "## ❌ 未発見",
            "",
            f"- 入力: `{r.input_text}`",
            f"- 理由: {reason}",
            "",
        ]
        if r.candidates:
            lines += [
                "### Crossref候補（上位3件）",
            ]
            for c in r.candidates:
                y = c.get("year")
                y = y if y is not None else "N/A"
                cont = c.get("container") or ""
                page = c.get("page") or ""
                lines += [
                    f"- {y} {cont} {page} — {c.get('title')}",
                    f"  DOI: `{c.get('DOI')}`",
                ]
            lines.append("")
        if r.suggestions:
            lines += [
                "### 次のチェック候補",
            ]
            for hint in r.suggestions:
                lines.append(f"- {hint}")
            lines.append("")
        return lines
    # retracted
    lines = [
        "## 🚩 撤回・撤回相当（Crossref 更新通知）",
        "",
        f"- 入力: `{r.input_text}`",
        f"- マッチ: **{r.title or '(no title)'}**",
        f"- DOI: `{r.doi}`",
        "",
        "### 参照された更新（通知）",
        "",
    ]
    for d in r.retraction_details:
        when = d.get("updated", {}).get("date-time") or "N/A"
        src = d.get("source") or "N/A"
        lines.append(
            f"- 種別: **{d.get('update_type')}**, 通知DOI: `{d.get('notice_doi')}`, "
            f"source: `{src}`, date: `{when}`"
        )
    lines.append("")
    return lines


def make_markdown_bad_only(results: Iterable[MatchResult]) -> str:
    bad = [r for r in results if (not r.found) or r.retracted or r.note == "year_warning"]
    lines = [
        "# Reference Audit Report",
        "",
        "対象：貼り付けテキストのうち **問題があった書誌**（未発見／撤回系）だけを列挙しています。",
        "",
    ]
    if not bad:
        lines.append("_問題のある書誌は見つかりませんでした。_")
        return "\n".join(lines)

    for r in bad:
        lines += _section_bad(r)
    return "\n".join(lines)


def make_markdown_full(results: Iterable[MatchResult]) -> str:
    # Materialize once to avoid consuming an iterator multiple times
    results = list(results)
    bad = [r for r in results if (not r.found) or r.retracted or r.note == "year_warning"]
    ok = [r for r in results if r.found and not r.retracted and r.note != "year_warning"]
    lines = [
        "# Reference Audit Report (Full)",
        "",
        f"合計: {len(results)}、正常: {len(ok)}、問題あり: {len(bad)}",
        "",
        "## 問題あり",
        "",
    ]
    if not bad:
        lines.append("_問題のある書誌は見つかりませんでした。_")
    else:
        for r in bad:
            lines += _section_bad(r)
    lines += [
        "## 正常",
        "",
    ]
    if not ok:
        lines.append("_正常な書誌はありませんでした。_")
    else:
        for r in ok:
            lines += [
                "### ✅ 正常",
                f"- 入力: `{r.input_text}`",
                f"- マッチ: **{r.title or '(no title)'}**",
                f"- DOI: `{r.doi}`",
                "",
            ]
    return "\n".join(lines)
