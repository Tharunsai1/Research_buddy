"""Semantic search over the whole library.

One embedding per paper, built once from its extraction and cached to disk —
the same nomic-embed-text model chat-with-paper already depends on, so there
is no new service to run. Ranking a query is a pure cosine-similarity sort
over the cached vectors; the only network call per search is embedding the
query itself, not another LLM completion.

Mirrors the incremental philosophy behind the global map (see
synthesize._partition_map): only papers missing from the index get embedded,
so search cost stays flat as the library grows instead of re-embedding
everything on every call.
"""

from __future__ import annotations

import math

import store
from llm import embed_texts
from models import Extraction, Paper


def _paper_text(paper: Paper, extraction: Extraction | None) -> str:
    """What gets embedded — the extraction if one exists, else the abstract.

    The extraction is preferred because it is denser: a tldr, problem, method,
    results and keywords say more per token than the abstract's prose, and
    every paper in the library already has one from the search pipeline.
    """
    if extraction is None:
        return f"{paper.title}\n{paper.abstract}"
    return (
        f"{paper.title}\n{extraction.tldr}\n{extraction.problem}\n"
        f"{extraction.method}\n{extraction.key_results}\n{extraction.why_it_matters}\n"
        f"Keywords: {', '.join(extraction.keywords)}"
    )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def ensure_index(
    papers: dict[str, Paper], extractions: dict[str, Extraction]
) -> dict[str, list[float]]:
    """Load the cached index, embedding only the papers missing from it."""
    index = store.load_library_index()
    missing = [pid for pid in papers if pid not in index]
    if not missing:
        return index
    texts = [_paper_text(papers[pid], extractions.get(pid)) for pid in missing]
    vectors = await embed_texts(texts)
    for paper_id, vector in zip(missing, vectors):
        index[paper_id] = vector
    store.save_library_index(index)
    return index


async def search(
    query: str,
    papers: dict[str, Paper],
    extractions: dict[str, Extraction],
    limit: int = 10,
) -> list[dict]:
    """Rank the library against `query`. [] for an empty query or library —
    both are normal states (a fresh library, a not-yet-typed search box), not
    errors worth raising over."""
    query = query.strip()
    if not query or not papers:
        return []
    index = await ensure_index(papers, extractions)
    if not index:
        return []
    query_vector = (await embed_texts([query], is_query=True))[0]
    scored = sorted(
        ((paper_id, _cosine(query_vector, vector)) for paper_id, vector in index.items()),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [{"paper_id": paper_id, "score": round(score, 4)} for paper_id, score in scored[:limit]]
