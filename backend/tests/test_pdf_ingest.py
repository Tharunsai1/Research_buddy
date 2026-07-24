"""PDF ingestion — turning an uploaded PDF into the same Paper/FullText
shapes fulltext.py produces from arXiv HTML.

Every PDF here is a real, valid, hand-built PDF (see conftest.make_test_pdf)
with real extractable text — not a mock of pypdf. What's approximate is the
content's realism (no real academic PDF), not the parsing path.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

import pdf_ingest
from tests.conftest import make_test_pdf


def filler(n: int, prefix: str = "Filler sentence") -> list[str]:
    return [f"{prefix} number {i} describing the method in some further detail." for i in range(n)]


# ---------------------------------------------------------------------------
# make_paper_id
# ---------------------------------------------------------------------------

def test_id_is_prefixed_so_it_can_never_collide_with_a_real_arxiv_id():
    pid = pdf_ingest.make_paper_id(b"content", "A Real Sounding Title")
    assert pid.startswith("local-")
    assert not re.fullmatch(r"[0-9]{4}\.[0-9]{4,5}", pid)
    assert not re.fullmatch(r"[a-z-]+/[0-9]{7}", pid)


def test_id_is_deterministic_for_identical_bytes():
    assert pdf_ingest.make_paper_id(b"same bytes", "Title") == pdf_ingest.make_paper_id(
        b"same bytes", "Title"
    )


def test_id_differs_for_different_content():
    a = pdf_ingest.make_paper_id(b"content one", "Title")
    b = pdf_ingest.make_paper_id(b"content two", "Title")
    assert a != b


def test_id_has_no_characters_that_break_filenames_or_urls():
    pid = pdf_ingest.make_paper_id(b"x", "Weird / Title: With? Punctuation!!")
    assert re.fullmatch(r"[a-z0-9-]+", pid)


# ---------------------------------------------------------------------------
# extract_pdf
# ---------------------------------------------------------------------------

@pytest.fixture
def realistic_pdf() -> bytes:
    return make_test_pdf([
        [
            "A Study of Toy Transformers for Cats",
            "Author One, Author Two",
            "Abstract",
            "We study a toy transformer variant and show it improves accuracy by "
            "ten percent on a small benchmark of feline sounds.",
            "1 Introduction",
            "Transformers are widely used across many domains of machine learning.",
        ]
        + filler(50)
    ])


def test_extract_pdf_guesses_the_title_from_the_first_page(realistic_pdf):
    paper, _ = pdf_ingest.extract_pdf(realistic_pdf, filename_hint="ignored.pdf")
    assert paper.title == "A Study of Toy Transformers for Cats"


def test_extract_pdf_skips_a_line_that_literally_says_abstract(realistic_pdf):
    """A naive 'first line' guess would sometimes land on the Abstract label
    itself rather than the title above it."""
    pdf = make_test_pdf([["Abstract", "The Real Title Comes Second"] + filler(30)])
    paper, _ = pdf_ingest.extract_pdf(pdf, filename_hint="x.pdf")
    assert paper.title != "Abstract"


def test_extract_pdf_falls_back_to_the_filename_when_the_page_has_nothing_usable():
    """Every one of the first 6 lines must be outside the usable length
    bounds (too short or absurdly long) for the fallback to trigger — title
    guessing deliberately scans a few lines, not just the very first."""
    too_long = "x " * 150
    pdf = make_test_pdf([["a", "b", too_long, too_long, too_long, too_long] + filler(30)])
    paper, _ = pdf_ingest.extract_pdf(pdf, filename_hint="my_cool_paper.pdf")
    assert paper.title == "my cool paper"


def test_extract_pdf_finds_the_abstract_and_stops_before_the_introduction(realistic_pdf):
    paper, _ = pdf_ingest.extract_pdf(realistic_pdf, filename_hint="x.pdf")
    assert paper.abstract.startswith("We study a toy transformer variant")
    assert "Introduction" not in paper.abstract
    assert "Transformers are widely used" not in paper.abstract


def test_extract_pdf_falls_back_to_leading_words_without_an_abstract_heading():
    pdf = make_test_pdf([["Some Paper Title"] + filler(80, prefix="Body text")])
    paper, _ = pdf_ingest.extract_pdf(pdf, filename_hint="x.pdf")
    assert paper.abstract.startswith("Some Paper Title Body text number 0")
    assert len(paper.abstract.split()) <= 250


def test_extract_pdf_sets_upload_specific_fields(realistic_pdf):
    paper, _ = pdf_ingest.extract_pdf(realistic_pdf, filename_hint="x.pdf")
    assert paper.authors == []
    assert paper.categories == ["uploaded"]
    assert paper.primary_category == "uploaded"
    assert paper.arxiv_url == ""
    assert paper.pdf_url == f"/api/papers/{paper.id}/pdf"
    assert paper.published == date.today().isoformat()


def test_extract_pdf_raises_on_a_page_with_no_extractable_text():
    """A scanned-image PDF has pages but no text layer — pypdf returns an
    empty string per page, which must not silently become a paper about
    nothing."""
    pdf = make_test_pdf([[]])
    with pytest.raises(ValueError, match="scanned"):
        pdf_ingest.extract_pdf(pdf, filename_hint="scanned.pdf")


def test_extract_pdf_returns_a_fulltext_matching_the_papers_id(realistic_pdf):
    paper, full = pdf_ingest.extract_pdf(realistic_pdf, filename_hint="x.pdf")
    assert full.paper_id == paper.id
    assert full.abstract == paper.abstract
    assert full.sections


# ---------------------------------------------------------------------------
# _split_sections (via extract_pdf / fulltext_from_pdf, its only callers)
# ---------------------------------------------------------------------------

def test_the_abstract_section_is_not_duplicated_as_a_body_section(realistic_pdf):
    """paper.abstract already carries this content (via _guess_abstract) —
    fulltext.py's HTML path never section-splits the abstract at all, since
    it removes the .ltx_abstract node first; the PDF path has no such tag,
    so it must filter the heading instead."""
    _, full = pdf_ingest.extract_pdf(realistic_pdf, filename_hint="x.pdf")
    assert not any(s.title.lower() == "abstract" for s in full.sections)


def test_trailing_matter_sections_are_skipped():
    pdf = make_test_pdf([
        ["Title", "1 Introduction"] + filler(20)
        + ["References"] + [f"[{i}] Some Author, Some Title, Venue {i}." for i in range(30)]
    ])
    _, full = pdf_ingest.extract_pdf(pdf, filename_hint="x.pdf")
    assert not any(s.title.lower() == "references" for s in full.sections)
    assert any(s.title == "Introduction" for s in full.sections)


def test_headings_have_their_leading_numeral_stripped():
    """Matches fulltext._heading_of's convention ('3 Methodology' ->
    'Methodology') so section titles look uniform regardless of whether a
    paper came from arXiv HTML or an uploaded PDF."""
    pdf = make_test_pdf([["Title", "3 Methodology"] + filler(20)])
    _, full = pdf_ingest.extract_pdf(pdf, filename_hint="x.pdf")
    assert any(s.title == "Methodology" for s in full.sections)
    assert not any(s.title == "3 Methodology" for s in full.sections)


def test_clear_headings_produce_named_sections():
    pdf = make_test_pdf([
        ["Paper Title", "1 Introduction"]
        + filler(15, "Intro filler")
        + ["2 Method"]
        + filler(15, "Method filler")
        + ["3 Results"]
        + filler(15, "Results filler")
    ])
    _, full = pdf_ingest.extract_pdf(pdf, filename_hint="x.pdf")
    titles = [s.title for s in full.sections]
    assert "Introduction" in titles
    assert "Method" in titles
    assert "Results" in titles


def test_ordinary_prose_is_not_mistaken_for_a_heading():
    """Running sentences must not fragment into dozens of false sections —
    the heading regex requires a short, title-like line."""
    pdf = make_test_pdf([["Paper Title"] + filler(60)])
    _, full = pdf_ingest.extract_pdf(pdf, filename_hint="x.pdf")
    # Filler sentences are 8+ words and lowercase after the first word, so
    # none should match the heading pattern; expect the chunked fallback.
    assert all(s.title.startswith("Part") for s in full.sections)


def test_headingless_text_falls_back_to_fixed_size_chunks():
    pdf = make_test_pdf([["Title, no structure here"] + filler(120)])
    _, full = pdf_ingest.extract_pdf(pdf, filename_hint="x.pdf")
    assert len(full.sections) >= 2
    assert all(s.title.startswith("Part") for s in full.sections)


def test_a_short_document_yields_no_chunked_fallback_spam():
    """Below MIN_WORDS (300), chunking shouldn't fire just because heading
    detection found nothing — one real, if unlabeled, section beats a fake
    'Part 1' padded out to look more substantial than the document is.
    (Word count must still clear extract_pdf's own 100-word floor.)"""
    pdf = make_test_pdf([["Title"] + filler(15)])  # ~165 words: above 100, below 300
    _, full = pdf_ingest.extract_pdf(pdf, filename_hint="x.pdf")
    assert len(full.sections) <= 1


# ---------------------------------------------------------------------------
# fulltext_from_pdf — the deep-dive entry point
# ---------------------------------------------------------------------------

def test_fulltext_from_pdf_returns_none_below_the_word_floor():
    pdf = make_test_pdf([["Title"] + filler(2)])
    assert pdf_ingest.fulltext_from_pdf("local-x-1", pdf) is None


def test_fulltext_from_pdf_returns_none_for_unreadable_pdfs():
    pdf = make_test_pdf([[]])
    assert pdf_ingest.fulltext_from_pdf("local-x-1", pdf) is None


def test_fulltext_from_pdf_carries_the_given_paper_id_and_abstract():
    pdf = make_test_pdf([["Title"] + filler(80)])
    full = pdf_ingest.fulltext_from_pdf("local-x-1", pdf, abstract="a stored abstract")
    assert full is not None
    assert full.paper_id == "local-x-1"
    assert full.abstract == "a stored abstract"
    assert full.sections
