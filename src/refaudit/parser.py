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


def extract_authors(ref_line: str) -> list[str]:
    """
    Extract author family names from a reference line.
    Returns a list of normalized family names.
    
    Heuristic: authors appear before the year (YYYY) or DOI.
    Split by commas and extract family names (last token before initials).
    """
    import unicodedata
    
    if not ref_line:
        return []
    
    author_segment = ref_line
    
    doi_match = re.search(r'\bDOI:', ref_line, re.IGNORECASE)
    if doi_match:
        author_segment = ref_line[:doi_match.start()]
    
    year_match = re.search(r'\((19|20)\d{2}\)', author_segment)
    if year_match:
        author_segment = author_segment[:year_match.start()]
    
    # Split by commas and extract family names
    authors = []
    parts = author_segment.split(',')
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
        
        if re.match(r'^et\s+al\.?$', part, re.IGNORECASE):
            continue
        
        cleaned = re.sub(r'\b[A-Z]\.\s*', '', part)
        cleaned = cleaned.strip()
        
        if not cleaned:
            continue
        
        tokens = cleaned.split()
        if tokens:
            family_name = tokens[-1]
            family_name = unicodedata.normalize('NFKC', family_name)
            family_name = re.sub(r'[^\w\s-]', '', family_name)
            family_name = family_name.lower().strip()
            
            if family_name and len(family_name) > 1:
                authors.append(family_name)
    
    return authors
