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
