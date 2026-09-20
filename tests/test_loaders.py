import pytest

from app.ingestion.errors import InvalidDocumentError
from app.ingestion.loaders import extract, load_markdown, load_pdf, load_txt
from tests.pdf_helper import make_pdf


def test_txt_basic():
    doc = load_txt(b"hello\r\nworld", "notes.txt")
    assert doc.title == "notes"
    assert doc.segments[0].text == "hello\nworld"


def test_txt_strips_bom_and_rejects_bad_utf8():
    assert load_txt(b"\xef\xbb\xbfhi", "a.txt").segments[0].text == "hi"
    with pytest.raises(InvalidDocumentError):
        load_txt(b"\xff\xfe\x00bad", "a.txt")


def test_markdown_sections_and_line_numbers():
    md = b"# Towers\nintro\n\n## Poison\nstacks 3 times\n\n## Fire\nburns\n"
    doc = load_markdown(md, "towers.md")
    assert doc.title == "Towers"
    assert [(s.section, s.start_line) for s in doc.segments] == [
        ("Towers", 1),
        ("Towers > Poison", 4),
        ("Towers > Fire", 7),
    ]


def test_markdown_preamble_before_first_heading_has_no_section():
    doc = load_markdown(b"preamble\n# Title\nbody", "x.md")
    assert doc.segments[0].section is None
    assert doc.segments[1].section == "Title"


def test_markdown_ignores_headings_inside_code_fences():
    md = b"# Real\n```python\n# not a heading\nx = 1\n```\n"
    doc = load_markdown(md, "x.md")
    assert len(doc.segments) == 1
    assert "# not a heading" in doc.segments[0].text


def test_markdown_heading_levels_reset_the_path():
    doc = load_markdown(b"# A\n## B\n### C\n## D\ntext", "x.md")
    assert [s.section for s in doc.segments] == ["A", "A > B", "A > B > C", "A > D"]


def test_markdown_falls_back_to_filename_title():
    assert load_markdown(b"## only h2\ntext", "design.md").title == "design"


def test_pdf_pages_become_segments():
    doc = load_pdf(make_pdf(["First page text", "Second page text"]), "spec.pdf")
    assert doc.page_count == 2
    assert [s.page for s in doc.segments] == [1, 2]
    assert "First page text" in doc.segments[0].text
    assert doc.title == "spec"


def test_pdf_without_text_is_rejected():
    with pytest.raises(InvalidDocumentError):
        load_pdf(make_pdf([""]), "blank.pdf")


def test_corrupt_pdf_is_rejected():
    with pytest.raises(InvalidDocumentError):
        load_pdf(b"%PDF-1.4\nthis is not really a pdf", "bad.pdf")


def test_extract_dispatches_by_type():
    assert extract("txt", b"hi", "a.txt").segments[0].text == "hi"
