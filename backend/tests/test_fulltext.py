"""Full-text fetching must tell a rendered paper from arXiv's landing page.

Papers without an HTML rendering (anything much before ~2023) get a 200 from
arxiv.org/html/{id} that redirects to the /abs/ page. That page is ~40k
characters of metadata and navigation, so every size-based heuristic accepts
it, and the no-<section> fallback wraps it into one plausible "Full text"
section. Two real deep dives were built that way — quant-ph/9903061 (509
words) and 2307.15883 (663) — and the only hint anything was wrong was the
model complaining about it inside the critique card.

No network: httpx.get is stubbed throughout.
"""

from __future__ import annotations

import httpx
import pytest

import fulltext
from fulltext import MIN_FALLBACK_WORDS, load_fulltext, parse_html

RENDERED_URL = "https://arxiv.org/html/2401.15884"
ABS_URL = "https://arxiv.org/abs/quant-ph/9903061"


def rendered_html(sections: int = 3, words: int = 300) -> str:
    body = " ".join(
        f'<section><h2>Section {i}</h2><p>{"word " * words}</p></section>'
        for i in range(1, sections + 1)
    )
    return f'<html><body><article class="ltx_document">{body}</article></body></html>'


def landing_page_html() -> str:
    """The shape that matters: no LaTeXML class, no <section>, but plenty of
    text — enough to clear any size threshold."""
    filler = "Quantum algorithms overview abstract metadata listing " * 90
    return (
        "<html><body><div id='content'>"
        f"<h1>Quantum Algorithms: An Overview</h1><p>{filler}</p>"
        "</div></body></html>"
    )


class FakeResponse:
    def __init__(self, text: str, url: str, status_code: int = 200):
        self.text = text
        self.url = url
        self.status_code = status_code


@pytest.fixture
def fetches(monkeypatch):
    """Map requested URL -> FakeResponse (or an exception to raise)."""
    requested: list[str] = []

    def script(responses: dict):
        def fake_get(url, **kwargs):
            requested.append(url)
            result = responses.get(url)
            if result is None:
                return FakeResponse("", url, status_code=404)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(fulltext.httpx, "get", fake_get)
        return requested

    return script


# ---------------------------------------------------------------------------
# _is_rendered_paper
# ---------------------------------------------------------------------------

def test_a_latexml_rendering_is_accepted():
    assert fulltext._is_rendered_paper(rendered_html(), RENDERED_URL) is True


def test_the_abs_landing_page_is_rejected():
    assert fulltext._is_rendered_paper(landing_page_html(), ABS_URL) is False


def test_a_redirect_to_abs_is_rejected_even_if_the_markup_looks_right():
    """The redirect target is decisive on its own — an /abs/ URL is never the
    paper, whatever the page happens to contain."""
    assert fulltext._is_rendered_paper(rendered_html(), ABS_URL) is False


def test_size_alone_does_not_qualify_a_page():
    """The old check let anything over 20k characters through, which is how
    the ~40k landing page got in."""
    huge = landing_page_html() + "<p>" + ("filler " * 20_000) + "</p>"
    assert len(huge) > 20_000
    assert fulltext._is_rendered_paper(huge, ABS_URL) is False


# ---------------------------------------------------------------------------
# fetch_html
# ---------------------------------------------------------------------------

def test_fetch_skips_a_landing_page_and_keeps_looking(fetches):
    """A landing page on the first candidate must not end the search."""
    requested = fetches({
        "https://arxiv.org/html/2401.15884v1": FakeResponse(landing_page_html(), ABS_URL),
        "https://arxiv.org/html/2401.15884": FakeResponse(rendered_html(), RENDERED_URL),
    })
    html, url = fulltext.fetch_html("2401.15884")
    assert url == RENDERED_URL
    assert len(requested) == 2


def test_fetch_returns_none_when_every_source_is_a_landing_page(fetches):
    fetches({
        url: FakeResponse(landing_page_html(), ABS_URL)
        for url in fulltext._candidate_urls("quant-ph/9903061")
    })
    assert fulltext.fetch_html("quant-ph/9903061") is None


def test_fetch_tries_ar5iv_for_pre_2007_ids(fetches):
    """Old ids carry a slash; it must survive into the candidate URLs."""
    ar5iv = "https://ar5iv.labs.arxiv.org/html/quant-ph/9903061"
    requested = fetches({ar5iv: FakeResponse(rendered_html(), ar5iv)})
    html, url = fulltext.fetch_html("quant-ph/9903061")
    assert url == ar5iv
    assert any("quant-ph/9903061" in r for r in requested)


def test_network_errors_fall_through_to_the_next_candidate(fetches):
    fetches({
        "https://arxiv.org/html/2401.15884v1": httpx.ConnectError("boom"),
        "https://arxiv.org/html/2401.15884": FakeResponse(rendered_html(), RENDERED_URL),
    })
    assert fulltext.fetch_html("2401.15884")[1] == RENDERED_URL


# ---------------------------------------------------------------------------
# parse_html fallback
# ---------------------------------------------------------------------------

def test_a_short_single_blob_is_not_treated_as_a_paper():
    """509 and 663 words were the real landing-page sizes that got through."""
    for count in (509, 663):
        html = f'<html><body><div class="ltx_document"><p>{"word " * count}</p></div></body></html>'
        assert parse_html("x", html, RENDERED_URL).sections == []


def test_a_long_single_blob_is_still_accepted():
    """ar5iv renderings of older papers legitimately lack <section>."""
    html = (
        '<html><body><div class="ltx_document"><p>'
        + ("word " * (MIN_FALLBACK_WORDS + 50))
        + "</p></div></body></html>"
    )
    (section,) = parse_html("x", html, RENDERED_URL).sections
    assert section.title == "Full text"
    assert section.words >= MIN_FALLBACK_WORDS


def test_properly_sectioned_papers_are_unaffected():
    full = parse_html("x", rendered_html(sections=3, words=300), RENDERED_URL)
    assert len(full.sections) == 3
    assert full.total_words > 800


# ---------------------------------------------------------------------------
# load_fulltext — what the deep dive actually calls
# ---------------------------------------------------------------------------

def test_load_returns_none_for_a_landing_page(fetches):
    """The contract the deep dive depends on: no full text means None, so
    main.py refuses instead of reading an abstract as if it were the paper."""
    fetches({
        url: FakeResponse(landing_page_html(), ABS_URL)
        for url in fulltext._candidate_urls("quant-ph/9903061")
    })
    assert load_fulltext("quant-ph/9903061") is None


def test_load_returns_sections_for_a_real_paper(fetches):
    fetches({"https://arxiv.org/html/2401.15884v1": FakeResponse(rendered_html(), RENDERED_URL)})
    full = load_fulltext("2401.15884")
    assert full is not None
    assert len(full.sections) == 3
