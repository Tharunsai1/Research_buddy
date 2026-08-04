"""Critical appraisal — work one paper through a reviewer's checklist.

The checklist is Chris Lovejoy's questions for papers applying machine
learning to healthcare (chrislovejoy.me). Its five sections generalise well
beyond healthcare — every empirical ML paper has data, a method, a claimed
result and a conclusion someone has to judge — so the *intent* of each
question is kept and the wording is adapted to the paper in hand. Asking an
architecture paper how ground truth was established by histology produces a
column of "not applicable" and teaches the reader nothing.

One call per section (map) plus a verdict over the answers (reduce), the same
shape as deepdive.py. Sections are independent, so a weak answer in one does
not contaminate the rest.
"""

from __future__ import annotations

import asyncio
import time

import meta_guard
from fulltext import FullText, trim_words
from llm import parse_json
from models import (
    Appraisal,
    AppraisalSection,
    AppraisalSectionOut,
    AppraisalVerdictOut,
    Paper,
)

# Every field here is prose the reader sees, so all of it is checked for the
# model narrating its instructions instead of answering them.
_NO_META = {
    "guard": meta_guard.find_leak_in,
    "repair": meta_guard.scrub,
    "retry_instruction": meta_guard.RETRY_INSTRUCTION,
}

# Words of source text per section call. The whole checklist runs against the
# same text, so this is a per-call budget rather than a per-paper one.
SOURCE_WORD_LIMIT = 3500

# The checklist, section by section. `prompt` carries the original questions;
# the model restates each one in the paper's own terms.
#
# `by_type` swaps the questions for kinds of paper the original checklist does
# not describe. It assumes an empirical study — a thing with data, a trained
# model and a measured result — and a survey has none of those. Asked the
# stock questions a survey answers "not reported" down the page, which reads
# as a failed appraisal when the truth is that the wrong questions were asked.
# The type comes from the extraction the paper already carries, so this costs
# no extra call.
CHECKLIST: list[dict] = [
    {
        "key": "overview",
        "title": "Overview",
        "prompt": (
            "- What did they do? (in plain English, no jargon)\n"
            "- How does this fit into the wider context — what other work exists "
            "on this problem, and what does this study add that they did not?\n"
            "- Who did the study? (authors and institutions, and any interest "
            "that might bear on the claims)"
        ),
    },
    {
        "key": "data",
        "title": "Data",
        "prompt": (
            "- What type of data is used?\n"
            "- How much data, and is it enough for the claim being made?\n"
            "- How was the ground truth or label defined, and by whom or by what "
            "process? (for a non-clinical paper: how were the reference answers, "
            "benchmarks or evaluation targets established?)\n"
            "- Is the data skewed toward particular classes, and how was that "
            "handled?\n"
            "- Does the data represent the population or distribution the model "
            "would actually be used on?"
        ),
        "by_type": {
            "survey": (
                "This is a survey, so 'data' means the literature it covers.\n"
                "- What body of work does it cover, and over what period?\n"
                "- How were papers selected — systematic criteria, or the authors' "
                "judgement?\n"
                "- Whose work is missing, and does the omission skew the picture?\n"
                "- Does it lean on the authors' own line of work more than the "
                "field would justify?"
            ),
            "theory": (
                "This is a theoretical paper, so 'data' means its assumptions and "
                "setting.\n"
                "- What is assumed, and how restrictive are those assumptions?\n"
                "- What model or regime does the analysis hold in?\n"
                "- Which assumptions are load-bearing — which results collapse if "
                "one is relaxed?\n"
                "- Are the assumptions ones that actually hold in practice?"
            ),
            "dataset": (
                "This paper introduces a dataset, so ask about its construction.\n"
                "- What does it contain and at what scale?\n"
                "- Who or what produced the annotations, and what was the "
                "agreement between them?\n"
                "- What biases does the collection process introduce?\n"
                "- How is it licensed and distributed, and is it maintainable?"
            ),
        },
    },
    {
        "key": "methodology",
        "title": "Methodology",
        "prompt": (
            "- What techniques did they use?\n"
            "- What were the output measures — what exactly does the model "
            "produce?\n"
            "- What type of study was it? Retrospective or prospective; on held-out "
            "data or data seen during development?\n"
            "- What was the rationale for the approach, and is there enough detail "
            "to replicate it?"
        ),
        "by_type": {
            "survey": (
                "This is a survey, so ask how it organises the field.\n"
                "- What taxonomy or structure does it impose, and does the work "
                "actually fall into it?\n"
                "- Are competing approaches compared on comparable terms?\n"
                "- Does it distinguish what is established from what is still "
                "contested?\n"
                "- Would someone new to the field come away with an accurate map?"
            ),
            "theory": (
                "This is a theoretical paper, so ask about the argument.\n"
                "- What is the main result, stated plainly?\n"
                "- What technique is the proof built on?\n"
                "- Which claims are proven and which are asserted, conjectured or "
                "argued informally?\n"
                "- Is the argument complete enough to check?"
            ),
        },
    },
    {
        "key": "performance",
        "title": "Performance",
        "prompt": (
            "- How did the model perform? Give the actual numbers and metrics as "
            "printed.\n"
            "- What was it compared against, and was that baseline a fair one?\n"
            "- What features or components mattered most, and do those make sense?\n"
            "- How would this be used in practice, and does the evaluation "
            "resemble that setting?"
        ),
        "by_type": {
            "survey": (
                "This is a survey, so there is no model to score. Ask what it "
                "establishes.\n"
                "- What does it conclude about the state of the field?\n"
                "- Is that conclusion supported by the work it reviews, or is it "
                "the authors' position?\n"
                "- Does it identify open problems concretely, or only gesture at "
                "them?\n"
                "- What would a reader be able to do after reading it that they "
                "could not before?"
            ),
            "theory": (
                "This is a theoretical paper, so ask what the results are worth.\n"
                "- How tight are the bounds or guarantees, and in what regime do "
                "they bind?\n"
                "- Are they vacuous at realistic scales?\n"
                "- Is there empirical work confirming the theory holds in "
                "practice?\n"
                "- What does this let you predict that you could not before?"
            ),
        },
    },
]


def _header(paper: Paper) -> str:
    return (
        f"Paper: {paper.title}\n"
        f"Authors: {', '.join(paper.authors[:8]) or 'not listed'}\n"
        f"Published: {paper.published} · {paper.primary_category}"
    )


def _source_text(paper: Paper, full: FullText | None) -> tuple[str, str]:
    """The text to appraise, and which kind it is.

    Falls back to the abstract when the paper has not been read in full. The
    caller records which was used: an abstract-only appraisal answers the
    Overview questions well and most of the Data and Performance ones not at
    all, and that difference has to reach the reader.
    """
    if full is not None and full.sections:
        body = "\n\n".join(f"## {s.title}\n{s.text}" for s in full.sections)
        return f"Abstract:\n{paper.abstract}\n\n{body}", "full_text"
    return f"Abstract:\n{paper.abstract}", "abstract"


def _questions_for(section: dict, paper_type: str) -> str:
    """The questions this section asks of this kind of paper."""
    return (section.get("by_type") or {}).get(paper_type, section["prompt"])


async def _appraise_section(
    paper: Paper, section: dict, text: str, source: str, paper_type: str
) -> AppraisalSection:
    unread = (
        "\n\nYou have ONLY the abstract, not the full paper. Answer what the "
        "abstract genuinely supports and mark everything else 'not_reported'. "
        "Do not infer method or evaluation detail an abstract would not contain."
        if source == "abstract"
        else ""
    )
    result = await parse_json(
        AppraisalSectionOut,
        system=(
            "You are appraising a research paper against a reviewer's checklist, "
            "one section at a time. For each question: restate it in the paper's "
            "own vocabulary, then answer it from the text. Keep specific numbers, "
            "dataset names, metrics and baselines exactly as printed. Never invent "
            "a result, and never soften a gap — if the paper does not report "
            "something the question asks for, say so and mark it 'not_reported'. "
            "If a question does not fit this kind of paper at all, mark it "
            "'not_applicable' instead and say briefly why; do not pad the section "
            "with questions this paper was never going to answer."
            + unread
        ),
        user=(
            f"{_header(paper)}\n"
            f"Kind of paper: {paper_type}\n\n"
            f"Checklist section — {section['title']}:\n"
            f"{_questions_for(section, paper_type)}\n\n"
            f"Paper text:\n{trim_words(text, SOURCE_WORD_LIMIT)}"
        ),
        max_tokens=1400,
        **_NO_META,
    )
    return AppraisalSection(
        key=section["key"], title=section["title"], answers=result.answers
    )


async def run_appraisal(
    paper: Paper,
    full: FullText | None,
    paper_type: str = "method",
    concurrency: int = 2,
) -> Appraisal:
    text, source = _source_text(paper, full)

    semaphore = asyncio.Semaphore(concurrency)
    sections: list[AppraisalSection | None] = [None] * len(CHECKLIST)

    async def run(index: int, section: dict) -> None:
        async with semaphore:
            sections[index] = await _appraise_section(
                paper, section, text, source, paper_type
            )

    await asyncio.gather(*(run(i, s) for i, s in enumerate(CHECKLIST)))
    ordered = [s for s in sections if s is not None]

    # Reduce: the Conclusions section of the checklist asks the reader to judge
    # the paper *after* working through the rest, so it runs over the answers
    # rather than over the paper.
    brief = "\n\n".join(
        f"[{s.title}]\n"
        + "\n".join(f"Q: {a.question}\nA: {a.answer} ({a.status})" for a in s.answers)
        for s in ordered
    )
    verdict = await parse_json(
        AppraisalVerdictOut,
        system=(
            "You are finishing a paper appraisal. Having worked through the "
            "checklist, judge the paper: what the authors conclude, whether the "
            "evidence supports it, the single biggest gap, and what you would "
            "want next. Commit to a view. Base it only on the answers given — "
            "questions marked 'not_reported' are themselves evidence about how "
            "much the paper establishes. Questions marked 'not_applicable' are "
            "not: they say the checklist asked something this kind of paper was "
            "never meant to answer, and must not count against it."
        ),
        user=f"{_header(paper)}\nKind of paper: {paper_type}\n\nChecklist answers:\n\n{brief}",
        max_tokens=1200,
        **_NO_META,
    )

    return Appraisal(
        paper_id=paper.id,
        source=source,
        sections=ordered,
        conclusion=verdict.conclusion,
        justified=verdict.justified,
        justification=verdict.justification,
        biggest_gap=verdict.biggest_gap,
        next_steps=verdict.next_steps,
        created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )
