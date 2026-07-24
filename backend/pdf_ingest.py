"""PDF ingestion — the non-arXiv entry point into the pipeline.

Extracts an uploaded PDF into the same `Paper` + `FullText`/`Section` shapes
`fulltext.py` produces from arXiv's rendered HTML, so every downstream stage
— extraction, clustering, deep dive, chat, flashcards — runs unchanged
regardless of where a paper came from. The one thing this deliberately does
NOT do is guess: author lists and venues are layout-dependent and unreliable
to parse from arbitrary PDFs, so they are left empty rather than invented.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date

from pypdf import PdfReader

from fulltext import FullText, Section
from models import Paper

# A "section" from fixed-size chunking (used when heading detection fails,
# e.g. two-column layouts) — matches deepdive.py's SECTION_WORD_LIMIT so
# chunks land in the same size range as ones from real papers.
CHUNK_WORDS = 900
MIN_WORDS = 300  # below this, there's nothing worth reading in depth

# A short, title-cased or numbered line ("3.2 Related Work", "Conclusion")
# followed by body text — heuristic, not a real layout parser, so it is
# deliberately conservative: better to under-split into fewer, larger
# sections than to shred running prose into false headings.
_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Za-z0-9 ,:/\-]{2,60}$")

# Sections that add tokens without adding understanding (same rationale as
# fulltext._SKIP_HEADING), plus "abstract": fulltext.py's HTML path never
# section-splits the abstract at all — it extracts and removes the
# .ltx_abstract node before section-splitting even sees the rest of the
# document. A PDF has no such tag to key off, so the same content would
# otherwise appear twice: once as paper.abstract, once again as a section.
_SKIP_HEADING = re.compile(
    r"^\s*(abstract|references|bibliography|acknowledg(e)?ments?|appendix\b.*|"
    r"supplementary material|author contributions|funding|"
    r"conflicts? of interest|ethics statement)\s*$",
    re.I,
)


def make_paper_id(pdf_bytes: bytes, title: str) -> str:
    """Content-hash based, so re-uploading the same file is idempotent
    (merge_search_results treats a matching id as already-in-library) rather
    than creating a duplicate. Prefixed so it can never collide with a real
    arXiv id, which is always digits or a category slash."""
    digest = hashlib.sha1(pdf_bytes).hexdigest()[:10]
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "paper"
    return f"local-{slug}-{digest}"


def _page_texts(reader: PdfReader) -> list[str]:
    texts = []
    for page in reader.pages:
        try:
            texts.append((page.extract_text() or "").strip())
        except Exception:
            texts.append("")
    return texts


def _guess_title(pages: list[str], fallback: str) -> str:
    if pages:
        for line in pages[0].splitlines()[:6]:
            stripped = line.strip()
            if 8 <= len(stripped) <= 200 and not stripped.lower().startswith("abstract"):
                return stripped
    return fallback


def _guess_abstract(pages: list[str]) -> str:
    head = "\n".join(pages[:2])
    match = re.search(
        r"abstract\b[:\s]*\n?(.+?)(?:\n\s*\n|\b(?:1\.?\s*)?introduction\b)",
        head,
        re.I | re.S,
    )
    if match:
        text = re.sub(r"\s+", " ", match.group(1)).strip()
        if 40 <= len(text) <= 3000:
            return text
    words = re.sub(r"\s+", " ", head).split()
    return " ".join(words[:250])


def _split_sections(full_text: str) -> list[Section]:
    sections: list[Section] = []
    title = "Full text"
    buffer: list[str] = []
    headings_found = 0

    def flush() -> None:
        if _SKIP_HEADING.match(title):
            return
        text = re.sub(r"\s+", " ", " ".join(buffer)).strip()
        if len(text.split()) >= 40:
            sections.append(Section(title=title, text=text))

    for line_index, line in enumerate(full_text.splitlines()):
        stripped = line.strip()
        # Line 0 is virtually always the paper's own title (already captured
        # separately by _guess_title), not a section boundary — matching it
        # here would count as "a heading was found" for a document that has
        # no real structure at all, silently disabling the chunking fallback.
        if line_index > 0 and _HEADING.match(stripped) and len(stripped.split()) <= 8:
            flush()
            headings_found += 1
            # Drop the leading numeral ("3 Methodology" -> "Methodology"),
            # matching fulltext._heading_of so section titles look uniform
            # regardless of whether a paper came from arXiv HTML or a PDF.
            title = re.sub(r"^\d+(\.\d+)*\s*", "", stripped) or stripped
            buffer = []
        else:
            buffer.append(line)
    flush()

    # Chunking must only trigger when heading detection genuinely found
    # nothing (an unstructured or two-column document) — not merely when
    # filtering trimmed real, found sections down to one or zero. The
    # fallback re-derives from the raw, unfiltered text, so running it
    # whenever few sections *survived* would silently undo the References/
    # Abstract skip above by re-including that same text as "Part N".
    if headings_found == 0 and len(sections) <= 1:
        words = full_text.split()
        if len(words) < MIN_WORDS:
            return sections
        sections = [
            Section(title=f"Part {i // CHUNK_WORDS + 1}", text=" ".join(words[i : i + CHUNK_WORDS]))
            for i in range(0, len(words), CHUNK_WORDS)
        ]
    return sections


def fulltext_from_pdf(paper_id: str, pdf_bytes: bytes, abstract: str = "") -> FullText | None:
    """The deep-dive entry point: rebuild a FullText from stored PDF bytes.

    Mirrors fulltext.load_fulltext's contract — None means "nothing worth
    reading in depth," which main.py already turns into a clean refusal
    rather than a deep dive built from too little text.
    """
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = _page_texts(reader)
    full_text = "\n".join(pages)
    if len(full_text.split()) < MIN_WORDS:
        return None
    sections = _split_sections(full_text)
    if not sections:
        return None
    return FullText(paper_id=paper_id, source_url="uploaded PDF", abstract=abstract, sections=sections)


def extract_pdf(pdf_bytes: bytes, filename_hint: str = "") -> tuple[Paper, FullText]:
    """The upload entry point: guess a Paper record and build its FullText
    in one pass over the same extracted pages."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages = _page_texts(reader)
    full_text = "\n".join(pages)
    if len(full_text.split()) < 100:
        raise ValueError(
            "Could not extract readable text from this PDF — it may be scanned "
            "images rather than a text layer."
        )

    fallback_title = (
        filename_hint.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
        or "Uploaded paper"
    )
    title = _guess_title(pages, fallback_title)
    abstract = _guess_abstract(pages)
    paper_id = make_paper_id(pdf_bytes, title)

    paper = Paper(
        id=paper_id,
        title=title,
        authors=[],
        abstract=abstract,
        published=date.today().isoformat(),
        categories=["uploaded"],
        primary_category="uploaded",
        arxiv_url="",
        pdf_url=f"/api/papers/{paper_id}/pdf",
    )
    sections = _split_sections(full_text)
    full = FullText(paper_id=paper_id, source_url="uploaded PDF", abstract=abstract, sections=sections)
    return paper, full
