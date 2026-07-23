"""Orchestrates the four-stage pipeline for one search."""

from __future__ import annotations

import asyncio
import os
import time

import store
from arxiv_client import search_arxiv
from extract import extract_many
from models import Job
from rerank import cross_encoder_rank, llm_shortlist
from synthesize import expand_queries, synthesize_landscape, update_global_map

FINAL_PAPERS = int(os.getenv("RC_PAPERS", "8"))
MAX_CANDIDATES = int(os.getenv("RC_CANDIDATES", "60"))


async def run_pipeline(job: Job) -> None:
    try:
        await _run(job)
        job.status = "done"
    except Exception as exc:  # surface any stage failure to the UI
        job.status = "error"
        job.error = str(exc)
        for stage in job.stages:
            if stage.status == "active":
                stage.status = "error"


async def _run(job: Job) -> None:
    query = job.query

    # ---- Stage 1: Query arXiv ---------------------------------------------
    stage = job.stage("query")
    stage.status = "active"
    stage.detail = "Writing search queries…"
    queries = await expand_queries(query)
    stage.detail = f"Searching arXiv ({len(queries)} queries)…"
    candidates = await asyncio.to_thread(search_arxiv, queries, 25, MAX_CANDIDATES)
    if not candidates:
        raise RuntimeError(f'arXiv returned no papers for "{query}". Try a broader topic.')
    stage.detail = f"{len(candidates)} candidate papers"
    stage.status = "done"

    # ---- Stage 2: Rank by relevance ---------------------------------------
    stage = job.stage("rank")
    stage.status = "active"
    stage.detail = f"Scoring {len(candidates)} candidates with the cross-encoder…"
    ranked = await cross_encoder_rank(query, candidates)
    if ranked is None:
        # Cross-encoder unavailable -> let the LLM pick straight from the pool.
        stage.detail = "Cross-encoder unavailable — using LLM ranking only"
        pool = candidates[: min(30, len(candidates))]
    else:
        pool = ranked[: min(20, len(ranked))]
        stage.detail = f"Cross-encoder scored {len(candidates)} papers — LLM picking top {FINAL_PAPERS}…"
    selected = await llm_shortlist(query, pool, FINAL_PAPERS)
    stage.detail = f"Selected {len(selected)} papers"
    stage.status = "done"

    # ---- Stage 3: Generate summaries --------------------------------------
    stage = job.stage("summarize")
    stage.status = "active"
    cached = store.get_cached_extractions([p.id for p in selected])

    def on_progress(done: int, total: int) -> None:
        stage.detail = f"Reading papers ({done}/{total})"

    extractions = await extract_many(selected, cached, on_progress)
    stage.detail = f"Summarized {len(selected)} papers"
    stage.status = "done"

    # ---- Stage 4: Map research landscape -----------------------------------
    stage = job.stage("map")
    stage.status = "active"
    stage.detail = "Synthesizing the research landscape…"
    landscape = await synthesize_landscape(query, selected, extractions)

    def ids(indices: list[int]) -> list[str]:
        return [selected[i - 1].id for i in indices]

    search_id = store.make_search_id(query)
    search = {
        "id": search_id,
        "query": query,
        "title": landscape.title,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "paper_ids": [p.id for p in selected],
        "overview": landscape.overview,
        "clusters": [
            {"name": c.name, "description": c.description, "paper_ids": ids(c.paper_indices)}
            for c in landscape.clusters
        ],
        "edges": [
            {
                "source": selected[e.source - 1].id,
                "target": selected[e.target - 1].id,
                "kind": e.kind,
                "description": e.description,
            }
            for e in landscape.edges
        ],
        "tensions": [
            {
                "name": t.name,
                "description": t.description,
                "side_a": {"label": t.side_a_label, "paper_ids": ids(t.side_a_indices)},
                "side_b": {"label": t.side_b_label, "paper_ids": ids(t.side_b_indices)},
            }
            for t in landscape.tensions
        ],
        "consensus": landscape.consensus,
        "open_problems": [
            {"title": p.title, "description": p.description, "paper_ids": ids(p.related_indices)}
            for p in landscape.open_problems
        ],
        "reading_order": [
            {"paper_id": selected[s.index - 1].id, "stage": s.stage, "why": s.why}
            for s in landscape.reading_order
        ],
    }

    store.merge_search_results(query, selected, extractions)
    store.save_search(search)
    store.add_search_meta(
        {
            "id": search_id,
            "query": query,
            "title": landscape.title,
            "created_at": search["created_at"],
            "paper_count": len(selected),
        }
    )

    # Global reading map: first search reuses the landscape clusters; later
    # searches re-cluster the whole collection so the map grows coherently.
    prior_searches = len(store.collection_snapshot()["searches"])
    if prior_searches <= 1:
        store.set_global_map(
            clusters=[
                {"name": c["name"], "paper_ids": c["paper_ids"]} for c in search["clusters"]
            ],
            bridge_edges=[],
        )
    else:
        stage.detail = "Updating the global reading map…"
        papers = store.all_papers()
        global_map = await update_global_map(
            papers,
            store.all_extractions(),
            store.paper_search_map(),
            store.existing_map(),
            query,
        )
        store.set_global_map(**global_map)

    stage.detail = "Landscape ready"
    stage.status = "done"
    job.search_id = search_id
