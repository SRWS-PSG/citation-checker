from __future__ import annotations

from typing import Iterable

from .crossref import MatchResult


def _section_arxiv(r: MatchResult) -> list[str]:
    """Generate report section for arXiv-verified references."""
    lines = [
        "### \U0001F4C4 arXiv\u78BA\u8A8D\u6E08\u307F",
        f"- \u5165\u529B: `{r.input_text}`",
        f"- \u30BF\u30A4\u30C8\u30EB: **{r.title or '(no title)'}**",
        f"- arXiv ID: `{r.arxiv_id}`",
    ]
    if r.arxiv_doi:
        lines.append(f"- \u51FA\u7248\u7248DOI: `{r.arxiv_doi}`")
    if r.journal_ref:
        lines.append(f"- Journal ref: {r.journal_ref}")
    if r.arxiv_doi:
        lines.append("- \U0001F4A1 \u51FA\u7248\u7248\u304C\u5B58\u5728\u3057\u307E\u3059\u3002\u51FA\u7248\u7248DOI\u3078\u306E\u66F4\u65B0\u3092\u691C\u8A0E\u3057\u3066\u304F\u3060\u3055\u3044\u3002")
    lines.append("")
    return lines


def _section_website(r: MatchResult) -> list[str]:
    """Generate report section for website/software references."""
    return [
        "### \U0001F310 \u30A6\u30A7\u30D6\u30B5\u30A4\u30C8\u53C2\u7167",
        f"- \u5165\u529B: `{r.input_text}`",
        "- \u8AAC\u660E: \u30BD\u30D5\u30C8\u30A6\u30A7\u30A2/\u30A6\u30A7\u30D6\u30B5\u30A4\u30C8\u53C2\u7167\u306E\u305F\u3081\u3001\u5B66\u8853DB\u691C\u8A3C\u306F\u30B9\u30AD\u30C3\u30D7\u3057\u307E\u3057\u305F\u3002",
        "",
    ]


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
        elif r.method and r.method.startswith("arxiv"):
            reason = f"arXiv API で候補なし (ID: {r.arxiv_id or 'N/A'})"
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
    bad = [
        r for r in results
        if (not r.found) or r.retracted or r.note == "year_warning"
    ]
    ok_standard = [
        r for r in results
        if r.found and not r.retracted and r.note != "year_warning"
        and not r.is_website and not r.arxiv_id
    ]
    ok_arxiv = [
        r for r in results
        if r.found and not r.retracted and r.note != "year_warning"
        and r.arxiv_id and not r.is_website
    ]
    websites = [r for r in results if r.is_website]
    total_ok = len(ok_standard) + len(ok_arxiv) + len(websites)
    lines = [
        "# Reference Audit Report (Full)",
        "",
        f"合計: {len(results)}、正常: {total_ok}、問題あり: {len(bad)}",
        "",
    ]
    # Problems section
    lines += ["## 問題あり", ""]
    if not bad:
        lines.append("_問題のある書誌は見つかりませんでした。_")
    else:
        for r in bad:
            lines += _section_bad(r)
    # Standard OK section
    lines += ["## 正常 (Crossref/PubMed)", ""]
    if not ok_standard:
        lines.append("_該当なし_")
    else:
        for r in ok_standard:
            lines += [
                "### \u2705 正常",
                f"- 入力: `{r.input_text}`",
                f"- マッチ: **{r.title or '(no title)'}**",
                f"- DOI: `{r.doi}`",
                "",
            ]
    # arXiv section
    if ok_arxiv:
        lines += ["## arXiv確認済み", ""]
        for r in ok_arxiv:
            lines += _section_arxiv(r)
    # Website section
    if websites:
        lines += ["## ウェブサイト/ソフトウェア参照（検証対象外）", ""]
        for r in websites:
            lines += _section_website(r)
    return "\n".join(lines)
