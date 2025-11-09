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
