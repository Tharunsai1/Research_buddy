"""Research toolkit — survey matrix rows, related-work drafts + BibTeX, and
pairwise comparisons.

Everything here prefers a paper's full-text deep dive when one exists (real
numbers, real dataset names) and falls back to the abstract otherwise.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

import store
from llm import parse_json
from models import (
    ComparisonOut,
    Extraction,
    MatrixRow,
    MatrixRowOut,
    Paper,
    RelatedWork,
    RelatedWorkOut,
    RelatedWorkParagraph,
)

_CODE_URL = re.compile(
    r"https?://(?:www\.)?(?:github\.com|gitlab\.com|huggingface\.co|bitbucket\.org)/[\w.\-/#]+",
    re.I,
)

_STOPWORDS = {
    "a", "an", "the", "on", "of", "for", "and", "in", "to", "with", "via",
    "is", "are", "towards", "toward", "using", "from", "by",
}


# ---------------------------------------------------------------------------
# Shared context building
# ---------------------------------------------------------------------------

def _paper_context(paper: Paper, extraction: Extraction | None) -> tuple[str, bool]:
    """Richest available description of a paper, plus whether it used full text."""
    deep = store.load_deep_dive(paper.id)
    header = f"Title: {paper.title}\nPublished: {paper.published}\nAbstract: {paper.abstract}"
    if deep:
        digests = "\n".join(
            f"[{section['title']}] {section['summary']} "
            + " ".join(section.get("key_points") or [])
            for section in deep.get("sections", [])
        )
        body = (
            f"{header}\n\nFull-paper synthesis: {deep.get('deep_summary', '')}\n"
            f"Results detail: {deep.get('results_detail', '')}\n\nSection digests:\n{digests}"
        )
        return body[:14000], True
    if extraction:
        body = (
            f"{header}\n\nSummary: {extraction.tldr}\nProblem: {extraction.problem}\n"
            f"Method: {extraction.method}\nResults: {extraction.key_results}"
        )
        return body, False
    return header, False


def _find_code_url(paper: Paper) -> str | None:
    haystack = " ".join(filter(None, [paper.abstract, paper.comment or ""]))
    deep = store.load_deep_dive(paper.id)
    if deep:
        haystack += " " + " ".join(
            section.get("summary", "") + " " + " ".join(section.get("key_points") or [])
            for section in deep.get("sections", [])
        )
    match = _CODE_URL.search(haystack)
    return match.group(0).rstrip(".,);") if match else None


# ---------------------------------------------------------------------------
# 1. Literature-review matrix
# ---------------------------------------------------------------------------

async def build_matrix_row(paper: Paper, extraction: Extraction | None) -> MatrixRow:
    context, from_fulltext = _paper_context(paper, extraction)
    result = await parse_json(
        MatrixRowOut,
        system=(
            "You fill in one row of a literature-review table for a research paper. "
            "Be terse and factual — these cells go into a comparison table. Use exact "
            "dataset and metric names as written in the paper. Never invent numbers: if "
            "a value is not stated, write 'Not reported'."
        ),
        user=context,
        max_tokens=800,
    )
    code_url = _find_code_url(paper)
    return MatrixRow(
        paper_id=paper.id,
        task=result.task,
        method_family=result.method_family,
        key_idea=result.key_idea,
        datasets=result.datasets,
        metrics=result.metrics,
        headline_result=result.headline_result,
        # A discovered repo link is harder evidence than the model's judgement.
        code_available="yes" if code_url else result.code_available,
        code_url=code_url,
        from_fulltext=from_fulltext,
    )


def matrix_to_csv(rows: list[MatrixRow], papers: dict[str, Paper]) -> str:
    import csv
    import io

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "Paper", "Year", "arXiv", "Task", "Method family", "Key idea",
            "Datasets", "Metrics", "Headline result", "Code",
        ]
    )
    for row in rows:
        paper = papers.get(row.paper_id)
        writer.writerow(
            [
                paper.title if paper else row.paper_id,
                paper.published[:4] if paper else "",
                row.paper_id,
                row.task,
                row.method_family,
                row.key_idea,
                "; ".join(row.datasets),
                "; ".join(row.metrics),
                row.headline_result,
                row.code_url or row.code_available,
            ]
        )
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# 2. Related work + BibTeX
# ---------------------------------------------------------------------------

def _ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def cite_key(paper: Paper, taken: set[str]) -> str:
    surname = "unknown"
    if paper.authors:
        parts = _ascii(paper.authors[0]).replace(".", " ").split()
        if parts:
            surname = re.sub(r"[^A-Za-z]", "", parts[-1]).lower() or "unknown"
    year = paper.published[:4] or "0000"
    word = next(
        (
            re.sub(r"[^A-Za-z]", "", w).lower()
            for w in _ascii(paper.title).split()
            if re.sub(r"[^A-Za-z]", "", w).lower() not in _STOPWORDS
            and len(re.sub(r"[^A-Za-z]", "", w)) > 2
        ),
        "paper",
    )
    base = f"{surname}{year}{word}"
    key, suffix = base, ord("a")
    while key in taken:
        key = f"{base}{chr(suffix)}"
        suffix += 1
    taken.add(key)
    return key


def _bibtex_escape(value: str) -> str:
    return value.replace("{", "").replace("}", "").replace("\\", "")


def to_bibtex(paper: Paper, key: str) -> str:
    authors = " and ".join(_bibtex_escape(a) for a in paper.authors) or "Unknown"
    return (
        f"@article{{{key},\n"
        f"  title         = {{{_bibtex_escape(paper.title)}}},\n"
        f"  author        = {{{authors}}},\n"
        f"  year          = {{{paper.published[:4]}}},\n"
        f"  journal       = {{arXiv preprint arXiv:{paper.id}}},\n"
        f"  eprint        = {{{paper.id}}},\n"
        f"  archivePrefix = {{arXiv}},\n"
        f"  primaryClass  = {{{paper.primary_category}}},\n"
        f"  url           = {{{paper.arxiv_url}}}\n"
        f"}}"
    )


_BRACKET_CITE = re.compile(r"\[\[\s*([A-Za-z0-9_:\-]+)\s*\]\]")


def _to_latex_cites(text: str) -> str:
    r"""Turn the model's [[key]] markers into \cite{key}.

    We ask for brackets rather than LaTeX because a backslash inside a JSON
    string is an escape: a model writing "\textcite{x}" yields a literal tab
    plus "extcite{x}", and "\cite{x}" is an invalid escape that can break
    parsing outright. The repairs below catch models that reach for LaTeX
    anyway.
    """
    text = _BRACKET_CITE.sub(r"\\cite{\1}", text)
    text = text.replace("\textcite{", "\\cite{")   # literal tab + "extcite{"
    text = text.replace("\textbackslash cite{", "\\cite{")
    # A bare "cite{key}" with its backslash eaten during decoding.
    text = re.sub(r"(?<![\\\w])cite\{([A-Za-z0-9_:\-]+)\}", r"\\cite{\1}", text)
    return text


async def build_related_work(
    topic: str,
    papers: list[Paper],
    extractions: dict[str, Extraction],
) -> RelatedWork:
    taken: set[str] = set()
    keys = {paper.id: cite_key(paper, taken) for paper in papers}

    blocks = []
    for paper in papers:
        context, _ = _paper_context(paper, extractions.get(paper.id))
        blocks.append(f"[[{keys[paper.id]}]] — {context[:2000]}")

    result = await parse_json(
        RelatedWorkOut,
        system=(
            "You draft the Related Work section of an academic paper. Group the given "
            "papers into themes and write one flowing academic paragraph per theme that "
            "compares and contrasts them — never a list of one-sentence summaries. Cite "
            "papers inline using double square brackets around the exact key supplied, "
            "like [[smith2024method]]. Never write a backslash or any LaTeX command. "
            "Every paper must be cited at least once. Write in the present tense, third "
            "person, no first-person pronouns, no marketing language. Finish with a gap "
            "statement."
        ),
        user=f"Topic: {topic}\n\nPapers (each prefixed by its citation key):\n\n"
        + "\n\n".join(blocks),
        max_tokens=3000,
    )

    paragraphs = [
        RelatedWorkParagraph(theme=p.theme, text=_to_latex_cites(p.text))
        for p in result.paragraphs
    ]
    bibtex = "\n\n".join(to_bibtex(paper, keys[paper.id]) for paper in papers)
    return RelatedWork(
        paragraphs=paragraphs,
        gap_statement=_to_latex_cites(result.gap_statement),
        bibtex=bibtex,
        keys=keys,
        paper_ids=[paper.id for paper in papers],
    )


# ---------------------------------------------------------------------------
# 3. Compare two papers
# ---------------------------------------------------------------------------

async def compare_papers(
    paper_a: Paper,
    paper_b: Paper,
    extractions: dict[str, Extraction],
) -> ComparisonOut:
    context_a, _ = _paper_context(paper_a, extractions.get(paper_a.id))
    context_b, _ = _paper_context(paper_b, extractions.get(paper_b.id))
    # Field-level descriptions are unreliable here: Ollama compiles the JSON
    # schema into a decoding grammar, so the model reliably sees field *names*
    # but not their descriptions. Spell out each field in the prompt instead.
    return await parse_json(
        ComparisonOut,
        system=(
            "You compare two research papers for someone deciding which to build on. "
            "Be specific and even-handed: name techniques and numbers rather than "
            "generalities, and make the 'when to use' guidance genuinely actionable. "
            "If the two papers address different problems, say so plainly.\n\n"
            "Fill each field as follows:\n"
            "- problem_a / problem_b: the GAP or CHALLENGE the paper attacks, in 1-2 "
            "sentences. Describe the difficulty in the world — never restate the "
            "paper's title, acronym, or method name here.\n"
            "- method_a / method_b: how the paper's approach works, 1-2 sentences.\n"
            "- results_a / results_b: headline findings with concrete numbers, "
            "datasets, and metrics where known.\n"
            "- strengths_a / strengths_b: where that paper is genuinely stronger.\n"
            "- limitations_a / limitations_b: its main weakness or scope limit.\n"
            "- key_difference: 2-3 sentences on the single most important difference.\n"
            "- when_to_use_a / when_to_use_b: one actionable sentence each."
        ),
        user=(
            f"=== PAPER A: {paper_a.title} ===\n{context_a[:7000]}\n\n"
            f"=== PAPER B: {paper_b.title} ===\n{context_b[:7000]}"
        ),
        max_tokens=2500,
    )


# ---------------------------------------------------------------------------
# 4. Diff two of the reader's own past searches
# ---------------------------------------------------------------------------

def _paper_briefs(ids: set[str], papers: dict[str, Paper]) -> list[dict]:
    return sorted(
        ({"id": pid, "title": papers[pid].title} for pid in ids if pid in papers),
        key=lambda p: p["title"],
    )


def diff_searches(a: dict, b: dict, papers: dict[str, Paper]) -> dict:
    """Structural diff between two saved searches — free, no LLM call.

    Re-running the same query later (or running a related one) produces a new
    synthesis over a library that has grown since; this shows what actually
    changed rather than making the reader eyeball two overviews side by side.
    """
    a_ids, b_ids = set(a.get("paper_ids", [])), set(b.get("paper_ids", []))
    a_clusters = {c["name"] for c in a.get("clusters", [])}
    b_clusters = {c["name"] for c in b.get("clusters", [])}
    a_consensus = set(a.get("consensus", []))
    b_consensus = set(b.get("consensus", []))
    a_tensions = {t["name"] for t in a.get("tensions", [])}
    b_tensions = {t["name"] for t in b.get("tensions", [])}
    a_problems = {p["title"] for p in a.get("open_problems", [])}
    b_problems = {p["title"] for p in b.get("open_problems", [])}

    def meta(search: dict, ids: set[str]) -> dict:
        return {
            "id": search["id"],
            "query": search["query"],
            "title": search["title"],
            "created_at": search["created_at"],
            "paper_count": len(ids),
        }

    return {
        "a": meta(a, a_ids),
        "b": meta(b, b_ids),
        "shared_paper_count": len(a_ids & b_ids),
        "new_papers": _paper_briefs(b_ids - a_ids, papers),
        "dropped_papers": _paper_briefs(a_ids - b_ids, papers),
        "clusters_added": sorted(b_clusters - a_clusters),
        "clusters_removed": sorted(a_clusters - b_clusters),
        "consensus_added": sorted(b_consensus - a_consensus),
        "consensus_removed": sorted(a_consensus - b_consensus),
        "tensions_added": sorted(b_tensions - a_tensions),
        "tensions_removed": sorted(a_tensions - b_tensions),
        "open_problems_added": sorted(b_problems - a_problems),
        "open_problems_removed": sorted(a_problems - b_problems),
    }


# ---------------------------------------------------------------------------
# 5. Field report export
# ---------------------------------------------------------------------------

_STAGE_LABEL = {"foundation": "Foundations", "core": "Core methods", "frontier": "Frontier"}


def build_field_report(search: dict, papers: dict[str, Paper], card_stats: dict) -> str:
    """Bundle a search's landscape + reading order + flashcard progress into
    one exportable Markdown document — no LLM call, everything here already
    exists from earlier synthesis and study-deck use.
    """
    lines: list[str] = [f"# {search.get('title') or search.get('query')}", ""]
    lines.append(
        f'*Field report generated {date.today().isoformat()} · query: '
        f'"{search.get("query", "")}" · {len(search.get("paper_ids") or [])} papers*'
    )
    lines.append("")

    if search.get("overview"):
        lines += ["## Overview", "", search["overview"], ""]

    if search.get("clusters"):
        lines += ["## Method clusters", ""]
        for cluster in search["clusters"]:
            lines.append(f"### {cluster['name']}")
            lines.append("")
            if cluster.get("description"):
                lines += [cluster["description"], ""]
            for pid in cluster.get("paper_ids") or []:
                paper = papers.get(pid)
                if paper is None:
                    continue
                authors = ", ".join(paper.authors[:3]) + (" et al." if len(paper.authors) > 3 else "")
                lines.append(f"- [{paper.title}]({paper.arxiv_url}) — {authors} ({paper.published[:4]})")
            lines.append("")

    if search.get("tensions"):
        lines += ["## Tensions", ""]
        for tension in search["tensions"]:
            lines.append(f"**{tension['name']}** — {tension.get('description', '')}")
            lines.append("")

    if search.get("consensus"):
        lines += ["## Consensus", ""]
        lines += [f"- {statement}" for statement in search["consensus"]]
        lines.append("")

    if search.get("open_problems"):
        lines += ["## Open problems", ""]
        for problem in search["open_problems"]:
            lines.append(f"**{problem['title']}** — {problem.get('description', '')}")
            lines.append("")

    if search.get("reading_order"):
        lines += ["## Suggested reading order", ""]
        for stage_key, stage_label in _STAGE_LABEL.items():
            steps = [s for s in search["reading_order"] if s.get("stage") == stage_key]
            if not steps:
                continue
            lines.append(f"### {stage_label}")
            lines.append("")
            for index, step in enumerate(steps, start=1):
                paper = papers.get(step["paper_id"])
                title = paper.title if paper else step["paper_id"]
                lines.append(f"{index}. **{title}** — {step.get('why', '')}")
            lines.append("")

    lines += ["## Study progress", ""]
    lines.append(
        f"- {card_stats['total']} flashcards "
        f"({card_stats['relationship']} relationship, {card_stats['per_paper']} per-paper)"
    )
    lines.append(f"- {card_stats['reviewed']} reviewed at least once · {card_stats['due']} due now")
    if card_stats.get("avg_score") is not None:
        lines.append(f"- Average score so far: {card_stats['avg_score']:.0f}/100")
    lines.append("")

    return "\n".join(lines)
