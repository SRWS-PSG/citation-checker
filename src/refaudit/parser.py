from __future__ import annotations

import re
import unicodedata

from .scoring import ReferenceRecord, normalize_author_name

DOI_REGEX = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)
JAPANESE_CHAR_REGEX = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")

# arXiv ID patterns:
# New format: 2307.06464, 2307.06464v1, 2307.06464v2
# Old format: hep-th/9901001, math.AG/0601001v1
ARXIV_ID_REGEX = re.compile(
    r"(?:arXiv:\s*|arxiv\.org/abs/)"
    r"((?:\d{4}\.\d{4,5}(?:v\d+)?)"
    r"|(?:[a-zA-Z][a-zA-Z\-\.]+/\d{7}(?:v\d+)?))",
    re.IGNORECASE,
)
# Bare arXiv ID (without arXiv: prefix) for fallback
ARXIV_ID_BARE_REGEX = re.compile(
    r"\b(\d{4}\.\d{4,5}(?:v\d+)?)\b"
)


BIBTEX_ENTRY_REGEX = re.compile(
    r"@\s*(?:article|book|inproceedings|incollection|conference|phdthesis|mastersthesis"
    r"|techreport|misc|unpublished|proceedings|inbook|manual|booklet)\s*\{",
    re.IGNORECASE,
)


def detect_bibtex(text: str) -> bool:
    """Return True if text appears to be BibTeX format."""
    return bool(BIBTEX_ENTRY_REGEX.search(text or ""))


def split_references(pasted_text: str) -> list[str]:
    # BibTeX形式を自動検出
    if detect_bibtex(pasted_text):
        from .bibtex_parser import load_bibtex_references
        return load_bibtex_references(pasted_text)

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
        line = re.sub(r"^\s*(\[\d+\]|\d+[\.\)]\s*)", "", line).strip()
        refs.append(line)
    return refs


def extract_doi(text: str) -> str | None:
    m = DOI_REGEX.search(text)
    if not m:
        return None
    doi = m.group(1).rstrip(").,;")
    return doi


def extract_arxiv_id(text: str) -> str | None:
    """Extract arXiv ID from text.

    Supports:
    - arXiv:2307.06464 / arXiv:2307.06464v1
    - arxiv.org/abs/2307.06464
    - arXiv:hep-th/9901001
    - Bare new-format IDs like 2307.06464 (only when 'arXiv' context is present)
    """
    # Try explicit arXiv: prefix or URL first
    m = ARXIV_ID_REGEX.search(text)
    if m:
        return m.group(1)
    # Fallback: bare new-format ID, but only if 'arxiv' appears somewhere in the text
    if re.search(r"arxiv", text, re.IGNORECASE):
        m = ARXIV_ID_BARE_REGEX.search(text)
        if m:
            return m.group(1)
    return None


def contains_japanese_text(text: str | None) -> bool:
    return bool(JAPANESE_CHAR_REGEX.search(text or ""))


def is_website_reference(text: str) -> bool:
    """Detect if a reference line is a website/software reference (not a journal article).

    These references should not be searched in academic databases as they will
    produce false positive matches.
    """
    lower = text.lower()
    # Check for URL-dominant references (short text with a URL)
    url_match = re.search(r"https?://[^\s]+", text)
    if url_match:
        # Remove the URL and see what remains
        remaining = text[:url_match.start()] + text[url_match.end():]
        remaining = re.sub(r"[\s.,;:]+", " ", remaining).strip()
        # If remaining text is very short (just a name/label), it's a website ref
        word_count = len([w for w in remaining.split() if len(w) > 1])
        if word_count <= 8:
            return True
    # Known software/website patterns
    website_indicators = [
        "systematic review software",
        "ai-powered tool",
        "ai research assistant",
        "evidence partners",
        "installation documentation",
    ]
    for indicator in website_indicators:
        if indicator in lower:
            return True
    return False


def extract_title_candidate(ref_line: str) -> str | None:
    if not ref_line:
        return None
    parts = [p.strip() for p in ref_line.split(".")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    
    def looks_like_authors(seg: str) -> bool:
        comma_count = seg.count(',')
        has_et_al = 'et al' in seg.lower()
        has_initials = bool(re.search(r'\b[A-Z]{1,3}\b', seg))
        return comma_count >= 2 or has_et_al or (comma_count >= 1 and has_initials)
    
    def score_as_title(seg: str) -> int:
        words = seg.split()
        word_count = len(words)
        digit_count = sum(1 for c in seg if c.isdigit())
        score = word_count * 10 - digit_count * 3
        if re.search(r"\b(?:19|20)\d{2}\b", seg):
            score -= 80
        if re.search(r"\d+\s*\(\d+\)", seg):
            score -= 60
        return score
    
    candidates = []
    for i, seg in enumerate(parts[:4]):
        if i == 0 and looks_like_authors(seg):
            continue
        if len(seg) >= 15:
            score = score_as_title(seg)
            candidates.append((score, seg))
    
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    
    return parts[1] if len(parts) > 1 else (parts[0] if parts else None)


def _normalize_reference_line(ref_line: str) -> str:
    text = unicodedata.normalize("NFKC", ref_line or "")
    text = text.replace("．", ".").replace("，", ",").replace("：", ":").replace("；", ";")
    text = text.replace("（", "(").replace("）", ")").replace("・", " ・ ")
    text = re.sub(r"(?<=[\u3040-\u30ff\u3400-\u9fff])\s+(?=[\u3040-\u30ff\u3400-\u9fff])", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _author_segment(ref_line: str) -> str:
    text = _normalize_reference_line(ref_line)
    if not text:
        return ""

    title = extract_title_candidate(text)
    if title and title in text:
        candidate = text.split(title, 1)[0]
    else:
        first_period = text.find(".")
        candidate = text[:first_period] if first_period > 0 else text

    year_match = re.search(r"\b(?:19|20)\d{2}\b", candidate)
    if year_match:
        candidate = candidate[:year_match.start()]
    doi_match = re.search(r"\bDOI:", candidate, re.IGNORECASE)
    if doi_match:
        candidate = candidate[:doi_match.start()]
    return candidate.strip(" .,:;")


def extract_authors(ref_line: str) -> list[str]:
    if not ref_line:
        return []

    author_segment = _author_segment(ref_line)
    if not author_segment:
        return []

    normalized = _normalize_reference_line(author_segment)
    normalized = re.sub(r"\bet\s+al\.?\b", "", normalized, flags=re.IGNORECASE)
    normalized = normalized.replace(" and ", ", ")
    normalized = normalized.replace(" & ", ", ")
    normalized = normalized.replace(" ・ ", ", ")
    normalized = normalized.replace("・", ", ")
    normalized = normalized.replace(";", ",")

    authors: list[str] = []
    seen: set[str] = set()
    for part in re.split(r",|\band\b", normalized, flags=re.IGNORECASE):
        chunk = part.strip()
        if not chunk:
            continue
        chunk = re.sub(r"\b[A-Z]{1,3}\b", "", chunk)
        chunk = chunk.replace(".", " ").strip()
        if not chunk:
            continue
        token = normalize_author_name(chunk)
        if token and token not in seen:
            seen.add(token)
            authors.append(token)

    return authors


def _extract_year(text: str) -> int | None:
    years = re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", _normalize_reference_line(text))
    return int(years[-1]) if years else None


def _extract_volume_issue_page(text: str) -> tuple[str | None, str | None, str | None]:
    normalized = _normalize_reference_line(text)
    patterns = [
        r"(?P<volume>\d+)\s*\((?P<issue>[^)]+)\)\s*[:,]\s*(?P<page>[A-Za-z]?\d[\w\-–]*)",
        r"(?P<volume>\d+)\s*[:,]\s*(?P<page>[A-Za-z]?\d[\w\-–]*)",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized)
        if match:
            return (
                (match.groupdict().get("volume") or "").strip() or None,
                (match.groupdict().get("issue") or "").strip() or None,
                (match.groupdict().get("page") or "").strip() or None,
            )
    return None, None, None


def _extract_article_number(page: str | None) -> str | None:
    if not page:
        return None
    stripped = page.strip()
    if re.fullmatch(r"[A-Za-z]?\d[\w-]*", stripped) and "-" not in stripped:
        return stripped
    return None


def _extract_venue(ref_line: str, title: str | None) -> str | None:
    normalized = _normalize_reference_line(ref_line)
    tail = normalized
    if title and title in normalized:
        tail = normalized.split(title, 1)[1]
    tail = re.sub(r"\bDOI:\s*10\.\S+", "", tail, flags=re.IGNORECASE)
    year_match = re.search(r"(?<!\d)(?:19|20)\d{2}(?!\d)", tail)
    if year_match:
        tail = tail[:year_match.start()]
    tail = tail.strip(" .,:;")
    return tail or None


def parse_reference_metadata(ref_line: str) -> ReferenceRecord:
    normalized = _normalize_reference_line(ref_line)
    title = extract_title_candidate(normalized)
    if title:
        title = re.sub(r",\s*arxiv.*$", "", title, flags=re.IGNORECASE).strip(" ,.;:")
    authors = extract_authors(normalized)
    year = _extract_year(normalized)
    volume, issue, page = _extract_volume_issue_page(normalized)
    venue = _extract_venue(normalized, title)
    if "arxiv" in normalized.lower() and venue == "Available from":
        venue = "arXiv"
    article_number = _extract_article_number(page)
    return ReferenceRecord(
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        volume=volume,
        issue=issue,
        page=page,
        article_number=article_number,
    )
