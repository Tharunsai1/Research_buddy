"""Research Copilot backend — FastAPI app."""

from __future__ import annotations

import asyncio
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")  # before importing modules that read env

from fastapi import FastAPI, HTTPException, Response  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import citations  # noqa: E402
import llm  # noqa: E402
import openrouter  # noqa: E402
import store  # noqa: E402
from arxiv_client import ArxivUnavailable, fetch_by_id, search_arxiv  # noqa: E402
from chat import answer_question as chat_with_paper_impl  # noqa: E402
from chat import build_index  # noqa: E402
from deepdive import run_deep_dive  # noqa: E402
from extract import extract_many, extract_paper  # noqa: E402
from fulltext import load_fulltext  # noqa: E402
from learning import (  # noqa: E402
    build_digest,
    generate_cards,
    grade_answer,
    is_due,
    relationship_cards,
    schedule,
    to_anki_tsv,
)
from models import Digest, Flashcard, MatrixRow, Paper  # noqa: E402
from synthesize import expand_queries  # noqa: E402
from research import (  # noqa: E402
    build_field_report,
    build_matrix_row,
    build_related_work,
    cite_key,
    compare_papers,
    diff_searches,
    matrix_to_csv,
    to_bibtex,
)
from semantic_scholar import S2Error, fetch_batch  # noqa: E402
from pipeline import FINAL_PAPERS, run_pipeline  # noqa: E402
from rerank import ce_status, warm_cross_encoder  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    warm_cross_encoder()
    # Restore the model the user last picked in the UI.
    saved = store.load_settings().get("engine")
    if saved:
        try:
            llm.set_engine(saved)
        except llm.LLMError:
            pass  # engine disappeared from the config; fall back to the default
    yield


app = FastAPI(title="Research Copilot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # Local tool: accept the frontend from any localhost port.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str


@app.get("/api/health")
async def health():
    status = await llm.provider_status()
    return {
        "ok": True,
        **status,
        "cross_encoder": ce_status(),
        "papers_per_search": FINAL_PAPERS,
    }


@app.get("/api/engines")
async def list_engines():
    """Selectable models, with the active one flagged."""
    active = llm.active_engine()
    return {
        "active": active["id"],
        "engines": [
            {k: v for k, v in spec.items()}
            for spec in llm.ENGINES.values()
            # Only surface Claude if a key is actually configured.
            if spec["provider"] != "anthropic" or llm.has_api_key()
        ],
        # The per-minute cap is enforced live and never surfaces to the user;
        # the per-day cap has no such backpressure, so warn before it's hit.
        "openrouter_usage": openrouter.daily_usage(),
    }


class EngineRequest(BaseModel):
    engine: str


@app.post("/api/engines/select")
async def select_engine(request: EngineRequest):
    """Switch the model used by every subsequent LLM call."""
    try:
        llm.set_engine(request.engine)
    except llm.LLMError as exc:
        raise HTTPException(400, str(exc)) from exc
    status = await llm.provider_status()
    store.save_settings({"engine": request.engine})
    return status


@app.post("/api/search")
async def start_search(request: SearchRequest):
    query = request.query.strip()
    if not query:
        raise HTTPException(400, "Query is empty.")
    if len(query) > 200:
        raise HTTPException(400, "Query is too long (200 chars max).")
    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])
    job = store.create_job(query)
    asyncio.create_task(run_pipeline(job))
    return {"job_id": job.id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = store.JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job.model_dump()


@app.get("/api/state")
def get_state():
    """Everything the UI needs: collection map, papers, extractions, searches."""
    snapshot = store.collection_snapshot()
    searches = sorted(snapshot["searches"], key=lambda s: s["created_at"], reverse=True)

    # Map edges: real citation edges first (they're ground truth), then
    # LLM-inferred relationships and cross-search bridges for pairs the
    # citation graph doesn't already connect.
    s2 = citations.load_all()
    library_ids = set(snapshot["papers"])
    edges: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    def add(edge: dict, **extra) -> None:
        pair = tuple(sorted((edge["source"], edge["target"])))
        if pair in seen_pairs:
            return
        seen_pairs.add(pair)
        edges.append({**edge, **extra})

    for edge in citations.citation_edges(s2, library_ids):
        add(edge, bridge=False)
    for edge in store.all_search_edges():
        add(edge, bridge=False, real=False)
    for edge in snapshot["map"]["bridge_edges"]:
        add(edge, bridge=True, real=False)

    clusters = snapshot["map"]["clusters"]
    return {
        "papers": snapshot["papers"],
        "extractions": snapshot["extractions"],
        "read": snapshot["read"],
        "map": {
            "clusters": clusters,
            "edges": edges,
            "seminal": citations.seminal_by_cluster(clusters, s2),
        },
        "searches": searches,
        "latest_search_id": searches[0]["id"] if searches else None,
        "deep_read": store.deep_dive_ids(),
        "citations": citations.metrics(s2),
    }


# ---------------------------------------------------------------------------
# Citation data (Semantic Scholar)
# ---------------------------------------------------------------------------

_enrich_lock = asyncio.Lock()


@app.post("/api/enrich")
async def enrich_citations(refresh: bool = False):
    """Fetch real citation counts + reference lists for the library."""
    if _enrich_lock.locked():
        raise HTTPException(409, "Citation lookup already running.")
    async with _enrich_lock:
        library = [p.id for p in store.all_papers()]
        todo = library if refresh else [p for p in library if store.load_s2(p) is None]
        if not todo:
            return {"fetched": 0, "total": len(library), "cached": len(library)}
        try:
            fetched = await fetch_batch(todo)
        except S2Error as exc:
            raise HTTPException(502, str(exc)) from exc
        for paper_id, paper in fetched.items():
            store.save_s2(paper_id, paper.model_dump())
        return {
            "fetched": len(fetched),
            "total": len(library),
            "missing": sorted(set(todo) - set(fetched)),
        }


@app.get("/api/prerequisites")
def get_prerequisites(limit: int = 20, search_id: str | None = None):
    """Foundations under the library, or under one search when `search_id` is given."""
    s2 = citations.load_all()
    library = {p.id for p in store.all_papers()}
    sources = None
    if search_id:
        search = store.load_search(search_id)
        if search is not None:
            sources = set(search["paper_ids"])
    items = citations.prerequisites(s2, library, limit=limit, source_ids=sources)
    return {
        "prerequisites": [item.model_dump() for item in items],
        "enriched": len(s2),
        "library": len(library),
        "scoped": sources is not None,
    }


class AddPaperRequest(BaseModel):
    arxiv_id: str
    search_id: str | None = None


def _attach_to_search(search_id: str, paper: Paper, citing: set[str]) -> bool:
    """Fold an added prerequisite into the search it was added from.

    Reaching the library and the global map is not enough: a search renders its
    own paper list, relationship graph, toolkit and reading order from its own
    `paper_ids`, so a paper missing from those is invisible everywhere the
    reader was actually looking when they pressed Add.
    """
    search = store.load_search(search_id)
    if search is None or paper.id in search["paper_ids"]:
        return False

    search["paper_ids"].append(paper.id)
    index_of = {pid: i + 1 for i, pid in enumerate(search["paper_ids"])}

    # Papers in *this* search that cite it — real citation edges, no LLM call.
    local_citing = [pid for pid in search["paper_ids"] if pid in citing]
    for pid in local_citing[:4]:
        search["edges"].append(
            {
                "source": pid,
                "target": paper.id,
                "kind": "builds_on",
                "description": (
                    f"[{index_of[pid]}] cites this paper — groundwork this search builds on."
                ),
                "real": True,
            }
        )

    # Group it with whichever cluster cites it most, else start a Foundations one.
    best, best_overlap = None, 0
    for cluster in search["clusters"]:
        overlap = len(set(local_citing).intersection(cluster["paper_ids"]))
        if overlap > best_overlap:
            best, best_overlap = cluster, overlap
    if best is None:
        best = next((c for c in search["clusters"] if c["name"] == "Foundations"), None)
        if best is None:
            best = {
                "name": "Foundations",
                "description": "Earlier work the papers in this search build on.",
                "paper_ids": [],
            }
            search["clusters"].append(best)
    best["paper_ids"].append(paper.id)

    # A prerequisite is by definition where the reading should start.
    search["reading_order"].insert(
        0,
        {
            "paper_id": paper.id,
            "stage": "foundation",
            "why": (
                f"Cited by {len(local_citing)} of the papers in this search — "
                "read it first for the groundwork."
                if local_citing
                else "A foundation of this field, added to your map."
            ),
        },
    )

    store.save_search(search)
    return True


@app.post("/api/papers/add")
async def add_paper(request: AddPaperRequest):
    """Pull a prerequisite paper into the library (fetch + summarize + map)."""
    arxiv_id = request.arxiv_id.strip()
    if not re.fullmatch(r"[0-9]{4}\.[0-9]{4,5}", arxiv_id):
        raise HTTPException(400, "Expected an arXiv id like 2005.11401.")
    if any(p.id == arxiv_id for p in store.all_papers()):
        return {"added": False, "reason": "Already in your library."}

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])

    try:
        paper = await asyncio.to_thread(fetch_by_id, arxiv_id)
    except ArxivUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    if paper is None:
        raise HTTPException(404, f"arXiv has no paper {arxiv_id}.")

    try:
        extraction = await extract_paper(paper)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc

    store.merge_search_results("prerequisites", [paper], {paper.id: extraction})

    # Place it in the map: the cluster whose papers cite it most, else its own.
    s2 = citations.load_all()
    snapshot = store.collection_snapshot()
    clusters = snapshot["map"]["clusters"]
    citing = {
        pid
        for pid, entry in s2.items()
        if any(
            reference.arxiv_id and reference.arxiv_id.split("v")[0] == arxiv_id
            for reference in entry.references
        )
    }
    best_cluster, best_overlap = None, 0
    for cluster in clusters:
        overlap = len(citing.intersection(cluster["paper_ids"]))
        if overlap > best_overlap:
            best_cluster, best_overlap = cluster, overlap
    if best_cluster is not None:
        best_cluster["paper_ids"].append(paper.id)
    elif clusters:
        clusters[0]["paper_ids"].append(paper.id)
    else:
        clusters = [{"name": "Foundations", "paper_ids": [paper.id]}]
    store.set_global_map(clusters, snapshot["map"]["bridge_edges"])

    attached = _attach_to_search(request.search_id, paper, citing) if request.search_id else False

    try:
        fetched = await fetch_batch([arxiv_id])
        for pid, entry in fetched.items():
            store.save_s2(pid, entry.model_dump())
    except S2Error:
        pass  # citation data is a bonus here, not required

    return {
        "added": True,
        "paper_id": paper.id,
        "title": paper.title,
        "attached_to_search": attached,
    }


@app.get("/api/searches/{search_id}")
def get_search(search_id: str):
    search = store.load_search(search_id)
    if search is None:
        raise HTTPException(404, "Search not found.")
    return search


@app.get("/api/search-diff")
def search_diff(a: str, b: str):
    """What changed between two of the reader's own past searches."""
    search_a, search_b = store.load_search(a), store.load_search(b)
    if search_a is None or search_b is None:
        raise HTTPException(404, "One or both searches not found.")
    return diff_searches(search_a, search_b, _papers_by_id())


@app.post("/api/searches/{search_id}/report")
def field_report(search_id: str):
    """Overview + clusters + reading order + flashcard progress as one .md file."""
    search = store.load_search(search_id)
    if search is None:
        raise HTTPException(404, "Search not found.")

    paper_ids = set(search.get("paper_ids") or [])
    raw_cards = [card for pid in paper_ids for card in store.load_cards(pid)]
    cards = [Flashcard(**c) for c in raw_cards]
    # A relationship card only counts for this search if both papers it
    # connects are actually in it — matches the study deck's own scoping.
    scoped = [
        c
        for c in cards
        if c.kind != "relationship" or (c.related_paper_id in paper_ids)
    ]
    reviewed = [c for c in scoped if c.reps > 0]
    scores = [c.last_score for c in reviewed if c.last_score is not None]
    card_stats = {
        "total": len(scoped),
        "relationship": sum(1 for c in scoped if c.kind == "relationship"),
        "per_paper": sum(1 for c in scoped if c.kind != "relationship"),
        "reviewed": len(reviewed),
        "due": sum(1 for c in scoped if is_due(c)),
        "avg_score": (sum(scores) / len(scores)) if scores else None,
    }

    content = build_field_report(search, _papers_by_id(), card_stats)
    filename = f"{search_id}-field-report.md"
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ReadRequest(BaseModel):
    paper_id: str
    read: bool


@app.post("/api/read")
def mark_read(request: ReadRequest):
    return {"read": store.set_read(request.paper_id, request.read)}


# ---------------------------------------------------------------------------
# Deep dive — full-text reading of a single paper
# ---------------------------------------------------------------------------

async def _run_deep_dive(job, paper: Paper) -> None:
    try:
        stage = job.stage("fetch")
        stage.status = "active"
        stage.detail = "Fetching full text from arXiv…"
        full = await asyncio.to_thread(load_fulltext, paper.id)
        if full is None:
            raise RuntimeError(
                "No HTML full text is available for this paper on arXiv "
                "(older papers are PDF-only). Abstract-level summary is still available."
            )
        stage.detail = f"{full.total_words:,} words · {len(full.sections)} sections"
        stage.status = "done"
        job.partial["source_url"] = full.source_url
        job.partial["total_words"] = full.total_words

        stage = job.stage("sections")
        stage.status = "active"
        section_stage = stage

        def on_progress(message: str) -> None:
            # deepdive reports through the section stage until it moves on.
            for key in ("sections", "synthesize", "teach"):
                if job.stage(key).status == "active":
                    job.stage(key).detail = message
                    return
            section_stage.detail = message

        async def advance(previous: str, nxt: str, detail: str) -> None:
            job.stage(previous).status = "done"
            job.stage(nxt).status = "active"
            job.stage(nxt).detail = detail

        def on_partial(key: str, value) -> None:
            job.partial[key] = value

        deep_task = asyncio.create_task(
            run_deep_dive(paper, full, on_progress, on_partial=on_partial)
        )
        # Flip stage highlighting as the deep dive announces each phase.
        while not deep_task.done():
            await asyncio.sleep(0.4)
            detail = job.stage("sections").detail
            if job.stage("sections").status == "active" and detail.startswith("Synthesizing"):
                await advance("sections", "synthesize", detail)
            elif job.stage("synthesize").status == "active" and (
                detail.startswith("Writing") or detail.startswith("Building")
            ):
                await advance("synthesize", "teach", detail)
        deep = await deep_task

        for key in ("sections", "synthesize", "teach"):
            job.stage(key).status = "done"
        job.stage("sections").detail = f"{len(deep.sections)} sections read"
        job.stage("synthesize").detail = "Synthesis complete"
        job.stage("teach").detail = f"{len(deep.glossary)} terms defined"

        stage = job.stage("index")
        stage.status = "active"
        stage.detail = "Embedding the paper for chat…"
        records = await build_index(full)
        store.save_index(paper.id, records)
        deep.chunk_count = len(records)
        stage.detail = f"{len(records)} passages indexed"
        stage.status = "done"

        store.save_deep_dive(paper.id, deep.model_dump())
        job.status = "done"
    except Exception as exc:
        job.status = "error"
        job.error = str(exc)
        for stage in job.stages:
            if stage.status == "active":
                stage.status = "error"


@app.post("/api/papers/{paper_id:path}/deepdive")
async def start_deep_dive(paper_id: str):
    papers = {p.id: p for p in store.all_papers()}
    paper = papers.get(paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found in your library.")

    existing = store.running_deep_job(paper_id)
    if existing is not None:
        return {"job_id": existing.id}

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])

    job = store.create_deep_job(paper_id)
    asyncio.create_task(_run_deep_dive(job, paper))
    return {"job_id": job.id}


@app.get("/api/papers/{paper_id:path}/deepjob")
def get_running_deep_job(paper_id: str):
    """Lets the UI resume progress if the workspace was closed mid-read."""
    job = store.running_deep_job(paper_id)
    return job.model_dump() if job else {"job_id": None}


@app.get("/api/deepjobs/{job_id}")
def get_deep_job(job_id: str):
    job = store.DEEP_JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job.model_dump()


@app.get("/api/papers/{paper_id:path}/deep")
def get_deep_dive(paper_id: str):
    deep = store.load_deep_dive(paper_id)
    if deep is None:
        raise HTTPException(404, "This paper has not been deep-read yet.")
    return deep


@app.delete("/api/papers/{paper_id:path}")
def remove_paper(paper_id: str):
    """Undo an add or a mis-placed paper: drops it from the library, every
    search it appears in, and every per-paper file (deep dive, chat index,
    citation cache, matrix row, flashcards)."""
    result = store.remove_paper(paper_id)
    if not result["removed"]:
        raise HTTPException(404, "Paper not found in your library.")
    return result


# ---------------------------------------------------------------------------
# Research toolkit
# ---------------------------------------------------------------------------

def _papers_by_id() -> dict[str, Paper]:
    return {p.id: p for p in store.all_papers()}


def _require_papers(paper_ids: list[str]) -> list[Paper]:
    papers = _papers_by_id()
    missing = [pid for pid in paper_ids if pid not in papers]
    if missing:
        raise HTTPException(404, f"Not in your library: {', '.join(missing[:3])}")
    return [papers[pid] for pid in paper_ids]


class PaperIdsRequest(BaseModel):
    paper_ids: list[str]


@app.post("/api/matrix")
async def build_matrix(request: PaperIdsRequest, refresh: bool = False):
    """Survey table rows for the given papers (cached per paper)."""
    if not request.paper_ids:
        raise HTTPException(400, "No papers selected.")
    if len(request.paper_ids) > 30:
        raise HTTPException(400, "Select 30 papers or fewer.")
    papers = _require_papers(request.paper_ids)
    extractions = store.all_extractions()

    status = await llm.provider_status()
    rows: list[dict] = []
    for paper in papers:
        cached = None if refresh else store.load_matrix_row(paper.id)
        if cached is not None:
            rows.append(cached)
            continue
        if not status["ready"]:
            raise HTTPException(400, status["detail"])
        try:
            row = await build_matrix_row(paper, extractions.get(paper.id))
        except llm.LLMError as exc:
            raise HTTPException(502, str(exc)) from exc
        store.save_matrix_row(paper.id, row.model_dump())
        rows.append(row.model_dump())
    return {"rows": rows}


@app.post("/api/matrix/csv")
def matrix_csv(request: PaperIdsRequest):
    papers = _papers_by_id()
    rows = [
        MatrixRow(**raw)
        for raw in (store.load_matrix_row(pid) for pid in request.paper_ids)
        if raw is not None
    ]
    if not rows:
        raise HTTPException(400, "Build the matrix first.")
    csv_text = matrix_to_csv(rows, papers)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="literature-matrix.csv"'},
    )


class RelatedWorkRequest(BaseModel):
    paper_ids: list[str]
    topic: str = ""


@app.post("/api/related-work")
async def related_work(request: RelatedWorkRequest):
    if len(request.paper_ids) < 2:
        raise HTTPException(400, "Select at least two papers.")
    if len(request.paper_ids) > 12:
        raise HTTPException(400, "Select 12 papers or fewer for one section.")
    papers = _require_papers(request.paper_ids)

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])
    try:
        result = await build_related_work(
            request.topic or "this research area", papers, store.all_extractions()
        )
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return result.model_dump()


@app.post("/api/bibtex")
def bibtex(request: PaperIdsRequest):
    papers = _require_papers(request.paper_ids)
    taken: set[str] = set()
    entries = [to_bibtex(paper, cite_key(paper, taken)) for paper in papers]
    return Response(
        content="\n\n".join(entries) + "\n",
        media_type="application/x-bibtex",
        headers={"Content-Disposition": 'attachment; filename="references.bib"'},
    )


class CompareRequest(BaseModel):
    paper_a: str
    paper_b: str


@app.post("/api/compare")
async def compare(request: CompareRequest):
    if request.paper_a == request.paper_b:
        raise HTTPException(400, "Pick two different papers.")
    papers = _require_papers([request.paper_a, request.paper_b])

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])
    try:
        result = await compare_papers(papers[0], papers[1], store.all_extractions())
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "paper_a": papers[0].id,
        "paper_b": papers[1].id,
        "comparison": result.model_dump(),
    }


# ---------------------------------------------------------------------------
# Learning loop: flashcards, quiz, digest
# ---------------------------------------------------------------------------

@app.post("/api/papers/{paper_id:path}/cards")
async def make_cards(paper_id: str, refresh: bool = False):
    papers = _papers_by_id()
    paper = papers.get(paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found in your library.")

    existing = store.load_cards(paper_id)
    if existing and not refresh:
        return {"cards": existing, "generated": False}

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])
    try:
        cards = await generate_cards(paper, store.all_extractions().get(paper_id))
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc

    # Keep review history for cards that survive a regeneration.
    previous = {card["id"]: card for card in existing}
    payload = []
    for card in cards:
        old = previous.get(card.id)
        if old and old.get("question") == card.question:
            card.due = old.get("due", "")
            card.interval = old.get("interval", 0)
            card.ease = old.get("ease", 2.5)
            card.reps = old.get("reps", 0)
            card.lapses = old.get("lapses", 0)
            card.last_score = old.get("last_score")
        payload.append(card.model_dump())

    store.save_cards(paper_id, payload)
    return {"cards": payload, "generated": True}


def _save_relationship_cards(search_id: str, cards: list[Flashcard]) -> list[dict]:
    """Relationship cards live in their source paper's card file, alongside its
    own definition/concept/result/critique cards — merged in, never overwritten."""
    by_paper: dict[str, list[Flashcard]] = {}
    for card in cards:
        by_paper.setdefault(card.paper_id, []).append(card)

    saved: list[dict] = []
    for paper_id, new_cards in by_paper.items():
        existing = store.load_cards(paper_id)
        previous = {c["id"]: c for c in existing}
        # Keep everything except this search's own relationship cards, which
        # are about to be replaced with a fresh (possibly changed) batch.
        # The old id scheme ("rel:{search_id}:...") didn't carry the source
        # paper id first, so grading couldn't find the card by id; matching it
        # too here clears out any of those left behind by that bug.
        prefix = f"{paper_id}:rel:{search_id}:"
        old_prefix = f"rel:{search_id}:"
        payload = [
            c
            for c in existing
            if not c.get("id", "").startswith(prefix)
            and not c.get("id", "").startswith(old_prefix)
        ]
        for card in new_cards:
            old = previous.get(card.id)
            if old and old.get("question") == card.question:
                card.due = old.get("due", "")
                card.interval = old.get("interval", 0)
                card.ease = old.get("ease", 2.5)
                card.reps = old.get("reps", 0)
                card.lapses = old.get("lapses", 0)
                card.last_score = old.get("last_score")
            dumped = card.model_dump()
            payload.append(dumped)
            saved.append(dumped)
        store.save_cards(paper_id, payload)
    return saved


@app.post("/api/searches/{search_id}/relationship-cards")
def make_relationship_cards(search_id: str):
    """Cross-paper cards from this search's relationship edges — instant, no LLM call."""
    search = store.load_search(search_id)
    if search is None:
        raise HTTPException(404, "Search not found.")
    cards = relationship_cards(search, _papers_by_id())
    saved = _save_relationship_cards(search_id, cards)
    return {"cards": saved, "generated": len(saved)}


@app.get("/api/cards")
def list_cards(due_only: bool = False, paper_id: str | None = None):
    raw = store.load_cards(paper_id) if paper_id else store.all_cards()
    cards = [Flashcard(**item) for item in raw]
    due = [card for card in cards if is_due(card)]
    selected = due if due_only else cards
    return {
        "cards": [card.model_dump() for card in selected],
        "total": len(cards),
        "due": len(due),
        "papers": store.card_paper_ids(),
    }


@app.post("/api/cards/anki")
def cards_anki(request: PaperIdsRequest):
    raw = (
        [card for pid in request.paper_ids for card in store.load_cards(pid)]
        if request.paper_ids
        else store.all_cards()
    )
    if not raw:
        raise HTTPException(400, "No cards yet — generate some first.")
    cards = [Flashcard(**item) for item in raw]
    return Response(
        content=to_anki_tsv(cards, _papers_by_id()),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": 'attachment; filename="research-copilot-cards.txt"'},
    )


class GradeRequest(BaseModel):
    card_id: str
    answer: str


@app.post("/api/cards/grade")
async def grade_card(request: GradeRequest):
    answer = request.answer.strip()
    if not answer:
        raise HTTPException(400, "Answer is empty.")
    paper_id = request.card_id.split(":")[0]
    raw = next(
        (c for c in store.load_cards(paper_id) if c.get("id") == request.card_id), None
    )
    if raw is None:
        raise HTTPException(404, "Card not found.")
    card = Flashcard(**raw)
    paper = _papers_by_id().get(card.paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found in your library.")

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])
    try:
        grade = await grade_answer(paper, card, answer)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc

    updated = schedule(card, grade.verdict, grade.score)
    store.update_card(updated.model_dump())
    return {"grade": grade.model_dump(), "card": updated.model_dump()}


@app.post("/api/searches/{search_id}/digest")
async def run_digest(search_id: str, max_new: int = 6):
    search = store.load_search(search_id)
    if search is None:
        raise HTTPException(404, "Search not found.")

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])

    query = search.get("query") or ""
    queries = await expand_queries(query)
    try:
        candidates = await asyncio.to_thread(search_arxiv, queries, 25, 60, True)
    except ArxivUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    known = {p.id for p in store.all_papers()}
    fresh = [paper for paper in candidates if paper.id not in known][:max_new]

    if not fresh:
        digest = Digest(
            search_id=search_id,
            query=query,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            checked_count=len(candidates),
            new_paper_ids=[],
            headline="No new papers since your last check.",
            summary=(
                f"Checked {len(candidates)} candidates on arXiv for “{query}”. "
                "Everything relevant is already in your library."
            ),
            highlights=[],
        )
        store.save_digest(search_id, digest.model_dump())
        return digest.model_dump()

    try:
        extractions = await extract_many(fresh, store.get_cached_extractions([p.id for p in fresh]), lambda *_: None)
        digest = await build_digest(search, fresh, extractions, len(candidates))
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc

    # Fold the new papers into the library so the map can grow with them.
    store.merge_search_results(query, fresh, extractions)
    store.save_digest(search_id, digest.model_dump())
    return digest.model_dump()


@app.get("/api/searches/{search_id}/digests")
def get_digests(search_id: str):
    return {"digests": store.load_digests(search_id)}


class ChatRequest(BaseModel):
    question: str


@app.post("/api/papers/{paper_id:path}/chat")
async def chat_with_paper(paper_id: str, request: ChatRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(400, "Question is empty.")
    if len(question) > 500:
        raise HTTPException(400, "Question is too long (500 chars max).")

    papers = {p.id: p for p in store.all_papers()}
    paper = papers.get(paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found in your library.")

    index = store.load_index(paper_id)
    if not index:
        raise HTTPException(
            400, "Read the full paper first — chat needs the indexed full text."
        )
    try:
        answer = await chat_with_paper_impl(paper, question, index)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return answer.model_dump()
