"""arXiv retrieval. The `arxiv` package is synchronous; call via asyncio.to_thread."""

from __future__ import annotations

import re

import arxiv

from models import Paper

# arXiv's terms ask for no more than one request every three seconds; at 1s we
# were earning HTTP 429s, which used to surface as "no such paper".
_client = arxiv.Client(page_size=50, delay_seconds=3.0, num_retries=3)


class ArxivUnavailable(RuntimeError):
    """arXiv could not be reached — rate limit, timeout, or transient failure."""

_VERSION_RE = re.compile(r"v\d+$")


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _to_paper(result: "arxiv.Result") -> Paper:
    short_id = _VERSION_RE.sub("", result.get_short_id())
    return Paper(
        id=short_id,
        title=_clean(result.title),
        authors=[a.name for a in result.authors],
        abstract=_clean(result.summary),
        published=result.published.date().isoformat(),
        categories=list(result.categories),
        primary_category=result.primary_category,
        arxiv_url=f"https://arxiv.org/abs/{short_id}",
        pdf_url=result.pdf_url or f"https://arxiv.org/pdf/{short_id}",
        comment=_clean(result.comment) if result.comment else None,
    )


def fetch_by_id(arxiv_id: str) -> Paper | None:
    """Fetch one paper by its arXiv id, or None if the API has no such paper.

    Looks the id up through the API's `id_list` parameter, which is the
    documented way to retrieve a specific article. Raises ArxivUnavailable
    rather than returning None when the API itself fails, so a rate limit is
    not reported to the reader as a missing paper.
    """
    try:
        results = list(_client.results(arxiv.Search(id_list=[arxiv_id], max_results=1)))
    except Exception as exc:
        raise ArxivUnavailable(f"arXiv did not respond: {exc}") from exc
    return _to_paper(results[0]) if results else None


def search_arxiv(
    queries: list[str],
    per_query: int = 25,
    cap: int = 60,
    newest_first: bool = False,
) -> list[Paper]:
    """Run each query against the arXiv API and return deduplicated papers.

    `newest_first` sorts by submission date instead of relevance — used by the
    field digest, which is looking for what appeared recently.
    """
    seen: set[str] = set()
    papers: list[Paper] = []
    attempted = 0
    failed: Exception | None = None
    sort_by = (
        arxiv.SortCriterion.SubmittedDate if newest_first else arxiv.SortCriterion.Relevance
    )
    for q in queries:
        q = q.strip()
        if not q:
            continue
        attempted += 1
        try:
            search = arxiv.Search(
                query=q,
                max_results=per_query,
                sort_by=sort_by,
            )
            for result in _client.results(search):
                short_id = _VERSION_RE.sub("", result.get_short_id())
                if short_id in seen:
                    continue
                seen.add(short_id)
                papers.append(_to_paper(result))
                if len(papers) >= cap:
                    return papers
        except Exception as exc:
            # One malformed query (or a transient arXiv hiccup) shouldn't sink
            # the whole retrieval stage; remaining queries still run.
            failed = exc
            continue

    # But if *every* query blew up and we have nothing, the caller must not be
    # told the topic has no papers — that is how an HTTP 429 came back to the
    # reader as "arXiv has no paper 2112.10752".
    if not papers and attempted and failed is not None:
        raise ArxivUnavailable(f"arXiv did not respond: {failed}")
    return papers
