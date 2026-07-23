"""Stage 3 — structured extraction per paper (from title + abstract)."""

from __future__ import annotations

import asyncio
from typing import Callable

from llm import parse_json
from models import Extraction, Paper

_SYSTEM = (
    "You read machine-learning papers and produce faithful structured summaries "
    "from their titles and abstracts. Be specific and concrete; include numbers "
    "when the abstract states them. Never invent results that are not implied by "
    "the abstract."
)


async def extract_paper(paper: Paper) -> Extraction:
    user = (
        f"Title: {paper.title}\n"
        f"Authors: {', '.join(paper.authors[:8])}\n"
        f"Published: {paper.published}\n"
        f"Categories: {', '.join(paper.categories[:4])}\n"
        + (f"Comment: {paper.comment}\n" if paper.comment else "")
        + f"\nAbstract:\n{paper.abstract}"
    )
    return await parse_json(Extraction, system=_SYSTEM, user=user, max_tokens=1200)


async def extract_many(
    papers: list[Paper],
    cached: dict[str, Extraction],
    on_progress: Callable[[int, int], None],
    concurrency: int = 4,
) -> dict[str, Extraction]:
    """Extract all papers not in `cached`; returns {paper_id: Extraction} for every input."""
    results: dict[str, Extraction] = {p.id: cached[p.id] for p in papers if p.id in cached}
    todo = [p for p in papers if p.id not in cached]
    total = len(papers)
    done = len(results)
    on_progress(done, total)
    if not todo:
        return results

    semaphore = asyncio.Semaphore(concurrency)

    async def run(paper: Paper) -> None:
        nonlocal done
        async with semaphore:
            results[paper.id] = await extract_paper(paper)
            done += 1
            on_progress(done, total)

    await asyncio.gather(*(run(p) for p in todo))
    return results
