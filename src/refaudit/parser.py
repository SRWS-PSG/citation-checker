import re

DOI_REGEX = re.compile(r"(10\.\d{4,9}/[^\s\"<>]+)", re.IGNORECASE)

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
        return word_count * 10 - digit_count
    
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


def extract_authors(ref_line: str) -> list[str]:
    """
    Extract author family names from a reference line.
    Returns a list of normalized family names.
    
    Heuristic: authors appear before the first period or year.
    Split by commas and extract family names (first token after removing initials).
    """
    import unicodedata
    
    if not ref_line:
        return []
    
    author_segment = ref_line
    
    first_period = ref_line.find('.')
    if first_period > 0:
        author_segment = ref_line[:first_period]
    
    year_match = re.search(r'\b(19|20)\d{2}\b', author_segment)
    if year_match:
        author_segment = author_segment[:year_match.start()]
    
    doi_match = re.search(r'\bDOI:', author_segment, re.IGNORECASE)
    if doi_match:
        author_segment = author_segment[:doi_match.start()]
    
    authors = []
    parts = author_segment.split(',')
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        if re.match(r'^et\s+al\.?$', part, re.IGNORECASE):
            continue
        
        cleaned = re.sub(r'\b[A-Z]{1,3}\b', '', part)
        cleaned = re.sub(r'\.', '', cleaned)
        cleaned = cleaned.strip()
        
        if not cleaned:
            continue
        
        tokens = cleaned.split()
        if tokens:
            family_name = tokens[0]
            family_name = unicodedata.normalize('NFKC', family_name)
            family_name = re.sub(r'[^\w\s-]', '', family_name)
            family_name = family_name.lower().strip()
            
            if family_name and len(family_name) > 1:
                authors.append(family_name)
    
    return authors
