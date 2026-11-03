import pytest

from app.audit_report import render_html


def claim(verdict: str, text: str, **extra: object) -> dict:
    return {
        "claim": text,
        "quote": "quoted words",
        "line": 12,
        "section": "Formulas",
        "verdict": verdict,
        "explanation": "because",
        "design_evidence": [
            {"path": "design/a.md", "section": None, "start_line": 1, "end_line": 4, "text": "d"}
        ],
        "implementation_evidence": [],
        **extra,
    }


def report(*claims: dict) -> dict:
    return {
        "document": "design/a.md",
        "section_filter": None,
        "generated": "2026-11-03T00:00:00+00:00",
        "model": "qwen3.5",
        "judge_mode": "per_source",
        "passages_read": 3,
        "claims": list(claims),
    }


def test_everything_from_documents_and_the_model_is_escaped() -> None:
    page = render_html(
        [report(claim("consistent", "<script>alert(1)</script>", quote="<img src=x onerror=y>"))],
        "T <b>",
        intro="<i>intro</i>",
    )
    assert "<script>alert" not in page and "<img src=x" not in page and "<title>T &lt;b&gt;" in page
    assert "&lt;script&gt;" in page and "&lt;i&gt;intro" in page


def test_mismatches_come_first_and_counts_and_reviews_are_shown() -> None:
    page = render_html(
        [
            report(
                claim("consistent", "OK claim", review={"verdict_correct": True}),
                claim("potential_discrepancy", "Bad claim", review={"verdict_correct": False}),
                claim("insufficient_evidence", "Unknown claim"),
            ),
            {**report(claim("consistent", "Second doc claim")), "document": "design/b.md"},
        ],
        "T",
    )
    assert page.index("Bad claim") < page.index("OK claim") < page.index("Unknown claim")
    assert "<b>1 / 2</b>verdicts confirmed by hand" in page
    assert "verdict WRONG" in page and "nothing cited" in page
    assert "<script" not in page  # the page runs no code at all
    assert page.index("design/a.md") < page.index("design/b.md")  # one section per document
    assert "<b>2</b>Consistent" in page  # the tally covers every document


def test_links_are_escaped_and_only_https_is_allowed() -> None:
    page = render_html([report()], "T", links=[("Code <x>", 'https://example.com/a?b="c"')])
    assert '<a href="https://example.com/a?b=&quot;c&quot;">Code &lt;x&gt;</a>' in page

    for bad in ("javascript:alert(1)", "http://example.com", "//example.com"):
        with pytest.raises(ValueError):
            render_html([report()], "T", links=[("x", bad)])
