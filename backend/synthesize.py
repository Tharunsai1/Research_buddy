"""Stage 4 — cross-paper synthesis: per-search landscape + global reading map."""

from __future__ import annotations

import os

from llm import parse_json
from models import (
    EdgeOut,
    Extraction,
    GlobalMapOut,
    IncrementalMapOut,
    LandscapeOut,
    Paper,
    QueryExpansion,
    ReadingStep,
)

# Above this many papers, re-clustering the whole collection stops being worth
# it: the prompt and the reply both scale with the library, and a single call
# starts brushing the provider timeout. See `update_global_map`.
FULL_RECLUSTER_MAX = int(os.getenv("RC_FULL_RECLUSTER_MAX", "40"))

# Papers the model declined to place land here, and are retried next search.
UNSORTED = "Unsorted"


async def expand_queries(topic: str) -> list[str]:
    """Stage 1 helper — turn the user's topic into 2-3 arXiv API queries."""
    try:
        result = await parse_json(
            QueryExpansion,
            system=(
                "You write search queries for the arXiv API. Given a machine-learning "
                "research topic, produce 2-3 diverse search_query strings that together "
                "give good coverage: the canonical phrasing, a synonym or subtopic, and "
                "optionally a category-filtered variant. Use arXiv query syntax "
                '(all:"..." / ti:"..." / AND / cat:cs.LG). Keep each query simple.'
            ),
            user=f"Research topic: {topic}",
            max_tokens=500,
        )
        queries = [q for q in result.queries if q.strip()][:3]
    except Exception:
        queries = []
    # Always include the raw topic as a safety net.
    fallback = f'all:"{topic}"' if " " in topic else f"all:{topic}"
    if not queries:
        queries = [fallback, topic]
    elif fallback not in queries:
        queries.append(fallback)
    return queries[:4]


def _paper_block(i: int, paper: Paper, ex: Extraction) -> str:
    return (
        f"[{i}] {paper.title} ({paper.published[:4]}, {ex.paper_type})\n"
        f"    TL;DR: {ex.tldr}\n"
        f"    Problem: {ex.problem}\n"
        f"    Method: {ex.method}\n"
        f"    Results: {ex.key_results}\n"
        f"    Keywords: {', '.join(ex.keywords)}"
    )


def _valid_indices(indices: list[int], n: int) -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for i in indices:
        if 1 <= i <= n and i not in seen:
            seen.add(i)
            out.append(i)
    return out


async def synthesize_landscape(
    topic: str, papers: list[Paper], extractions: dict[str, Extraction]
) -> LandscapeOut:
    n = len(papers)
    blocks = "\n\n".join(
        _paper_block(i, p, extractions[p.id]) for i, p in enumerate(papers, start=1)
    )
    landscape = await parse_json(
        LandscapeOut,
        system=(
            "You are a research-field cartographer. Given structured summaries of the "
            "top papers on a topic, synthesize the research landscape: thematic clusters, "
            "how papers relate (builds_on / compares_to / complements / evaluates / extends), "
            "genuine tensions or tradeoffs between approaches, points of consensus, open "
            "problems, and a reading order (foundation -> core -> frontier). Refer to papers "
            "strictly by their [index]. Every paper must appear in exactly one cluster and "
            "exactly once in the reading order."
        ),
        user=f"Topic: {topic}\n\nPapers:\n\n{blocks}",
        max_tokens=8000,
        thinking=True,
    )

    # --- validation / repair ------------------------------------------------
    assigned: set[int] = set()
    for cluster in landscape.clusters:
        cluster.paper_indices = [
            i for i in _valid_indices(cluster.paper_indices, n) if i not in assigned
        ]
        assigned.update(cluster.paper_indices)
    landscape.clusters = [c for c in landscape.clusters if c.paper_indices]
    orphans = [i for i in range(1, n + 1) if i not in assigned]
    if orphans:
        if landscape.clusters:
            landscape.clusters[-1].paper_indices.extend(orphans)
        else:
            from models import ClusterOut

            landscape.clusters = [
                ClusterOut(name="Papers", description="All papers.", paper_indices=orphans)
            ]

    landscape.edges = _clean_edges(landscape.edges, n)

    for tension in landscape.tensions:
        tension.side_a_indices = _valid_indices(tension.side_a_indices, n)
        tension.side_b_indices = _valid_indices(tension.side_b_indices, n)
    landscape.tensions = [
        t for t in landscape.tensions if t.side_a_indices or t.side_b_indices
    ]
    for problem in landscape.open_problems:
        problem.related_indices = _valid_indices(problem.related_indices, n)

    ordered: list[ReadingStep] = []
    seen: set[int] = set()
    for step in landscape.reading_order:
        if 1 <= step.index <= n and step.index not in seen:
            seen.add(step.index)
            ordered.append(step)
    for i in range(1, n + 1):
        if i not in seen:
            ordered.append(ReadingStep(index=i, stage="core", why=""))
    landscape.reading_order = ordered
    return landscape


def _clean_edges(edges: list[EdgeOut], n: int) -> list[EdgeOut]:
    seen_pairs: set[tuple[int, int]] = set()
    cleaned: list[EdgeOut] = []
    for edge in edges:
        if not (1 <= edge.source <= n and 1 <= edge.target <= n):
            continue
        if edge.source == edge.target:
            continue
        pair = (min(edge.source, edge.target), max(edge.source, edge.target))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        cleaned.append(edge)
    return cleaned


async def synthesize_global_map(
    papers: list[Paper],
    extractions: dict[str, Extraction],
    paper_search: dict[str, str],
    existing_cluster_names: list[str],
) -> GlobalMapOut:
    """Re-cluster the whole collection after a new search merges in."""
    n = len(papers)
    lines = "\n".join(
        f"[{i}] {p.title} ({p.published[:4]}) — {extractions[p.id].tldr} "
        f"[keywords: {', '.join(extractions[p.id].keywords[:5])}] "
        f"[from search: {paper_search.get(p.id, '?')}]"
        for i, p in enumerate(papers, start=1)
    )
    hint = (
        f"Existing cluster names (reuse when still appropriate): {', '.join(existing_cluster_names)}\n\n"
        if existing_cluster_names
        else ""
    )
    result = await parse_json(
        GlobalMapOut,
        system=(
            "You maintain a growing reading map of arXiv papers. Partition ALL papers "
            "into 4-8 thematic clusters (every paper in exactly one cluster; prefer "
            "stable, reusable cluster names). Then add 0-10 bridge edges connecting "
            "strongly related papers that came from different searches."
        ),
        user=f"{hint}Papers:\n\n{lines}",
        max_tokens=4000,
    )

    assigned: set[int] = set()
    for cluster in result.clusters:
        cluster.paper_indices = [
            i for i in _valid_indices(cluster.paper_indices, n) if i not in assigned
        ]
        assigned.update(cluster.paper_indices)
    result.clusters = [c for c in result.clusters if c.paper_indices]
    orphans = [i for i in range(1, n + 1) if i not in assigned]
    if orphans:
        if result.clusters:
            result.clusters[-1].paper_indices.extend(orphans)
        else:
            from models import MapClusterOut

            result.clusters = [MapClusterOut(name="Papers", paper_indices=orphans)]
    result.bridge_edges = _clean_edges(result.bridge_edges, n)
    return result


def _topic_cluster_name(topic: str) -> str:
    """A cluster name for the search topic itself, e.g. 'stable diffusion' -> 'Stable Diffusion'."""
    cleaned = " ".join(topic.split())[:40].strip()
    if not cleaned:
        return ""
    # Leave existing capitalisation alone (MCP, LLM); only fix all-lowercase input.
    return cleaned.title() if cleaned.islower() else cleaned


def _partition_map(
    papers: list[Paper],
    extractions: dict[str, Extraction],
    current: dict,
) -> tuple[list[dict], list[Paper]]:
    """Split the library into settled clusters and papers still needing a home."""
    by_id = {p.id: p for p in papers}
    settled: list[dict] = []
    placed: set[str] = set()
    for cluster in current.get("clusters", []):
        ids = [pid for pid in cluster.get("paper_ids", []) if pid in by_id]
        # Papers parked in Unsorted get another shot at a real cluster.
        if not ids or cluster.get("name") == UNSORTED:
            continue
        settled.append({"name": cluster["name"], "paper_ids": ids})
        placed.update(ids)
    pending = [p for p in papers if p.id not in placed and p.id in extractions]
    return settled, pending


async def _place_new_papers(
    papers: list[Paper],
    extractions: dict[str, Extraction],
    settled: list[dict],
    pending: list[Paper],
    prior_edges: list[dict],
    topic: str,
) -> dict:
    """Slot the not-yet-mapped papers into the clusters that already exist.

    A full re-cluster spends one call whose prompt *and* reply grow with the
    whole collection. Showing settled papers as bare titles and asking only
    where the new arrivals go keeps that cost roughly flat as the library
    grows — and stops every search from reshuffling clusters the reader has
    already learned their way around.
    """
    by_id = {p.id: p for p in papers}
    index_of = {p.id: i for i, p in enumerate(papers, start=1)}
    placed = {pid for c in settled for pid in c["paper_ids"]}
    pending = pending[:40]  # matches IncrementalMapOut.assignments maxItems

    roster = "\n\n".join(
        f"## {c['name']}\n"
        + "\n".join(f"[{index_of[pid]}] {by_id[pid].title}" for pid in c["paper_ids"])
        for c in settled
    )

    # Offering the new topic as a listed, empty cluster works where asking the
    # model to invent one does not: told only to "create a new cluster when
    # nothing fits", it anchors on the existing names and files everything under
    # the nearest neighbour (a whole Stable Diffusion search landed in
    # "Multimodal & Sensor Fusion"). Picking from a list is a far easier call.
    candidate = _topic_cluster_name(topic)
    if candidate and not any(c["name"].casefold() == candidate.casefold() for c in settled):
        roster += (
            f"\n\n## {candidate}\n"
            "(new, currently empty — use this if these papers are their own topic)"
        )

    pending_block = "\n".join(
        _paper_block(index_of[p.id], p, extractions[p.id]) for p in pending
    )

    result = await parse_json(
        IncrementalMapOut,
        system=(
            "You maintain a growing reading map of arXiv papers. The existing "
            "clusters and their papers are listed first — leave those alone and "
            "never move a paper that is already in one. Place every paper under "
            "'Papers to place' into exactly one cluster.\n\n"
            "Those papers all arrived from a single new search, so they usually "
            "share a theme. Decide what that theme is before assigning anything. "
            "One listed cluster is marked new and empty: it is named after the "
            "search topic. Use it whenever these papers are really about their "
            "own subject, and reuse an existing cluster only when that cluster "
            "genuinely describes the same subject. Never stretch an existing "
            "cluster name to cover a subject it does not actually describe — a "
            "wrong-but-nearby cluster is worse than a new one. A paper may still "
            "go to a different existing cluster when it clearly belongs there.\n\n"
            "In each assignment, 'paper_index' is the bracketed number of the "
            "paper being placed and 'cluster' is the name of the cluster it goes "
            "in. Then add up to 6 bridge edges, each linking a newly placed paper "
            "(source) to a strongly related existing paper (target) by their "
            "bracketed numbers."
        ),
        user=(
            f"Existing clusters:\n\n{roster}\n\n"
            f"Papers to place (they came from a search for \"{topic}\"):\n\n"
            f"{pending_block}"
        ),
        max_tokens=1500,
    )

    merged = [dict(c) for c in settled]
    by_name = {c["name"]: c for c in merged}
    pending_by_index = {index_of[p.id]: p.id for p in pending}

    assigned: set[str] = set()
    for item in result.assignments:
        paper_id = pending_by_index.get(item.paper_index)
        if paper_id is None or paper_id in assigned:
            continue
        name = item.cluster.strip() or UNSORTED
        target = by_name.get(name)
        if target is None:
            target = {"name": name, "paper_ids": []}
            by_name[name] = target
            merged.append(target)
        target["paper_ids"].append(paper_id)
        assigned.add(paper_id)

    leftover = [p.id for p in papers if p.id not in placed and p.id not in assigned]
    if leftover:
        target = by_name.get(UNSORTED)
        if target is None:
            target = {"name": UNSORTED, "paper_ids": []}
            merged.append(target)
        target["paper_ids"].extend(leftover)

    # Keep the edges already on the map; add only ones touching a new paper.
    edges = [dict(e) for e in prior_edges]
    seen = {(e["source"], e["target"]) for e in edges}
    seen |= {(e["target"], e["source"]) for e in edges}
    n = len(papers)
    for edge in result.bridge_edges:
        if not (1 <= edge.source <= n and 1 <= edge.target <= n):
            continue
        source_id, target_id = papers[edge.source - 1].id, papers[edge.target - 1].id
        if source_id == target_id or (source_id, target_id) in seen:
            continue
        if source_id not in assigned and target_id not in assigned:
            continue
        seen.add((source_id, target_id))
        seen.add((target_id, source_id))
        edges.append(
            {
                "source": source_id,
                "target": target_id,
                "kind": edge.kind,
                "description": edge.description,
            }
        )

    return {"clusters": [c for c in merged if c["paper_ids"]], "bridge_edges": edges}


async def update_global_map(
    papers: list[Paper],
    extractions: dict[str, Extraction],
    paper_search: dict[str, str],
    current: dict,
    topic: str = "",
) -> dict:
    """Grow the reading map after a search, as `{clusters, bridge_edges}` of ids."""
    if len(papers) > FULL_RECLUSTER_MAX:
        settled, pending = _partition_map(papers, extractions, current)
        # No settled map to grow yet: fall through and build one from scratch.
        if settled:
            if not pending:
                # The map already covers the library — nothing to ask the model.
                return {
                    "clusters": settled,
                    "bridge_edges": [dict(e) for e in current.get("bridge_edges", [])],
                }
            return await _place_new_papers(
                papers,
                extractions,
                settled,
                pending,
                current.get("bridge_edges", []),
                topic,
            )

    names = [c["name"] for c in current.get("clusters", []) if c["name"] != UNSORTED]
    result = await synthesize_global_map(papers, extractions, paper_search, names)
    return {
        "clusters": [
            {"name": c.name, "paper_ids": [papers[i - 1].id for i in c.paper_indices]}
            for c in result.clusters
        ],
        "bridge_edges": [
            {
                "source": papers[e.source - 1].id,
                "target": papers[e.target - 1].id,
                "kind": e.kind,
                "description": e.description,
            }
            for e in result.bridge_edges
        ],
    }
