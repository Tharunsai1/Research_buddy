"""Research Copilot backend — FastAPI app."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")  # before importing modules that read env

from fastapi import FastAPI, File, HTTPException, Response, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import artifacts  # noqa: E402
import citations  # noqa: E402
import insights  # noqa: E402
import library_search  # noqa: E402
import llm  # noqa: E402
import openrouter  # noqa: E402
import pdf_ingest  # noqa: E402
import prefetch  # noqa: E402
import scheduler  # noqa: E402
import store  # noqa: E402
from arxiv_client import ArxivUnavailable, fetch_by_id, search_arxiv  # noqa: E402
from chat import answer_question as chat_with_paper_impl  # noqa: E402
from chat import build_index  # noqa: E402
from deepdive import run_deep_dive  # noqa: E402
from extract import extract_many, extract_paper  # noqa: E402
from fulltext import load_fulltext  # noqa: E402
from appraisal import run_appraisal  # noqa: E402
from learning import build_digest  # noqa: E402
from models import (  # noqa: E402
    Digest,
    Highlight,
    HighlightIn,
    MatrixRow,
    Paper,
)
from synthesize import expand_queries, update_global_map  # noqa: E402
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


# Without this the root logger has no handler and sits at WARNING, so every
# INFO line the background workers emit is dropped on the floor. They are the
# only trace those workers leave — nothing they do is a request the reader can
# watch — so losing them means a digest or a warm-up that quietly declined to
# run looks identical to one that never triggered. uvicorn's own loggers carry
# their own handlers and don't propagate, so they are unaffected.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

_scheduler_log = logging.getLogger("research-copilot.scheduler")
_appraisal_log = logging.getLogger("research-copilot.appraisal")
_results_log = logging.getLogger("research-copilot.results")

# How often to check whether any followed search is due — not the digest
# interval itself (scheduler.DIGEST_INTERVAL_DAYS, ~weekly). Checking hourly
# costs nothing (a no-op when nothing is due) and means a search becomes
# current again within an hour of the backend coming back up, rather than
# waiting for the next weekly boundary that already passed while it was off.
DIGEST_CHECK_INTERVAL = int(os.getenv("RC_DIGEST_CHECK_INTERVAL", str(60 * 60)))


async def _run_due_digests() -> None:
    """One scheduler tick: refresh every followed search that's due.

    This can only run while the backend process is alive — see scheduler.py.
    Digest runs cost real LLM calls, so this respects the same OpenRouter
    daily cap the model picker already warns about, and silently skips a
    tick entirely rather than partially running through the cap.
    """
    followed = store.followed_searches()
    if not followed:
        return

    status = await llm.provider_status()
    if not status["ready"]:
        return
    if status["provider"] == "openrouter" and openrouter.daily_usage()["near_cap"]:
        _scheduler_log.info("skipping auto-digest tick: near the daily OpenRouter cap")
        return

    for search in followed:
        digests = store.load_digests(search["id"])
        latest = digests[0] if digests else None
        if not scheduler.is_digest_due(search, latest):
            continue
        try:
            await _build_and_save_digest(search)
        except Exception:
            _scheduler_log.exception("auto-digest failed for search %s", search["id"])


async def _digest_scheduler_loop() -> None:
    while True:
        try:
            await _run_due_digests()
        except asyncio.CancelledError:
            raise
        except Exception:
            _scheduler_log.exception("digest scheduler tick failed")
        await asyncio.sleep(DIGEST_CHECK_INTERVAL)


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
    scheduler_task = asyncio.create_task(_digest_scheduler_loop())
    yield
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass


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


@app.get("/api/library/search")
async def search_library(q: str, limit: int = 10):
    """Semantic search across every paper collected, not just one search's
    results — "which of my papers discussed KV-cache compression?" without
    remembering which search turned it up."""
    papers = {p.id: p for p in store.all_papers()}
    extractions = store.all_extractions()
    try:
        results = await library_search.search(q, papers, extractions, limit=limit)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {
        "query": q,
        "results": [
            {**hit, "paper": papers[hit["paper_id"]].model_dump()}
            for hit in results
            if hit["paper_id"] in papers
        ],
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


MAX_UPLOAD_BYTES = 40 * 1024 * 1024  # 40MB — comfortably above a typical paper


@app.post("/api/papers/upload")
async def upload_paper(file: UploadFile = File(...)):
    """A paper that isn't on arXiv — a camera-ready, something emailed by a
    professor, a workshop paper never posted. Extracted text flows through
    the exact same extraction, clustering, deep-dive and flashcard machinery
    as an arXiv result; only where the full text is fetched from differs
    (see the upload check inside _run_deep_dive).
    """
    if file.content_type not in ("application/pdf", "application/octet-stream", None):
        raise HTTPException(400, "Only PDF files are supported.")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File is too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)}MB).")
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])

    try:
        paper, full = await asyncio.to_thread(pdf_ingest.extract_pdf, data, file.filename or "")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Could not read this PDF: {exc}") from exc

    if any(p.id == paper.id for p in store.all_papers()):
        return {"added": False, "reason": "This exact file is already in your library.", "paper_id": paper.id}

    try:
        extraction = await extract_paper(paper)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc

    store.save_upload(paper.id, data)
    store.merge_search_results("Uploaded", [paper], {paper.id: extraction})

    # Place it in the global map the same way a real search's results are —
    # incremental past FULL_RECLUSTER_MAX, so this stays cheap regardless of
    # library size.
    snapshot = store.collection_snapshot()
    prior_searches = len(snapshot["searches"])
    if prior_searches == 0:
        store.set_global_map(clusters=[{"name": "Uploaded", "paper_ids": [paper.id]}], bridge_edges=[])
    else:
        global_map = await update_global_map(
            store.all_papers(),
            store.all_extractions(),
            store.paper_search_map(),
            store.existing_map(),
            paper.title,
        )
        store.set_global_map(**global_map)

    return {
        "added": True,
        "paper_id": paper.id,
        "title": paper.title,
        "word_count": full.total_words,
    }


@app.get("/api/papers/{paper_id:path}/pdf")
def get_uploaded_pdf(paper_id: str):
    data = store.load_upload(paper_id)
    if data is None:
        raise HTTPException(404, "No uploaded PDF stored for this paper.")
    return Response(content=data, media_type="application/pdf")


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
    """Overview + clusters + reading order + appraisal progress as one .md file."""
    search = store.load_search(search_id)
    if search is None:
        raise HTTPException(404, "Search not found.")

    paper_ids = list(search.get("paper_ids") or [])
    done = [pid for pid in paper_ids if store.load_appraisal(pid)]
    appraisal_stats = {
        "total": len(paper_ids),
        "appraised": len(done),
        "remaining": len(paper_ids) - len(done),
    }

    content = build_field_report(
        search, _papers_by_id(), appraisal_stats, store.all_notes()
    )
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

        # An uploaded paper's text already lives on disk — no arXiv fetch
        # applies (there's nothing to fetch it from). Every stage after this
        # one operates on the same FullText shape regardless of source.
        upload_bytes = store.load_upload(paper.id)
        if upload_bytes is not None:
            stage.detail = "Reading the uploaded PDF…"
            full = await asyncio.to_thread(
                pdf_ingest.fulltext_from_pdf, paper.id, upload_bytes, paper.abstract
            )
            if full is None:
                raise RuntimeError(
                    "Could not extract enough readable text from this PDF to read it "
                    "in depth (it may be mostly scanned images). The summary, "
                    "extraction and flashcards built from the abstract still work."
                )
        else:
            stage.detail = "Fetching full text from arXiv…"
            full = await asyncio.to_thread(load_fulltext, paper.id)
            if full is None:
                # Deliberately refuse rather than read whatever arXiv served. For a
                # paper with no HTML rendering arXiv returns the /abs/ landing page,
                # and summarising that produces a confident-looking deep dive built
                # from an abstract — worse than no deep dive at all.
                raise RuntimeError(
                    "arXiv has no HTML full text for this paper, only the abstract page "
                    "(papers before ~2023 are often PDF-only), so there is nothing to read "
                    "in depth. The summary, extraction and flashcards built from the "
                    "abstract still work — open the PDF for the full paper."
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


# ---------------------------------------------------------------------------
# Prefetch — warming a paper's deep read before it is clicked
# ---------------------------------------------------------------------------

_prefetch_log = logging.getLogger("research-copilot.prefetch")
_prefetch_queue: list[str] = []
_prefetch_failed: set[str] = set()
_prefetch_task: asyncio.Task | None = None
# The paper being warmed right now. Separate from the queue because a paper is
# taken off the queue before its read starts, so the queue alone cannot say
# what is in progress.
_prefetch_current: str | None = None

# How long to wait before re-checking whether the reader's own read has
# finished. Short enough that a warm-up starts promptly after it does.
_PREFETCH_POLL_SECONDS = 2.0


def _deep_job_running() -> bool:
    return any(job.status == "running" for job in store.DEEP_JOBS.values())


async def _drain_prefetch_queue() -> None:
    """Warm queued papers one at a time, never alongside a read in progress.

    Serial on purpose. run_deep_dive already fans a single paper out to
    several concurrent calls, so warming a second paper next to the one the
    reader is watching would slow that read down — the exact opposite of what
    warming is for. The queue therefore yields to any running job, including
    a read the reader started by hand, and only then takes its turn.
    """
    global _prefetch_current
    while True:
        deep_read = set(store.deep_dive_ids())
        paper_id = prefetch.next_to_warm(
            _prefetch_queue, deep_read=deep_read, failed=_prefetch_failed
        )
        if paper_id is None:
            _prefetch_queue.clear()
            return

        while _deep_job_running():
            await asyncio.sleep(_PREFETCH_POLL_SECONDS)

        status = await llm.provider_status()
        usage = openrouter.daily_usage() if status["provider"] == "openrouter" else None
        hold = prefetch.should_hold(status, usage)
        if hold:
            # Leave the queue intact: the reader may switch engines or the cap
            # may roll over, and the next request restarts the worker.
            _prefetch_log.info("holding off on warming %s — %s", paper_id, hold)
            return

        if _deep_job_running():
            # provider_status() is a network call; the reader can start a read
            # of their own while it is in flight. Re-check rather than race it.
            continue

        _prefetch_queue.remove(paper_id)
        paper = next((p for p in store.all_papers() if p.id == paper_id), None)
        if paper is None:  # removed between queueing and running
            continue

        job = store.create_deep_job(paper_id)
        _prefetch_log.info("warming %s", paper_id)
        _prefetch_current = paper_id
        try:
            await _run_deep_dive(job, paper)
        finally:
            # Cleared even if the read raises, or the badge would sit on
            # "reading now" for a paper nothing is working on.
            _prefetch_current = None
        if job.status == "error":
            # Almost always a paper arXiv only publishes as PDF, which will
            # fail identically forever — remember it so the queue moves on.
            _prefetch_failed.add(paper_id)
            _prefetch_log.info("could not warm %s — %s", paper_id, job.error)


class PrefetchRequest(BaseModel):
    reading_order: list[str]
    after_paper_id: str | None = None


@app.post("/api/prefetch")
async def request_prefetch(request: PrefetchRequest):
    """Warm the papers the reader is most likely to open next.

    Best-effort and advisory: the caller says where the reader is, the policy
    in prefetch.py decides what that makes worth warming, and the queue drains
    in the background. Nothing here blocks, and a paper already read, already
    running or already queued is silently skipped.
    """
    global _prefetch_task

    wanted = prefetch.plan(request.reading_order[:500], request.after_paper_id)
    known = {p.id for p in store.all_papers()}
    wanted = [paper_id for paper_id in wanted if paper_id in known]

    _prefetch_queue[:] = prefetch.enqueue(
        _prefetch_queue,
        wanted,
        deep_read=set(store.deep_dive_ids()),
        failed=_prefetch_failed,
    )
    if _prefetch_queue and (_prefetch_task is None or _prefetch_task.done()):
        _prefetch_task = asyncio.create_task(_drain_prefetch_queue())
    return _prefetch_state()


def _prefetch_state() -> dict[str, Any]:
    return {"warming": _prefetch_current, "queued": list(_prefetch_queue)}


@app.get("/api/prefetch")
def prefetch_status():
    """What the warm-up queue is doing, so the paper list can show it.

    Read-only and cheap — no disk, no model — because the list polls it while
    it is open.
    """
    return _prefetch_state()


# ---------------------------------------------------------------------------
# Highlights — passages the reader marked
# ---------------------------------------------------------------------------

@app.get("/api/highlights")
def list_all_highlights():
    """Every highlight in the library, backing the library-wide view."""
    return {"highlights": store.all_highlights()}


@app.get("/api/papers/{paper_id:path}/highlights")
def list_highlights(paper_id: str):
    return {"highlights": store.load_highlights(paper_id)}


@app.post("/api/papers/{paper_id:path}/highlights")
def add_highlight(paper_id: str, request: HighlightIn):
    if paper_id not in {p.id for p in store.all_papers()}:
        raise HTTPException(404, "Paper not found in your library.")
    quote = request.quote.strip()
    if not quote:
        raise HTTPException(400, "Nothing was selected.")
    if len(quote) > 2000:
        raise HTTPException(400, "That passage is too long to mark (2,000 chars max).")

    highlight = Highlight(
        **{**request.model_dump(), "quote": quote},
        id=f"h_{uuid.uuid4().hex[:10]}",
        paper_id=paper_id,
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    highlights = store.load_highlights(paper_id)
    highlights.append(highlight.model_dump())
    store.save_highlights(paper_id, highlights)
    return highlight.model_dump()


@app.delete("/api/papers/{paper_id:path}/highlights/{highlight_id}")
def remove_highlight(paper_id: str, highlight_id: str):
    highlights = store.load_highlights(paper_id)
    kept = [h for h in highlights if h.get("id") != highlight_id]
    if len(kept) == len(highlights):
        raise HTTPException(404, "No such highlight.")
    store.save_highlights(paper_id, kept)
    return {"removed": highlight_id}


class NoteRequest(BaseModel):
    text: str


@app.get("/api/papers/{paper_id:path}/note")
def get_note(paper_id: str):
    """The reader's own free-text note on a paper — separate from anything
    AI-generated, and the one place in the app where their own thinking lives."""
    return {"paper_id": paper_id, "text": store.get_note(paper_id)}


@app.post("/api/papers/{paper_id:path}/note")
def set_note(paper_id: str, request: NoteRequest):
    if len(request.text) > 20_000:
        raise HTTPException(400, "Note is too long (20,000 characters max).")
    saved = store.set_note(paper_id, request.text)
    return {"paper_id": paper_id, "text": saved}


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
    failed: list[dict] = []
    for paper in papers:
        cached = None if refresh else store.load_matrix_row(paper.id)
        if cached is not None:
            rows.append(cached)
            continue
        if not status["ready"]:
            raise HTTPException(400, status["detail"])
        # Same rule as the results ledger: one paper must not cost the others.
        # A row is an LLM call, and a single bad reply used to discard every
        # row already built in the request — 8 papers' work lost to one, with
        # nothing on screen saying which paper or why.
        try:
            row = await build_matrix_row(paper, extractions.get(paper.id))
        except Exception as exc:  # noqa: BLE001 - one paper's failure is data, not a crash
            _results_log.exception("matrix row failed for %s", paper.id)
            failed.append({"paper_id": paper.id, "title": paper.title, "reason": str(exc)[:300]})
            continue
        store.save_matrix_row(paper.id, row.model_dump())
        rows.append(row.model_dump())

    if failed and not rows:
        raise HTTPException(502, failed[0]["reason"] or "Matrix extraction failed.")
    return {"rows": rows, "failed": failed}


# ---------------------------------------------------------------------------
# Code / reproducibility signals — pure text scan, no LLM, no network
# ---------------------------------------------------------------------------

def _scan_text_for(paper_id: str, paper: Paper) -> tuple[str, bool]:
    """Best text available for artifact scanning, and whether it is full text.

    Prefers the chat index (real full text) over the deep dive's section
    summaries, because a repo link usually lives in a footnote or an
    availability statement that a summary drops.
    """
    chunks = store.load_index(paper_id)
    if chunks:
        return " ".join(c.get("text", "") for c in chunks), True
    parts = [paper.abstract or "", paper.comment or ""]
    deep = store.load_deep_dive(paper_id)
    if deep:
        parts.append(deep.get("results_detail", "") or "")
        for section in deep.get("sections", []) or []:
            parts.append(section.get("summary", "") or "")
            parts.extend(section.get("key_points") or [])
    return " ".join(p for p in parts if p), False


@app.get("/api/library/artifacts")
def library_artifacts():
    """Code availability + reproducibility signals for every paper.

    Free and instant (regex over text already on disk), so this is computed
    on request rather than cached — no staleness to manage.
    """
    papers = _papers_by_id()
    out = []
    for paper_id, paper in papers.items():
        text, full = _scan_text_for(paper_id, paper)
        assessment = artifacts.assess(text, scanned_full_text=full)
        out.append(
            {
                "paper_id": paper_id,
                "title": paper.title,
                "published": paper.published,
                **assessment,
            }
        )
    out.sort(key=lambda row: (not row["has_code"], -row["signal_count"], row["title"]))
    return {"papers": out, "labels": artifacts.SIGNAL_LABELS}


# ---------------------------------------------------------------------------
# Results scoreboard
# ---------------------------------------------------------------------------

@app.post("/api/results")
async def build_results(request: PaperIdsRequest, refresh: bool = False):
    """Extract reported numbers for the given papers (cached per paper)."""
    if not request.paper_ids:
        raise HTTPException(400, "No papers selected.")
    if len(request.paper_ids) > 30:
        raise HTTPException(400, "Select 30 papers or fewer.")
    papers = _require_papers(request.paper_ids)
    extractions = store.all_extractions()

    status = await llm.provider_status()
    rows: list[dict] = []
    failed: list[dict] = []
    for paper in papers:
        cached = None if refresh else store.load_results(paper.id)
        if cached is not None:
            rows.extend(cached)
            continue
        if not status["ready"]:
            raise HTTPException(400, status["detail"])
        # One paper must not cost the others. Extraction is a per-paper LLM
        # call over a batch of up to 30, so a single bad reply used to discard
        # every row already extracted in the same request and surface as one
        # opaque failure for the whole scoreboard. Report the casualties
        # instead and keep what worked; each success is cached as it lands, so
        # a retry only re-runs what actually failed.
        try:
            extracted = await insights.extract_results(paper, extractions.get(paper.id))
        except Exception as exc:  # noqa: BLE001 - one paper's failure is data, not a crash
            _results_log.exception("results extraction failed for %s", paper.id)
            failed.append({"paper_id": paper.id, "title": paper.title, "reason": str(exc)[:300]})
            continue
        dumped = [row.model_dump() for row in extracted]
        store.save_results(paper.id, dumped)
        rows.extend(dumped)

    # Every paper failing is a real failure, not a partial result — say so
    # rather than handing back an empty table that looks like "no numbers".
    if failed and not rows:
        raise HTTPException(502, failed[0]["reason"] or "Results extraction failed.")
    return {"rows": rows, "failed": failed}


@app.get("/api/results")
def get_results():
    """Every already-extracted result row across the library."""
    rows: list[dict] = []
    for paper_rows in store.all_results().values():
        rows.extend(paper_rows)
    return {"rows": rows}


# ---------------------------------------------------------------------------
# Gap finder
# ---------------------------------------------------------------------------

@app.get("/api/library/gaps")
def get_gaps():
    return {"report": store.load_gaps()}


@app.post("/api/library/gaps")
async def build_gaps():
    """Propose unexplored intersections across the whole library."""
    papers = store.all_papers()
    if len(papers) < 4:
        raise HTTPException(400, "Collect at least 4 papers first.")

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])

    snapshot = store.collection_snapshot()
    searches = [s for s in (store.load_search(m["id"]) for m in snapshot["searches"]) if s]
    try:
        report = await insights.find_gaps(papers, store.all_extractions(), searches)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    store.save_gaps(report.model_dump())
    return {"report": report.model_dump()}


# ---------------------------------------------------------------------------
# Simulated peer review
# ---------------------------------------------------------------------------

@app.get("/api/papers/{paper_id:path}/review")
def get_review(paper_id: str):
    return {"review": store.load_review(paper_id)}


@app.post("/api/papers/{paper_id:path}/review")
async def build_review(paper_id: str, refresh: bool = False):
    papers = _papers_by_id()
    paper = papers.get(paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found.")

    if not refresh:
        cached = store.load_review(paper_id)
        if cached is not None:
            return {"review": cached}

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])
    try:
        review = await insights.review_paper(paper, store.all_extractions().get(paper_id))
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    store.save_review(paper_id, review.model_dump())
    return {"review": review.model_dump()}


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
# Critical appraisal: one paper at a time, against the checklist
# ---------------------------------------------------------------------------

@app.get("/api/papers/{paper_id:path}/appraisal")
def get_appraisal(paper_id: str):
    saved = store.load_appraisal(paper_id)
    if saved is None:
        raise HTTPException(404, "This paper has not been appraised yet.")
    return saved


@app.post("/api/papers/{paper_id:path}/appraisal")
async def make_appraisal(paper_id: str, refresh: bool = False):
    paper = _papers_by_id().get(paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found in your library.")

    existing = store.load_appraisal(paper_id)
    if existing and not refresh:
        return existing

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])

    # Prefer the full text when the paper has already been deep-read; the
    # appraisal records which it used either way, so an abstract-only pass is
    # never mistaken for a complete one. load_fulltext is synchronous and does
    # network I/O, so it goes to a thread rather than blocking the loop.
    full = None
    if store.load_deep_dive(paper_id) is not None:
        try:
            full = await asyncio.to_thread(load_fulltext, paper.id)
        except Exception:
            # Falling back to the abstract is survivable, but doing it silently
            # is not: the appraisal would look complete and answer half the
            # checklist with "not reported" for no visible reason.
            _appraisal_log.exception("full text unavailable for %s", paper_id)
            full = None

    # The extraction already classified this paper; the checklist swaps in
    # questions that suit its kind rather than asking a survey for its
    # test-set accuracy.
    extraction = store.all_extractions().get(paper_id)
    paper_type = getattr(extraction, "paper_type", None) or "method"

    try:
        result = await run_appraisal(paper, full, paper_type)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc

    payload = result.model_dump()
    store.save_appraisal(paper_id, payload)
    return payload


@app.delete("/api/papers/{paper_id:path}/appraisal")
def drop_appraisal(paper_id: str):
    store.delete_appraisal(paper_id)
    return {"ok": True}


@app.get("/api/appraisals")
def appraisal_progress(search_id: str | None = None):
    """Which papers are done — drives the queue. Scoped to one search when
    asked, since 'what is left to read' means this search's papers, not the
    whole accumulated library."""
    done = set(store.appraised_paper_ids())
    if search_id:
        search = store.load_search(search_id)
        if search is None:
            raise HTTPException(404, "Search not found.")
        ids = list(search.get("paper_ids") or [])
    else:
        ids = [p.id for p in store.all_papers()]
    return {
        "appraised": [pid for pid in ids if pid in done],
        "remaining": [pid for pid in ids if pid not in done],
        "total": len(ids),
    }


# ---------------------------------------------------------------------------
# Field digest: what is new in a followed search
# ---------------------------------------------------------------------------

async def _build_and_save_digest(search: dict, max_new: int = 6) -> Digest:
    """The digest logic itself, shared by the on-demand endpoint and the
    background scheduler for followed searches — one place that decides what
    a digest run does, so a manual check and an automatic one behave
    identically."""
    search_id = search["id"]
    query = search.get("query") or ""
    queries = await expand_queries(query)
    candidates = await asyncio.to_thread(search_arxiv, queries, 25, 60, True)
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
        return digest

    extractions = await extract_many(
        fresh, store.get_cached_extractions([p.id for p in fresh]), lambda *_: None
    )
    digest = await build_digest(search, fresh, extractions, len(candidates))

    # Fold the new papers into the library, then actually place them on the
    # global map. merge_search_results only records the papers — without the
    # update below every digest silently added papers that existed in the
    # library but appeared nowhere on the reading map, so the header count and
    # the map disagreed. Mirrors the upload path.
    store.merge_search_results(query, fresh, extractions)
    try:
        global_map = await update_global_map(
            store.all_papers(),
            store.all_extractions(),
            store.paper_search_map(),
            store.existing_map(),
            search.get("title") or query,
        )
        store.set_global_map(**global_map)
    except llm.LLMError:
        # The digest itself is already worth saving; an unplaced paper is
        # recoverable (the next search or upload re-clusters), a lost digest
        # is not.
        _scheduler_log.exception("could not place new digest papers on the map")

    store.save_digest(search_id, digest.model_dump())
    return digest


@app.post("/api/searches/{search_id}/digest")
async def run_digest(search_id: str, max_new: int = 6):
    search = store.load_search(search_id)
    if search is None:
        raise HTTPException(404, "Search not found.")

    status = await llm.provider_status()
    if not status["ready"]:
        raise HTTPException(400, status["detail"])

    try:
        digest = await _build_and_save_digest(search, max_new)
    except ArxivUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return digest.model_dump()


@app.get("/api/searches/{search_id}/digests")
def get_digests(search_id: str):
    return {"digests": store.load_digests(search_id)}


class FollowRequest(BaseModel):
    followed: bool


@app.post("/api/searches/{search_id}/follow")
def set_followed(search_id: str, request: FollowRequest):
    """Mark a search to auto-refresh its field digest roughly weekly, while
    the backend process is running (see the scheduler in lifespan) — there is
    no external cron here, so "weekly" means "next time a week has passed
    and the backend happens to be up," not a guaranteed wall-clock trigger.
    """
    search = store.load_search(search_id)
    if search is None:
        raise HTTPException(404, "Search not found.")
    search["followed"] = request.followed
    store.save_search(search)
    return {"search_id": search_id, "followed": request.followed}


class ChatRequest(BaseModel):
    question: str
    anchor: str | None = None  # a passage the reader highlighted before asking


@app.post("/api/papers/{paper_id:path}/chat")
async def chat_with_paper(paper_id: str, request: ChatRequest):
    question = request.question.strip()
    if not question:
        raise HTTPException(400, "Question is empty.")
    if len(question) > 500:
        raise HTTPException(400, "Question is too long (500 chars max).")
    anchor = (request.anchor or "").strip() or None
    if anchor and len(anchor) > 2000:
        raise HTTPException(400, "Highlighted passage is too long (2,000 chars max).")

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
        answer = await chat_with_paper_impl(paper, question, index, anchor=anchor)
    except llm.LLMError as exc:
        raise HTTPException(502, str(exc)) from exc
    return answer.model_dump()

