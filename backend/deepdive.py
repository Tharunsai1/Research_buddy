"""Deep dive — read one paper's full text and produce teaching material.

Map-reduce over the paper: digest each section independently (map), then
synthesize, explain at three levels, extract a glossary, and critique from
those digests (reduce). Only the digests reach the reduce stage, so context
stays small even for long papers.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import meta_guard
from fulltext import FullText, trim_words
from llm import parse_json
from models import (
    CritiqueOut,
    DeepDive,
    ExplanationsOut,
    GlossaryOut,
    Paper,
    SectionDigest,
    SectionDigestOut,
    SynthesisOut,
)

MAX_SECTIONS = 8
SECTION_WORD_LIMIT = 1400

Progress = Callable[[str], None]
Partial = Callable[[str, Any], None]

# Every stage here writes prose the reader sees directly, so all of them are
# checked for the model narrating its own instructions instead of answering.
# The guard is free when the output is clean — it only costs a retry on a hit.
_NO_META = {
    "guard": meta_guard.find_leak_in,
    "repair": meta_guard.scrub,
    "retry_instruction": meta_guard.RETRY_INSTRUCTION,
}


def _paper_header(paper: Paper) -> str:
    return (
        f"Paper: {paper.title}\n"
        f"Authors: {', '.join(paper.authors[:6])}\n"
        f"Published: {paper.published} · {paper.primary_category}"
    )


def _select_sections(full: FullText) -> list:
    """Keep the most substantial sections, in reading order."""
    sections = list(full.sections)
    if len(sections) <= MAX_SECTIONS:
        return sections
    ranked = sorted(sections, key=lambda s: s.words, reverse=True)[:MAX_SECTIONS]
    keep = {id(s) for s in ranked}
    return [s for s in sections if id(s) in keep]


async def _digest_section(paper: Paper, section, index: int, total: int) -> SectionDigest:
    result = await parse_json(
        SectionDigestOut,
        system=(
            "You are helping a student read a machine-learning paper carefully. "
            "Digest ONE section at a time. Be concrete and faithful to the text: "
            "keep specific numbers, dataset names, model names, and equations. "
            "Never invent results that are not in the section."
        ),
        user=(
            f"{_paper_header(paper)}\n\n"
            f"Section {index} of {total}: {section.title}\n\n"
            f"{trim_words(section.text, SECTION_WORD_LIMIT)}"
        ),
        max_tokens=900,
        **_NO_META,
    )
    return SectionDigest(
        title=section.title,
        summary=result.summary,
        key_points=result.key_points,
        words=section.words,
    )


def _digest_brief(digests: list[SectionDigest]) -> str:
    return "\n\n".join(
        f"[{d.title}]\n{d.summary}\n" + "\n".join(f"- {p}" for p in d.key_points)
        for d in digests
    )


async def run_deep_dive(
    paper: Paper,
    full: FullText,
    on_progress: Progress,
    concurrency: int = 2,
    on_partial: Partial | None = None,
) -> DeepDive:
    def emit(key: str, value: Any) -> None:
        if on_partial is not None:
            on_partial(key, value)

    sections = _select_sections(full)
    total = len(sections)

    # ---- map: one digest per section ---------------------------------------
    done = 0
    lock = asyncio.Lock()
    semaphore = asyncio.Semaphore(concurrency)
    digests: list[SectionDigest | None] = [None] * total

    async def run(index: int, section) -> None:
        nonlocal done
        async with semaphore:
            digest = await _digest_section(paper, section, index + 1, total)
        async with lock:
            done += 1
            digests[index] = digest
            on_progress(f"Read {done}/{total} sections · {section.title}")

    on_progress(f"Reading 0/{total} sections")
    await asyncio.gather(*(run(i, s) for i, s in enumerate(sections)))
    ordered = [d for d in digests if d is not None]
    brief = _digest_brief(ordered)
    emit("sections", [d.model_dump() for d in ordered])

    # ---- reduce: synthesis --------------------------------------------------
    on_progress("Synthesizing the full paper…")
    synthesis = await parse_json(
        SynthesisOut,
        system=(
            "You synthesize a complete machine-learning paper from per-section digests. "
            "Be specific and quantitative. Do not add claims that are absent from the digests."
        ),
        user=f"{_paper_header(paper)}\n\nAbstract:\n{paper.abstract}\n\nSection digests:\n\n{brief}",
        max_tokens=1600,
        **_NO_META,
    )
    emit("synthesis", synthesis.model_dump())

    # ---- reduce: teaching material -----------------------------------------
    on_progress("Writing three-level explanations…")
    explanations = await parse_json(
        ExplanationsOut,
        system=(
            "You explain research papers at three depths for three different readers. "
            "The undergrad version must contain NO jargon and use a concrete analogy. "
            "The grad version names techniques precisely. The expert version covers only "
            "the delta versus prior work. Never repeat the same wording across levels."
        ),
        user=(
            f"{_paper_header(paper)}\n\nSynthesis:\n{synthesis.deep_summary}\n\n"
            f"Results:\n{synthesis.results_detail}\n\nSection digests:\n\n{brief}"
        ),
        max_tokens=1600,
        **_NO_META,
    )
    emit("explanations", explanations.model_dump())

    on_progress("Building the jargon glossary…")
    glossary = await parse_json(
        GlossaryOut,
        system=(
            "You build glossaries that unblock newcomers reading a paper. Choose the terms "
            "that genuinely gate comprehension — technical methods, metrics, datasets, and "
            "architectures — not common words. Definitions must be plain English, one sentence, "
            "understandable without prior ML knowledge."
        ),
        user=f"{_paper_header(paper)}\n\nAbstract:\n{paper.abstract}\n\nSection digests:\n\n{brief}",
        max_tokens=2000,
        **_NO_META,
    )
    emit("glossary", [t.model_dump() for t in glossary.terms])

    on_progress("Writing the critique card…")
    critique = await parse_json(
        CritiqueOut,
        system=(
            "You are a rigorous but fair peer reviewer. Write the finished review only: "
            "never restate the task, narrate your process, refer to yourself, or mention "
            "'the digest', 'the summary', or 'the provided text'. Start directly with the "
            "substance. Prefer specific, checkable criticisms (missing baseline, single "
            "dataset, cost not reported) over generic complaints, and cite the paper's own "
            "numbers wherever you can. If something you would want is absent, say the paper "
            "does not report it."
        ),
        user=(
            f"{_paper_header(paper)}\n\nSynthesis:\n{synthesis.deep_summary}\n\n"
            f"Results:\n{synthesis.results_detail}\n\nSection digests:\n\n{brief}"
        ),
        max_tokens=1800,
        **_NO_META,
    )
    emit("critique", critique.model_dump())

    return DeepDive(
        paper_id=paper.id,
        source_url=full.source_url,
        total_words=full.total_words,
        deep_summary=synthesis.deep_summary,
        contributions=synthesis.contributions,
        results_detail=synthesis.results_detail,
        sections=ordered,
        explanations=explanations,
        glossary=glossary.terms,
        critique=critique,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
