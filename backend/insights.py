"""Three reader-facing analyses that sit on top of the existing pipeline.

  * results  — every number a paper reports, as a comparable table
  * gaps     — unexplored intersections across the whole library
  * review   — a conference-style peer review of one paper

All three prefer a paper's full-text deep dive and fall back to the abstract,
matching research.py. Each is on-demand and cached by the caller: they cost
real LLM calls, and nothing here should run on a timer.
"""

from __future__ import annotations

import re
from datetime import datetime

import meta_guard
import store
from llm import parse_json
from models import (
    Extraction,
    GapReport,
    GapsOut,
    Paper,
    PeerReview,
    PeerReviewOut,
    ResearchGap,
    ResultRow,
    ResultsOut,
)


def _paper_context(paper: Paper, extraction: Extraction | None) -> tuple[str, bool]:
    """Richest available text for a paper, plus whether it is full text."""
    deep = store.load_deep_dive(paper.id)
    header = f"Title: {paper.title}\nPublished: {paper.published}\nAbstract: {paper.abstract}"
    if deep:
        sections = "\n".join(
            f"[{s['title']}] {s['summary']} " + " ".join(s.get("key_points") or [])
            for s in deep.get("sections", [])
        )
        body = (
            f"{header}\n\nFull-paper synthesis: {deep.get('deep_summary', '')}\n"
            f"Results detail: {deep.get('results_detail', '')}\n\nSections:\n{sections}"
        )
        return body[:14000], True
    if extraction:
        return (
            f"{header}\n\nSummary: {extraction.tldr}\nMethod: {extraction.method}\n"
            f"Results: {extraction.key_results}"
        ), False
    return header, False


# ---------------------------------------------------------------------------
# 1. Results ledger
# ---------------------------------------------------------------------------

# Metric names that describe how a model was *configured* rather than how it
# *performed*. Asking the model not to emit these is not enough — it reliably
# returns "Adam beta1 = 0.9" as a result row anyway — so they are dropped in
# code. Measured costs (training time, FLOPs, step time, throughput) are kept:
# papers genuinely compete on those, unlike an optimizer constant.
_CONFIG_METRIC = re.compile(
    r"""
    adam | \bbeta\s*[12]\b | β | epsilon | \blr\b | learning[\s-]?rate | warm[\s-]?up
    | dropout | label[\s-]?smooth | weight[\s-]?decay | batch[\s-]?size | optimi[sz]er
    | momentum | \bseed\b | training[\s-]?steps | \bepochs?\b | num[\s_-]?layers
    | d_model | hidden[\s-]?(?:size|dim) | vocab(?:ulary)?[\s-]?size | \bheads?\b
    | temperature | top[\s-]?[kp]\b | beam[\s-]?size
    """,
    re.IGNORECASE | re.VERBOSE,
)


def is_config_metric(metric: str) -> bool:
    """True for a hyperparameter/config value masquerading as a result."""
    return bool(_CONFIG_METRIC.search(metric or ""))


async def extract_results(paper: Paper, extraction: Extraction | None) -> list[ResultRow]:
    """Pull every reported *evaluation* number out of one paper.

    Baselines are kept alongside the paper's own numbers on purpose: the whole
    point of a cross-paper table is spotting when two papers report different
    values for the *same* baseline, which is invisible if only headline
    results are stored.
    """
    context, _from_fulltext = _paper_context(paper, extraction)
    result = await parse_json(
        ResultsOut,
        system=(
            "You extract reported experimental results from a machine-learning paper "
            "into a table. Copy every number exactly as printed — never compute, "
            "convert, round, or estimate a value, and never invent a row.\n\n"
            "Include ONLY evaluation outcomes: scores on a dataset or benchmark "
            "(accuracy, BLEU, F1, EM, win rate, perplexity...) and measured costs "
            "(training time, FLOPs, throughput, latency).\n\n"
            "EXCLUDE model and training configuration — optimizer settings, Adam "
            "betas, learning rate, warmup, dropout, batch size, number of epochs or "
            "training steps, layer counts, hidden sizes, beam size. Those are "
            "settings, not results.\n\n"
            "If the paper reports no numeric evaluation results, return an empty list."
        ),
        user=context,
        max_tokens=1600,
    )
    return [
        ResultRow(paper_id=paper.id, **row.model_dump())
        for row in result.rows
        if not is_config_metric(row.metric)
    ]


# ---------------------------------------------------------------------------
# 2. Gap finder
# ---------------------------------------------------------------------------

def _gap_context(
    papers: list[Paper],
    extractions: dict[str, Extraction],
    searches: list[dict],
) -> tuple[str, list[Paper]]:
    """Numbered paper list plus the open problems already identified.

    Numbers (not ids) go to the model because arXiv ids are noisy tokens that
    invite hallucinated variants; they are mapped back to ids by position.
    """
    lines = []
    for index, paper in enumerate(papers, start=1):
        extraction = extractions.get(paper.id)
        summary = extraction.tldr if extraction else paper.abstract[:200]
        method = f" Method: {extraction.method}" if extraction else ""
        lines.append(f"[{index}] {paper.title}\n    {summary}{method}")

    open_problems = []
    for search in searches:
        for problem in search.get("open_problems", []) or []:
            title = problem.get("title", "")
            if title:
                open_problems.append(f"- {title}: {problem.get('description', '')}")

    context = "PAPERS:\n" + "\n".join(lines)
    if open_problems:
        # Deduplicated and capped: the same open problem recurs across searches
        # on one topic, and a wall of near-identical lines crowds out the paper
        # list the model actually needs to reason over.
        unique = list(dict.fromkeys(open_problems))[:25]
        context += "\n\nOPEN PROBLEMS ALREADY IDENTIFIED:\n" + "\n".join(unique)
    return context, papers


async def find_gaps(
    papers: list[Paper],
    extractions: dict[str, Extraction],
    searches: list[dict],
    limit: int = 60,
) -> GapReport:
    """Propose concrete unexplored intersections across the library.

    Capped at `limit` papers: the prompt has to fit, and beyond a few dozen
    papers the model stops reasoning about specific pairs and drifts into
    generic advice. Newest first, since recent work defines the open frontier.
    """
    selected = sorted(papers, key=lambda p: p.published, reverse=True)[:limit]
    context, ordered = _gap_context(selected, extractions, searches)

    result = await parse_json(
        GapsOut,
        system=(
            "You are a research advisor looking for genuinely unexplored intersections "
            "in a reading list. Each gap must name specific papers by their bracketed "
            "number and describe something concrete that has not been done — not a "
            "restatement of an open problem, and not generic advice like 'more work is "
            "needed'. Prefer gaps where one paper's method could be applied to another "
            "paper's setting. Never invent papers or numbers outside the given list."
        ),
        user=context,
        max_tokens=2200,
        guard=meta_guard.find_leak_in,
        repair=meta_guard.scrub,
        retry_instruction=meta_guard.RETRY_INSTRUCTION,
    )

    gaps: list[ResearchGap] = []
    for raw in result.gaps:
        ids: list[str] = []
        titles: list[str] = []
        for number in raw.paper_numbers:
            # 1-based numbering from the prompt; anything out of range is a
            # hallucinated reference and is dropped rather than trusted.
            if 1 <= number <= len(ordered):
                paper = ordered[number - 1]
                if paper.id not in ids:
                    ids.append(paper.id)
                    titles.append(paper.title)
        gaps.append(
            ResearchGap(
                title=raw.title,
                description=raw.description,
                why_it_matters=raw.why_it_matters,
                first_step=raw.first_step,
                paper_ids=ids,
                paper_titles=titles,
            )
        )

    return GapReport(
        gaps=gaps,
        paper_count=len(ordered),
        created_at=datetime.now().isoformat(timespec="seconds"),
    )


# ---------------------------------------------------------------------------
# 3. Simulated peer review
# ---------------------------------------------------------------------------

async def review_paper(paper: Paper, extraction: Extraction | None) -> PeerReview:
    """A conference-style review, scored on the usual reviewer axes.

    Distinct from the deep dive's critique card: that lists weaknesses, this
    commits to scores and a recommendation, which is what makes it useful for
    pressure-testing a paper (or your own draft) rather than just noting flaws.
    """
    context, from_fulltext = _paper_context(paper, extraction)
    if not from_fulltext:
        context += (
            "\n\nNOTE: only the abstract is available. Judge what can be judged and "
            "lower your confidence score accordingly."
        )

    result = await parse_json(
        PeerReviewOut,
        system=(
            "You are an experienced, fair reviewer for a top machine-learning "
            "conference. Write a review of the paper below. Be specific and cite "
            "details from the paper; generic praise or criticism is useless. Judge "
            "only what the paper actually claims. Scores are 1-5."
        ),
        user=context,
        max_tokens=1800,
        guard=meta_guard.find_leak_in,
        repair=meta_guard.scrub,
        retry_instruction=meta_guard.RETRY_INSTRUCTION,
    )

    return PeerReview(
        paper_id=paper.id,
        from_fulltext=from_fulltext,
        created_at=datetime.now().isoformat(timespec="seconds"),
        **result.model_dump(),
    )
