"""Tests for arXiv ID extraction, website detection, and arXiv API client."""
from refaudit.parser import extract_arxiv_id, is_website_reference


class TestExtractArxivId:
    """Tests for extract_arxiv_id function."""

    def test_explicit_arxiv_prefix_new_format(self):
        text = "Syriani E et al. arXiv:2307.06464. 2023."
        assert extract_arxiv_id(text) == "2307.06464"

    def test_explicit_arxiv_prefix_with_version(self):
        text = "Some paper. arXiv:2307.06464v1."
        assert extract_arxiv_id(text) == "2307.06464v1"

    def test_explicit_arxiv_prefix_v2(self):
        text = "arXiv:2502.03400v2"
        assert extract_arxiv_id(text) == "2502.03400v2"

    def test_arxiv_url(self):
        text = "Available at arxiv.org/abs/2307.06464"
        assert extract_arxiv_id(text) == "2307.06464"

    def test_arxiv_url_with_version(self):
        text = "https://arxiv.org/abs/2510.06708v1"
        assert extract_arxiv_id(text) == "2510.06708v1"

    def test_old_format_with_prefix(self):
        text = "arXiv:hep-th/9901001"
        assert extract_arxiv_id(text) == "hep-th/9901001"

    def test_old_format_with_version(self):
        text = "arXiv:math.AG/0601001v1"
        assert extract_arxiv_id(text) == "math.AG/0601001v1"

    def test_bare_id_with_arxiv_context(self):
        text = "Huotala A. AISysRev. arXiv 2510.06708."
        assert extract_arxiv_id(text) == "2510.06708"

    def test_no_arxiv_id(self):
        text = "Borah R et al. BMJ Open. 2017;7(2):e012545."
        assert extract_arxiv_id(text) is None

    def test_bare_id_without_arxiv_context(self):
        # Without "arXiv" in the text, bare IDs should not be extracted
        text = "Some paper with number 2307.06464 in it."
        assert extract_arxiv_id(text) is None

    def test_five_digit_id(self):
        text = "arXiv:2307.12345"
        assert extract_arxiv_id(text) == "2307.12345"

    def test_case_insensitive(self):
        text = "ARXIV:2307.06464"
        assert extract_arxiv_id(text) == "2307.06464"


class TestIsWebsiteReference:
    """Tests for is_website_reference function."""

    def test_covidence(self):
        assert is_website_reference("Covidence. Systematic review software. https://www.covidence.org/.")

    def test_rayyan(self):
        assert is_website_reference(
            "Rayyan. AI-powered tool for systematic literature reviews. https://www.rayyan.ai/."
        )

    def test_distillersr(self):
        assert is_website_reference("DistillerSR. Evidence Partners. https://www.distillersr.com/.")

    def test_elicit(self):
        assert is_website_reference("Elicit. The AI Research Assistant. https://elicit.com/.")

    def test_asreview_docs(self):
        assert is_website_reference(
            "ASReview LAB. Installation documentation. https://asreview.readthedocs.io/en/stable/lab/installation.html."
        )

    def test_journal_article_not_website(self):
        assert not is_website_reference(
            "Borah R, Brown AW, Capers PL, Kaiser KA. Analysis of the time and workers needed "
            "to conduct systematic reviews. BMJ Open. 2017;7(2):e012545."
        )

    def test_arxiv_not_website(self):
        assert not is_website_reference(
            "Syriani E, David I, Kumar G. Assessing the Ability of ChatGPT to Screen Articles "
            "for Systematic Reviews. arXiv:2307.06464. 2023."
        )


class TestArxivClientParsing:
    """Tests for ArxivClient XML parsing (unit tests with mock data)."""

    def test_parse_entry(self):
        from refaudit.arxiv import ArxivClient
        import xml.etree.ElementTree as ET

        xml_text = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2307.06464v1</id>
    <title>Assessing the Ability of ChatGPT to Screen Articles for Systematic Reviews</title>
    <published>2023-07-12T21:39:42Z</published>
    <updated>2023-07-12T21:39:42Z</updated>
    <author><name>Eugene Syriani</name></author>
    <author><name>Istvan David</name></author>
    <author><name>Gauransh Kumar</name></author>
    <arxiv:doi>10.1016/j.cola.2024.101287</arxiv:doi>
    <arxiv:journal_ref>Journal of Computer Languages, 2024</arxiv:journal_ref>
    <category term="cs.SE"/>
    <category term="cs.CL"/>
    <summary>Test abstract.</summary>
  </entry>
</feed>"""
        root = ET.fromstring(xml_text)
        client = ArxivClient()
        ns = "http://www.w3.org/2005/Atom"
        entry = root.find(f"{{{ns}}}entry")
        result = client._parse_entry(entry)

        assert result is not None
        assert result.arxiv_id == "2307.06464v1"
        assert result.title == "Assessing the Ability of ChatGPT to Screen Articles for Systematic Reviews"
        assert len(result.authors) == 3
        assert result.authors[0] == "Eugene Syriani"
        assert result.doi == "10.1016/j.cola.2024.101287"
        assert result.journal_ref == "Journal of Computer Languages, 2024"
        assert "cs.SE" in result.categories
        assert result.published == "2023-07-12T21:39:42Z"

    def test_parse_entry_without_doi(self):
        from refaudit.arxiv import ArxivClient
        import xml.etree.ElementTree as ET

        xml_text = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2510.06708v1</id>
    <title>AISysRev -- LLM-based Tool for Title-abstract Screening</title>
    <published>2025-10-09T00:00:00Z</published>
    <updated>2025-10-09T00:00:00Z</updated>
    <author><name>Antti Huotala</name></author>
    <category term="cs.SE"/>
    <summary>A paper about screening.</summary>
  </entry>
</feed>"""
        root = ET.fromstring(xml_text)
        client = ArxivClient()
        ns = "http://www.w3.org/2005/Atom"
        entry = root.find(f"{{{ns}}}entry")
        result = client._parse_entry(entry)

        assert result is not None
        assert result.arxiv_id == "2510.06708v1"
        assert result.doi is None
        assert result.journal_ref is None


class TestNormalizeArxivText:
    """Tests for _normalize_arxiv_text."""

    def test_basic_normalization(self):
        from refaudit.arxiv import _normalize_arxiv_text
        assert _normalize_arxiv_text("Hello World") == "hello world"

    def test_tex_removal(self):
        from refaudit.arxiv import _normalize_arxiv_text
        result = _normalize_arxiv_text("Study of $\\alpha$-particles")
        assert "alpha" not in result or "$" not in result

    def test_whitespace_normalization(self):
        from refaudit.arxiv import _normalize_arxiv_text
        assert _normalize_arxiv_text("  hello   world  ") == "hello world"

    def test_empty_string(self):
        from refaudit.arxiv import _normalize_arxiv_text
        assert _normalize_arxiv_text("") == ""
        assert _normalize_arxiv_text(None) == ""


class TestStripVersion:
    """Tests for _strip_version."""

    def test_strip_v1(self):
        from refaudit.arxiv import _strip_version
        assert _strip_version("2307.06464v1") == "2307.06464"

    def test_strip_v2(self):
        from refaudit.arxiv import _strip_version
        assert _strip_version("2307.06464v2") == "2307.06464"

    def test_no_version(self):
        from refaudit.arxiv import _strip_version
        assert _strip_version("2307.06464") == "2307.06464"

    def test_old_format(self):
        from refaudit.arxiv import _strip_version
        assert _strip_version("hep-th/9901001v1") == "hep-th/9901001"
