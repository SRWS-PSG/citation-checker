from __future__ import annotations

from typing import Iterable

from .crossref import MatchResult


def make_markdown_bad_only(results: Iterable[MatchResult]) -> str:
    bad = [r for r in results if (not r.found) or r.retracted]
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
        if not r.found:
            lines += [
                "## ❌ 未発見",
                "",
                f"- 入力: `{r.input_text}`",
                "- 理由: Crossref REST `/works?query.bibliographic=` で候補なし",
                "",
            ]
            continue

        lines += [
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
    return "\n".join(lines)

