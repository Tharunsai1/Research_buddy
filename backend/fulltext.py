"""Full-text ingestion — fetch and parse arXiv's rendered HTML into sections.

arXiv serves LaTeXML-rendered HTML for most papers since ~2023 at
`arxiv.org/html/{id}`; ar5iv covers much of the older archive. Both use the
same `<section>` / `ltx_*` markup, so one parser handles both and we avoid
PDF extraction entirely.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import httpx
from bs4 import BeautifulSoup, Tag

_HEADERS = {"User-Agent": "research-copilot/0.1 (local research tool)"}

# Minimum body length for a single-blob document to count as a paper — see the
# fallback branch in `parse_html`.
MIN_FALLBACK_WORDS = 1200

# Sections that add tokens without adding understanding.
_SKIP_HEADING = re.compile(
    r"^\s*(references|bibliography|acknowledg(e)?ments?|appendix\b.*|"
    r"supplementary material|author contributions|funding|"
    r"conflicts? of interest|ethics statement)\s*$",
    re.I,
)


@dataclass
class Section:
    title: str
    text: str

    @property
    def words(self) -> int:
        return len(self.text.split())


@dataclass
class FullText:
    paper_id: str
    source_url: str
    abstract: str
    sections: list[Section] = field(default_factory=list)

    @property
    def total_words(self) -> int:
        return sum(s.words for s in self.sections)


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _candidate_urls(arxiv_id: str) -> list[str]:
    base = arxiv_id.strip()
    return [
        f"https://arxiv.org/html/{base}v1",
        f"https://arxiv.org/html/{base}",
        f"https://ar5iv.labs.arxiv.org/html/{base}",
    ]


# When a paper has no HTML rendering, arXiv answers /html/{id} with a 200 that
# redirects to the /abs/ landing page. That page is ~40k characters of
# metadata and navigation, so a size threshold cannot tell it apart from a
# real paper — quant-ph/9903061 and 2307.15883 both sailed through and parsed
# into a plausible-looking 500-700 word "Full text" section, which the deep
# dive then read as if it were the paper.
_ABS_PAGE = re.compile(r"://arxiv\.org/abs/", re.I)


def _is_rendered_paper(html: str, url: str) -> bool:
    """True only for an actual LaTeXML rendering, not a landing page.

    Both arxiv.org/html and ar5iv emit LaTeXML, whose document class is the
    reliable positive signal; the landing page never carries it.
    """
    return "ltx_document" in html and not _ABS_PAGE.search(url)


def fetch_html(arxiv_id: str) -> tuple[str, str] | None:
    """Return (html, source_url) for the first source that serves this paper."""
    for url in _candidate_urls(arxiv_id):
        try:
            response = httpx.get(
                url, follow_redirects=True, timeout=45.0, headers=_HEADERS
            )
        except httpx.HTTPError:
            continue
        if response.status_code != 200:
            continue
        text = response.text
        if not _is_rendered_paper(text, str(response.url)):
            continue
        return text, str(response.url)
    return None


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def _clean_tree(root: Tag) -> None:
    """Strip noise in place: nav, scripts, bibliographies, raw math markup."""
    for tag in root.select(
        "script, style, nav, header, footer, .ltx_bibliography, .ltx_pagination, "
        ".ltx_tag_section, .ltx_role_footnote, .ltx_authors, .ltx_TOC"
    ):
        tag.decompose()

    # Replace rendered math with its LaTeX source — far more legible to an LLM
    # than the flattened glyph soup `get_text()` produces from <math>.
    for math in root.find_all("math"):
        alt = (math.get("alttext") or "").strip()
        math.replace_with(f" ${alt}$ " if 0 < len(alt) <= 160 else " [math] ")


def _text_of(node: Tag) -> str:
    text = node.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    # LaTeXML leaves stray footnote/ref markers behind.
    text = re.sub(r"\s+([.,;:)])", r"\1", text)
    return text.strip()


def _heading_of(section: Tag) -> str:
    heading = section.find(["h1", "h2", "h3", "h4"], recursive=True)
    if heading is None:
        return "Section"
    title = re.sub(r"\s+", " ", heading.get_text(" ", strip=True)).strip()
    # Drop the leading numeral LaTeXML emits ("3 Methodology" -> "Methodology").
    return re.sub(r"^\d+(\.\d+)*\s*", "", title) or "Section"


def parse_html(paper_id: str, html: str, source_url: str) -> FullText:
    soup = BeautifulSoup(html, "lxml")
    root = soup.find("article") or soup.body or soup
    _clean_tree(root)

    abstract_node = root.select_one(".ltx_abstract")
    abstract = ""
    if abstract_node is not None:
        abstract = _text_of(abstract_node)
        abstract = re.sub(r"^Abstract\s*", "", abstract, flags=re.I)
        abstract_node.decompose()

    # Top-level sections only — nested subsections come along inside their
    # parent, which keeps each chunk topically coherent.
    sections: list[Section] = []
    for node in root.find_all("section"):
        if node.find_parent("section") is not None:
            continue
        title = _heading_of(node)
        if _SKIP_HEADING.match(title):
            continue
        text = _text_of(node)
        # Strip the heading itself off the front of the body text.
        if text.lower().startswith(title.lower()):
            text = text[len(title):].lstrip(" .:")
        if len(text.split()) < 40:
            continue
        sections.append(Section(title=title, text=text))

    # Fallback for documents that don't use <section> (older ar5iv output).
    # The floor is deliberately high: a whole paper's body runs to thousands
    # of words, and the arXiv landing pages that used to reach this branch
    # carried only 509 and 663, so the original 200-word floor accepted them.
    if not sections:
        body = _text_of(root)
        if len(body.split()) >= MIN_FALLBACK_WORDS:
            sections = [Section(title="Full text", text=body)]

    return FullText(
        paper_id=paper_id,
        source_url=source_url,
        abstract=abstract,
        sections=sections,
    )


def load_fulltext(arxiv_id: str) -> FullText | None:
    fetched = fetch_html(arxiv_id)
    if fetched is None:
        return None
    full = parse_html(arxiv_id, *fetched)
    return full if full.sections else None


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def trim_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]) + " …"


def chunk_for_embedding(
    full: FullText, target_words: int = 220, overlap: int = 40
) -> list[dict]:
    """Sentence-aware chunks tagged with their section, for retrieval."""
    chunks: list[dict] = []
    for section in full.sections:
        sentences = re.split(r"(?<=[.!?])\s+", section.text)
        current: list[str] = []
        count = 0
        for sentence in sentences:
            words = len(sentence.split())
            if count + words > target_words and current:
                chunks.append({"section": section.title, "text": " ".join(current)})
                # Carry a little context across the boundary.
                tail: list[str] = []
                tail_words = 0
                for previous in reversed(current):
                    tail_words += len(previous.split())
                    tail.insert(0, previous)
                    if tail_words >= overlap:
                        break
                current, count = tail, tail_words
            current.append(sentence)
            count += words
        if current:
            chunks.append({"section": section.title, "text": " ".join(current)})
    return [c for c in chunks if len(c["text"].split()) >= 20]
