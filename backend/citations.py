"""Derive map products from Semantic Scholar data: real citation edges,
citation metrics per paper, and prerequisite ranking.
"""

from __future__ import annotations

import re

import store
from models import Prerequisite, S2Paper

# arXiv ids carry an optional version suffix; the library stores them bare.
_VERSION = re.compile(r"v\d+$")


def _bare(arxiv_id: str) -> str:
    return _VERSION.sub("", arxiv_id.strip())


def load_all() -> dict[str, S2Paper]:
    return {pid: S2Paper(**raw) for pid, raw in store.all_s2().items()}


def metrics(s2: dict[str, S2Paper]) -> dict[str, dict]:
    """Per-paper citation numbers for the UI."""
    return {
        pid: {
            "citations": paper.citation_count,
            "influential": paper.influential_count,
            "references": paper.reference_count,
            "year": paper.year,
        }
        for pid, paper in s2.items()
    }


def citation_edges(s2: dict[str, S2Paper], library_ids: set[str]) -> list[dict]:
    """Real 'A cites B' edges between papers that are both in the library."""
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for paper_id, paper in s2.items():
        if paper_id not in library_ids:
            continue
        for reference in paper.references:
            if not reference.arxiv_id:
                continue
            target = _bare(reference.arxiv_id)
            if target not in library_ids or target == paper_id:
                continue
            pair = (paper_id, target)
            if pair in seen:
                continue
            seen.add(pair)
            edges.append(
                {
                    "source": paper_id,
                    "target": target,
                    "kind": "cites",
                    "description": "Cites (from Semantic Scholar reference list).",
                    "real": True,
                }
            )
    return edges


def prerequisites(
    s2: dict[str, S2Paper],
    library_ids: set[str],
    limit: int = 20,
    min_cited_by: int = 2,
    source_ids: set[str] | None = None,
) -> list[Prerequisite]:
    """Papers your library repeatedly cites but doesn't contain.

    Being cited by several papers in a collection is a much stronger
    foundational signal than raw citation count alone, so rank on that first.

    `source_ids` narrows which papers' reference lists are read. Scanning the
    whole library while the reader is looking at one search surfaces the
    foundations of *other* fields — T5 and GShard under a Stable Diffusion
    search — which then join that search as unconnected nodes.
    """
    sources = source_ids if source_ids is not None else library_ids
    pooled: dict[str, Prerequisite] = {}
    for paper_id, paper in s2.items():
        if paper_id not in sources:
            continue
        for reference in paper.references:
            if not reference.arxiv_id:
                continue
            target = _bare(reference.arxiv_id)
            if target in library_ids:
                continue
            entry = pooled.get(target)
            if entry is None:
                entry = Prerequisite(
                    arxiv_id=target,
                    title=reference.title,
                    citation_count=reference.citation_count,
                    year=reference.year,
                )
                pooled[target] = entry
            if paper_id not in entry.cited_by:
                entry.cited_by.append(paper_id)
            entry.citation_count = max(entry.citation_count, reference.citation_count)

    candidates = [p for p in pooled.values() if len(p.cited_by) >= min_cited_by]
    # Fall back to single-citation references when the library is still small.
    if len(candidates) < 5:
        candidates = list(pooled.values())

    candidates.sort(key=lambda p: (len(p.cited_by), p.citation_count), reverse=True)
    return candidates[:limit]


def seminal_by_cluster(
    clusters: list[dict], s2: dict[str, S2Paper]
) -> dict[str, str]:
    """cluster name -> paper id with the most citations in it."""
    result: dict[str, str] = {}
    for cluster in clusters:
        best_id, best_count = None, -1
        for paper_id in cluster.get("paper_ids", []):
            paper = s2.get(paper_id)
            if paper and paper.citation_count > best_count:
                best_id, best_count = paper_id, paper.citation_count
        if best_id is not None and best_count > 0:
            result[cluster["name"]] = best_id
    return result
