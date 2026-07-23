"""Pydantic models shared across the pipeline, the store, and the API."""

from __future__ import annotations

import time
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Core domain objects
# ---------------------------------------------------------------------------

class Paper(BaseModel):
    id: str                      # arXiv id without version, e.g. "2401.12345"
    title: str
    authors: list[str]
    abstract: str
    published: str               # YYYY-MM-DD
    categories: list[str]
    primary_category: str
    arxiv_url: str
    pdf_url: str
    comment: Optional[str] = None
    relevance: Optional[float] = None   # 0..1 reranker score for the search that found it


class Extraction(BaseModel):
    """Structured summary of a single paper (from title + abstract)."""

    tldr: str = Field(description="One-sentence TL;DR of the paper, <= 35 words.")
    problem: str = Field(description="The gap or problem the paper addresses, 2-3 sentences.")
    method: str = Field(description="The approach or method proposed, 2-3 sentences.")
    key_results: str = Field(description="The main quantitative/qualitative results, 2-3 sentences.")
    why_it_matters: str = Field(description="The contribution and why it matters for the field, 1-2 sentences.")
    keywords: list[str] = Field(
        json_schema_extra={"minItems": 3, "maxItems": 6},
        description="3-6 short lowercase topic keywords.",
    )
    paper_type: Literal[
        "method", "survey", "benchmark", "evaluation", "theory", "application", "dataset"
    ] = Field(description="The kind of paper this is.")


# ---------------------------------------------------------------------------
# LLM structured-output schemas (indices refer to numbered lists in prompts)
# ---------------------------------------------------------------------------

# NOTE on json_schema_extra bounds: these minItems/maxItems land in the JSON
# schema, where Ollama's grammar-constrained decoding enforces them at
# generation time (stops small models from looping array items forever).
# Pydantic does NOT validate them, so providers that ignore the bounds are
# unaffected.

class QueryExpansion(BaseModel):
    queries: list[str] = Field(
        json_schema_extra={"minItems": 1, "maxItems": 3},
        description=(
            "2-3 arXiv API search queries covering different phrasings/subtopics. "
            'Each is a search_query string, e.g. all:"retrieval augmented generation" '
            'or ti:"diffusion policy" AND cat:cs.LG.'
        ),
    )


class Shortlist(BaseModel):
    selected: list[int] = Field(
        json_schema_extra={"minItems": 1, "maxItems": 12},
        description="Indices (1-based) of the selected papers, most relevant first.",
    )


class ClusterOut(BaseModel):
    name: str = Field(description="Short cluster name, 2-4 words.")
    description: str = Field(description="1-2 sentence description of what this cluster explores.")
    paper_indices: list[int] = Field(
        json_schema_extra={"minItems": 1, "maxItems": 12},
        description="1-based indices of papers in this cluster.",
    )


class EdgeOut(BaseModel):
    source: int = Field(description="1-based index of the source paper.")
    target: int = Field(description="1-based index of the target paper.")
    kind: Literal["builds_on", "compares_to", "complements", "evaluates", "extends"]
    description: str = Field(description="One sentence explaining the relationship.")


class TensionOut(BaseModel):
    name: str = Field(description="Short name of the tension/tradeoff, 3-6 words.")
    description: str = Field(description="1-2 sentences on the disagreement or tradeoff.")
    side_a_label: str
    side_a_indices: list[int] = Field(json_schema_extra={"minItems": 1, "maxItems": 6})
    side_b_label: str
    side_b_indices: list[int] = Field(json_schema_extra={"minItems": 1, "maxItems": 6})


class OpenProblemOut(BaseModel):
    title: str = Field(description="Short title of the open problem.")
    description: str = Field(description="1-2 sentences on why it is unsolved and what is needed.")
    related_indices: list[int] = Field(json_schema_extra={"maxItems": 6})


class ReadingStep(BaseModel):
    index: int = Field(description="1-based paper index.")
    stage: Literal["foundation", "core", "frontier"]
    why: str = Field(description="One short sentence: why read it at this point.")


class LandscapeOut(BaseModel):
    title: str = Field(description='Clean display title for the topic, e.g. "Retrieval-Augmented Generation".')
    overview: str = Field(description="3-4 sentence overview of the research landscape these papers span.")
    clusters: list[ClusterOut] = Field(
        json_schema_extra={"minItems": 2, "maxItems": 4},
        description="2-4 method/theme clusters covering every paper.",
    )
    edges: list[EdgeOut] = Field(
        json_schema_extra={"minItems": 4, "maxItems": 14},
        description="6-14 relationships between papers.",
    )
    tensions: list[TensionOut] = Field(
        json_schema_extra={"minItems": 1, "maxItems": 3},
        description="1-3 genuine tensions or tradeoffs in the field.",
    )
    consensus: list[str] = Field(
        json_schema_extra={"minItems": 2, "maxItems": 4},
        description="2-4 statements most of these papers agree on.",
    )
    open_problems: list[OpenProblemOut] = Field(
        json_schema_extra={"minItems": 3, "maxItems": 5},
        description="3-5 open problems.",
    )
    reading_order: list[ReadingStep] = Field(
        json_schema_extra={"minItems": 1, "maxItems": 12},
        description="Suggested reading order covering every paper exactly once.",
    )


class MapClusterOut(BaseModel):
    name: str = Field(description="Short cluster name, 2-4 words.")
    paper_indices: list[int] = Field(json_schema_extra={"minItems": 1, "maxItems": 80})


class GlobalMapOut(BaseModel):
    clusters: list[MapClusterOut] = Field(
        json_schema_extra={"minItems": 1, "maxItems": 8},
        description="4-8 clusters partitioning ALL papers in the collection. Every paper appears exactly once.",
    )
    bridge_edges: list[EdgeOut] = Field(
        json_schema_extra={"maxItems": 10},
        description="0-10 extra edges connecting related papers that came from DIFFERENT searches.",
    )


class ClusterAssignmentOut(BaseModel):
    paper_index: int = Field(description="1-based index of the paper being placed.")
    cluster: str = Field(description="Cluster it belongs in; reuse an existing name when one fits.")


class IncrementalMapOut(BaseModel):
    """Places only the papers a new search added, leaving settled clusters alone."""

    assignments: list[ClusterAssignmentOut] = Field(
        json_schema_extra={"maxItems": 40},
        description="One entry per paper that still needs a cluster.",
    )
    bridge_edges: list[EdgeOut] = Field(
        json_schema_extra={"maxItems": 6},
        description="0-6 edges from a newly placed paper to a strongly related existing one.",
    )


# ---------------------------------------------------------------------------
# Citation data (Semantic Scholar)
# ---------------------------------------------------------------------------

class S2Reference(BaseModel):
    arxiv_id: Optional[str] = None
    title: str
    citation_count: int = 0
    year: Optional[int] = None


class S2Paper(BaseModel):
    arxiv_id: str
    title: str
    year: Optional[int] = None
    citation_count: int = 0
    influential_count: int = 0
    reference_count: int = 0
    references: list[S2Reference] = Field(default_factory=list)
    fetched_at: str = ""


class Prerequisite(BaseModel):
    """A paper cited by the library that isn't in it yet."""

    arxiv_id: str
    title: str
    citation_count: int = 0
    year: Optional[int] = None
    cited_by: list[str] = Field(default_factory=list)   # library paper ids
    in_library: bool = False


# ---------------------------------------------------------------------------
# Deep dive (full-text reading of a single paper)
# ---------------------------------------------------------------------------

class SectionDigestOut(BaseModel):
    """LLM output for one section of the paper."""

    summary: str = Field(description="2-4 sentences explaining what this section does and why.")
    key_points: list[str] = Field(
        json_schema_extra={"minItems": 1, "maxItems": 5},
        description="1-5 concrete takeaways from this section. Include specific numbers, dataset names, or equations when present.",
    )


class SectionDigest(BaseModel):
    title: str
    summary: str
    key_points: list[str]
    words: int = 0


class ExplanationsOut(BaseModel):
    undergrad: str = Field(
        description=(
            "Explain the paper to a smart undergraduate with no ML background. "
            "No jargon at all; use a concrete everyday analogy. 4-6 sentences."
        )
    )
    grad: str = Field(
        description=(
            "Explain to a CS grad student who knows ML basics but not this subfield. "
            "Name the technique precisely and describe how it works mechanically. 4-6 sentences."
        )
    )
    expert: str = Field(
        description=(
            "For a researcher in this exact subfield: only the delta versus prior work — "
            "what is genuinely new, the key technical choice, and the headline numbers. 3-5 sentences."
        )
    )


class GlossaryTermOut(BaseModel):
    term: str = Field(description="The technical term exactly as it appears in the paper.")
    definition: str = Field(description="One plain-English sentence a beginner can understand.")
    in_this_paper: str = Field(
        description="One sentence on how this specific paper uses or changes this concept."
    )


class GlossaryOut(BaseModel):
    terms: list[GlossaryTermOut] = Field(
        json_schema_extra={"minItems": 3, "maxItems": 12},
        description="The 6-12 technical terms a newcomer must know to read this paper.",
    )


class CritiqueOut(BaseModel):
    not_solved: str = Field(
        description="2-3 sentences on what problem this paper explicitly does NOT solve."
    )
    assumptions: list[str] = Field(
        json_schema_extra={"minItems": 2, "maxItems": 5},
        description="The load-bearing assumptions the results depend on; note which are fragile.",
    )
    weaknesses: list[str] = Field(
        json_schema_extra={"minItems": 2, "maxItems": 5},
        description="Concrete methodological weaknesses: missing baselines, narrow evaluation, cost, confounds.",
    )
    reviewer_questions: list[str] = Field(
        json_schema_extra={"minItems": 3, "maxItems": 5},
        description="Sharp questions a peer reviewer would ask the authors.",
    )


class SynthesisOut(BaseModel):
    deep_summary: str = Field(
        description="A 5-8 sentence synthesis of the whole paper, written from the section digests."
    )
    contributions: list[str] = Field(
        json_schema_extra={"minItems": 1, "maxItems": 5},
        description="The paper's concrete claimed contributions, one per item.",
    )
    results_detail: str = Field(
        description="3-5 sentences on the experimental setup and the actual numbers reported."
    )


class DeepDive(BaseModel):
    """Everything produced by a full-text reading, persisted per paper."""

    paper_id: str
    source_url: str
    total_words: int
    deep_summary: str
    contributions: list[str]
    results_detail: str
    sections: list[SectionDigest]
    explanations: ExplanationsOut
    glossary: list[GlossaryTermOut]
    critique: CritiqueOut
    chunk_count: int = 0
    created_at: str = ""


class ChatSource(BaseModel):
    section: str
    text: str
    score: float


class ChatAnswer(BaseModel):
    answer: str
    sources: list[ChatSource]


class ChatOut(BaseModel):
    """LLM output for a grounded question about one paper."""

    answer: str = Field(
        description=(
            "Answer the question using ONLY the numbered excerpts. Cite them inline as [1], [2]. "
            "If the excerpts do not contain the answer, say so plainly."
        )
    )
    used_excerpts: list[int] = Field(
        json_schema_extra={"maxItems": 6},
        description="Numbers of the excerpts you actually relied on.",
    )


# ---------------------------------------------------------------------------
# Research toolkit: matrix, related work, comparison
# ---------------------------------------------------------------------------

class MatrixRowOut(BaseModel):
    """One row of the classic survey table, extracted per paper."""

    task: str = Field(description="The concrete task addressed, 2-5 words (e.g. 'open-domain QA').")
    method_family: str = Field(
        description="The family the approach belongs to, 2-5 words (e.g. 'iterative retrieval', 'graph retrieval')."
    )
    key_idea: str = Field(description="The single distinguishing idea, one short sentence.")
    datasets: list[str] = Field(
        json_schema_extra={"maxItems": 6},
        description="Datasets or benchmarks used. Exact names only. Empty if none are named.",
    )
    metrics: list[str] = Field(
        json_schema_extra={"maxItems": 5},
        description="Evaluation metrics reported (e.g. EM, F1, Recall@5). Empty if none are named.",
    )
    headline_result: str = Field(
        description="The single most important reported number, with its metric and dataset. 'Not reported' if absent."
    )
    code_available: Literal["yes", "no", "unclear"] = Field(
        description="Whether the paper states that code or a repository is released."
    )


class MatrixRow(BaseModel):
    paper_id: str
    task: str
    method_family: str
    key_idea: str
    datasets: list[str]
    metrics: list[str]
    headline_result: str
    code_available: str
    code_url: Optional[str] = None
    from_fulltext: bool = False


class RelatedWorkParagraph(BaseModel):
    theme: str = Field(description="Short heading for this group of work, 2-5 words.")
    text: str = Field(
        description=(
            "One academic paragraph (4-7 sentences) synthesizing the papers in this theme. "
            "Cite every paper you discuss inline using DOUBLE SQUARE BRACKETS around its "
            "key, exactly like [[smith2024method]]. Never use a backslash or LaTeX command. "
            "Compare and contrast rather than listing summaries."
        )
    )


class RelatedWorkOut(BaseModel):
    paragraphs: list[RelatedWorkParagraph] = Field(
        json_schema_extra={"minItems": 1, "maxItems": 5},
        description="2-4 thematic paragraphs covering all the papers.",
    )
    gap_statement: str = Field(
        description=(
            "2-3 sentences naming what remains unaddressed across these papers — the "
            "gap a new contribution could target. Cite with [[key]] where relevant."
        )
    )


class RelatedWork(BaseModel):
    paragraphs: list[RelatedWorkParagraph]
    gap_statement: str
    bibtex: str
    keys: dict[str, str]          # paper_id -> cite key
    paper_ids: list[str]


class ComparisonOut(BaseModel):
    problem_a: str = Field(
        description=(
            "The gap or challenge paper A sets out to solve, 1-2 sentences. "
            "Describe the problem itself — never restate the paper's name or method."
        )
    )
    problem_b: str = Field(
        description=(
            "The gap or challenge paper B sets out to solve, 1-2 sentences. "
            "Describe the problem itself — never restate the paper's name or method."
        )
    )
    method_a: str = Field(description="Paper A's approach, 1-2 sentences.")
    method_b: str = Field(description="Paper B's approach, 1-2 sentences.")
    results_a: str = Field(description="Paper A's headline results with numbers where known.")
    results_b: str = Field(description="Paper B's headline results with numbers where known.")
    strengths_a: str = Field(description="Where paper A is stronger.")
    strengths_b: str = Field(description="Where paper B is stronger.")
    limitations_a: str = Field(description="Paper A's main limitation.")
    limitations_b: str = Field(description="Paper B's main limitation.")
    key_difference: str = Field(
        description="2-3 sentences on the single most important difference between them."
    )
    when_to_use_a: str = Field(description="One sentence: choose A when…")
    when_to_use_b: str = Field(description="One sentence: choose B when…")


# ---------------------------------------------------------------------------
# Learning loop: flashcards, quiz grading, field digest
# ---------------------------------------------------------------------------

class FlashcardOut(BaseModel):
    question: str
    answer: str
    kind: Literal["concept", "result", "critique"]


class FlashcardSetOut(BaseModel):
    cards: list[FlashcardOut] = Field(
        json_schema_extra={"minItems": 3, "maxItems": 10},
        description="Study cards for this paper.",
    )


class Flashcard(BaseModel):
    id: str
    paper_id: str
    question: str
    answer: str
    kind: str                      # definition | concept | result | critique | relationship
    # For kind="relationship": the other paper in the pair, so a cluster-scoped
    # quiz can require BOTH ends of the relationship to be in scope, not just
    # the source paper.
    related_paper_id: Optional[str] = None
    # Spaced-repetition state (SM-2 lite)
    due: str = ""                  # ISO date; "" means never reviewed
    interval: int = 0              # days until next review
    ease: float = 2.5
    reps: int = 0
    lapses: int = 0
    last_score: Optional[int] = None


class GradeOut(BaseModel):
    verdict: Literal["correct", "partial", "incorrect"]
    score: int = Field(description="0-100 how complete and accurate the answer is.")
    feedback: str = Field(description="2-3 sentences of direct, encouraging feedback.")
    missed: list[str] = Field(
        json_schema_extra={"maxItems": 4},
        description="Key points the answer omitted or got wrong. Empty if fully correct.",
    )


class DigestHighlightOut(BaseModel):
    index: int = Field(description="1-based index of the new paper.")
    why_it_matters: str = Field(description="One sentence on why this matters for the field.")
    challenges_consensus: bool = Field(
        description="True only if this paper contradicts or complicates an existing consensus point."
    )
    relation: str = Field(
        description="One sentence relating it to the papers already in the collection."
    )


class DigestOut(BaseModel):
    headline: str = Field(
        description="One sentence summarizing what changed, e.g. '3 new papers, one challenges X'."
    )
    summary: str = Field(description="3-5 sentences on how the field moved since the last check.")
    highlights: list[DigestHighlightOut] = Field(
        json_schema_extra={"maxItems": 8},
        description="One entry per genuinely notable new paper.",
    )


class DigestHighlight(BaseModel):
    paper_id: str
    why_it_matters: str
    challenges_consensus: bool
    relation: str


class Digest(BaseModel):
    search_id: str
    query: str
    created_at: str
    checked_count: int             # candidates seen on arXiv
    new_paper_ids: list[str]
    headline: str
    summary: str
    highlights: list[DigestHighlight]


# ---------------------------------------------------------------------------
# Job / pipeline progress
# ---------------------------------------------------------------------------

STAGES: list[tuple[str, str]] = [
    ("query", "Query arXiv"),
    ("rank", "Rank by relevance"),
    ("summarize", "Generate summaries"),
    ("map", "Map research landscape"),
]


class StageState(BaseModel):
    key: str
    label: str
    status: Literal["pending", "active", "done", "error"] = "pending"
    detail: str = ""


class Job(BaseModel):
    id: str
    query: str
    status: Literal["running", "done", "error"] = "running"
    stages: list[StageState] = Field(
        default_factory=lambda: [StageState(key=k, label=l) for k, l in STAGES]
    )
    error: Optional[str] = None
    search_id: Optional[str] = None
    created_at: float = Field(default_factory=time.time)

    def stage(self, key: str) -> StageState:
        return next(s for s in self.stages if s.key == key)


DEEP_STAGES: list[tuple[str, str]] = [
    ("fetch", "Fetch full text"),
    ("sections", "Read section by section"),
    ("synthesize", "Synthesize the paper"),
    ("teach", "Explain, define, critique"),
    ("index", "Index for chat"),
]


class DeepJob(BaseModel):
    id: str
    paper_id: str
    status: Literal["running", "done", "error"] = "running"
    stages: list[StageState] = Field(
        default_factory=lambda: [StageState(key=k, label=l) for k, l in DEEP_STAGES]
    )
    error: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    # Filled in as each generation phase finishes (sections, synthesis,
    # explanations, glossary, critique), so the reader can start reading the
    # summary while the critique is still being written instead of staring at
    # a progress bar for the full ~90s-4min. Keys mirror DeepDive's fields.
    partial: dict[str, Any] = Field(default_factory=dict)

    def stage(self, key: str) -> StageState:
        return next(s for s in self.stages if s.key == key)
