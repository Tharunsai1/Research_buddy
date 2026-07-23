"""Stage 2 — rerank candidates: cross-encoder scores, then an LLM shortlist."""

from __future__ import annotations

import asyncio
import math
import os
import threading

from llm import parse_json
from models import Paper, Shortlist

_ce = None
_ce_status = "cold"  # cold | loading | ready | unavailable
_ce_lock = threading.Lock()
_ce_attempts = 0
_MAX_CE_ATTEMPTS = 3


def ce_status() -> str:
    return _ce_status


def _load_ce():
    """Blocking; import + model load can take ~10s on first call.

    A failed load is retried on later calls rather than latching: the first
    attempt happens at startup, when a slow or rate-limited model download
    would otherwise disable reranking for the life of the process.
    """
    global _ce, _ce_status, _ce_attempts
    with _ce_lock:
        if _ce is not None:
            return _ce
        if os.getenv("RC_DISABLE_CE") == "1":
            _ce_status = "unavailable"
            return None
        if _ce_attempts >= _MAX_CE_ATTEMPTS:
            return None
        _ce_attempts += 1
        _ce_status = "loading"
        try:
            from sentence_transformers import CrossEncoder

            model_name = os.getenv("RC_CROSS_ENCODER", "cross-encoder/ms-marco-MiniLM-L-6-v2")
            _ce = CrossEncoder(model_name)
            _ce_status = "ready"
        except Exception:
            _ce_status = (
                "unavailable" if _ce_attempts >= _MAX_CE_ATTEMPTS else "retry pending"
            )
            _ce = None
        return _ce


def warm_cross_encoder() -> None:
    """Fire-and-forget warmup at server startup."""
    threading.Thread(target=_load_ce, daemon=True).start()


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


async def cross_encoder_rank(query: str, papers: list[Paper]) -> list[Paper] | None:
    """Score (query, title+abstract) pairs; returns papers sorted by relevance, or None."""
    ce = await asyncio.to_thread(_load_ce)
    if ce is None:
        return None
    pairs = [(query, f"{p.title}. {p.abstract[:1500]}") for p in papers]
    scores = await asyncio.to_thread(ce.predict, pairs)
    for paper, score in zip(papers, scores):
        paper.relevance = round(_sigmoid(float(score)), 4)
    return sorted(papers, key=lambda p: p.relevance or 0.0, reverse=True)


def _candidate_lines(papers: list[Paper], snippet: int = 350) -> str:
    return "\n".join(
        f"[{i}] {p.title} ({p.published[:4]})\n    {p.abstract[:snippet]}"
        for i, p in enumerate(papers, start=1)
    )


async def llm_shortlist(topic: str, candidates: list[Paper], k: int) -> list[Paper]:
    """Pick the final k papers from the candidate pool, best first."""
    result = await parse_json(
        Shortlist,
        system=(
            "You curate reading lists for machine-learning researchers. "
            "Given a research topic and candidate arXiv papers, select the papers that "
            "together best map the field: directly relevant, complementary rather than "
            "redundant, mixing foundational and recent work. Return their indices, most "
            "relevant first."
        ),
        user=(
            f"Research topic: {topic}\n\n"
            f"Select exactly {min(k, len(candidates))} papers from these candidates:\n\n"
            f"{_candidate_lines(candidates)}"
        ),
        max_tokens=1000,
    )
    picked: list[Paper] = []
    seen: set[int] = set()
    for idx in result.selected:
        if 1 <= idx <= len(candidates) and idx not in seen:
            seen.add(idx)
            picked.append(candidates[idx - 1])
        if len(picked) == k:
            break
    # Top up from cross-encoder order if the model under-selected.
    for paper in candidates:
        if len(picked) >= k:
            break
        if paper not in picked:
            picked.append(paper)
    return picked[:k]
