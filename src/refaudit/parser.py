import re

DOI_REGEX = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)


def split_references(pasted_text: str) -> list[str]:
    # シンプル：改行ごとに1書誌。空行と番号プレフィックス、明らかなラベル行を除去。
    refs: list[str] = []
    skip_labels = {
        "article",
        "pubmed",
        "pubmed central",
        "google scholar",
        "cas",
        "references",
    }
    for raw in (pasted_text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.lower() in skip_labels:
            continue
        # 例: [1] , 1) , 1. などを剥がす
        line = re.sub(r"^\s*(\[\d+\]|\d+[\.\)]\s*)", "", line)
        refs.append(line)
    return refs


def extract_doi(text: str) -> str | None:
    m = DOI_REGEX.search(text)
    if not m:
        return None
    doi = m.group(1).rstrip(").,;")
    return doi


def extract_title_candidate(ref_line: str) -> str | None:
    # Heuristic: title is often the segment after authors, before journal.
    # Split by period and pick the first sufficiently long segment.
    if not ref_line:
        return None
    parts = [p.strip() for p in ref_line.split(".")]
    parts = [p for p in parts if p]
    for seg in parts[:4]:
        if len(seg) >= 15:  # avoid author initials or very short tokens
            return seg
    return parts[1] if len(parts) > 1 else (parts[0] if parts else None)
