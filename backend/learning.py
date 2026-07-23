"""Learning loop — flashcards, spaced repetition, quiz grading, field digests."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import store
from llm import parse_json
from models import (
    Digest,
    DigestHighlight,
    DigestOut,
    Extraction,
    Flashcard,
    FlashcardSetOut,
    GradeOut,
    Paper,
)

# ---------------------------------------------------------------------------
# Card generation
# ---------------------------------------------------------------------------

def _glossary_cards(paper_id: str, deep: dict) -> list[Flashcard]:
    """Definition cards come straight from the glossary — no LLM call needed."""
    cards: list[Flashcard] = []
    for index, term in enumerate(deep.get("glossary") or []):
        name = (term.get("term") or "").strip()
        definition = (term.get("definition") or "").strip()
        if not name or not definition:
            continue
        usage = (term.get("in_this_paper") or "").strip()
        cards.append(
            Flashcard(
                id=f"{paper_id}:def:{index}",
                paper_id=paper_id,
                question=f"What is {name}?",
                answer=definition + (f" In this paper: {usage}" if usage else ""),
                kind="definition",
            )
        )
    return cards


_EDGE_VERB = {
    "builds_on": "build on",
    "compares_to": "compare to",
    "complements": "complement",
    "evaluates": "evaluate",
    "extends": "extend",
}


def relationship_cards(search: dict, papers: dict[str, Paper]) -> list[Flashcard]:
    """Cross-paper cards from a search's own relationship edges — no LLM call.

    Definition/concept/result/critique cards test one paper at a time; these
    test whether the reader understands how the papers in a cluster relate to
    each other. The edge descriptions already exist from landscape synthesis,
    so this is free and instant rather than another generation pass.
    """
    cards: list[Flashcard] = []
    for index, edge in enumerate(search.get("edges") or []):
        source = papers.get(edge.get("source", ""))
        target = papers.get(edge.get("target", ""))
        description = (edge.get("description") or "").strip()
        if not source or not target or not description:
            continue
        verb = _EDGE_VERB.get(edge.get("kind", ""), "relate to")
        cards.append(
            Flashcard(
                # /api/cards/grade extracts the paper id from the part of a
                # card id before the first colon — matching that convention
                # (source id first) is what makes a relationship card gradable.
                id=f"{source.id}:rel:{search['id']}:{index}",
                paper_id=source.id,
                related_paper_id=target.id,
                question=f'How does "{source.title}" {verb} "{target.title}"?',
                answer=description,
                kind="relationship",
            )
        )
    return cards


async def generate_cards(paper: Paper, extraction: Extraction | None) -> list[Flashcard]:
    deep = store.load_deep_dive(paper.id)
    cards: list[Flashcard] = []

    if deep:
        cards.extend(_glossary_cards(paper.id, deep))
        context = (
            f"Synthesis: {deep.get('deep_summary', '')}\n"
            f"Contributions: {'; '.join(deep.get('contributions') or [])}\n"
            f"Results: {deep.get('results_detail', '')}\n"
            f"Not solved: {(deep.get('critique') or {}).get('not_solved', '')}\n"
            f"Weaknesses: {'; '.join((deep.get('critique') or {}).get('weaknesses') or [])}"
        )
    elif extraction:
        context = (
            f"Summary: {extraction.tldr}\nProblem: {extraction.problem}\n"
            f"Method: {extraction.method}\nResults: {extraction.key_results}\n"
            f"Significance: {extraction.why_it_matters}"
        )
    else:
        context = paper.abstract

    result = await parse_json(
        FlashcardSetOut,
        system=(
            "You write flashcards that test real understanding of a research paper, for a "
            "student revising for an exam or a group meeting.\n\n"
            "Rules for every card:\n"
            "- question: self-contained. A student must be able to answer it without seeing "
            "the paper title, so name the specific method or setting inside the question.\n"
            "- answer: 1-3 sentences, complete on its own, with concrete numbers when they exist.\n"
            "- kind: 'concept' for how/why a mechanism works, 'result' for what was measured "
            "and found, 'critique' for limitations and assumptions.\n"
            "Ask 'why' and 'how' rather than 'what did the authors call X'. Never write a "
            "yes/no question. Cover a mix of kinds."
        ),
        user=f"Paper: {paper.title}\n\n{context[:9000]}",
        max_tokens=2000,
    )

    for index, card in enumerate(result.cards):
        cards.append(
            Flashcard(
                id=f"{paper.id}:gen:{index}",
                paper_id=paper.id,
                question=card.question,
                answer=card.answer,
                kind=card.kind,
            )
        )
    return cards


# ---------------------------------------------------------------------------
# Spaced repetition (SM-2 lite)
# ---------------------------------------------------------------------------

def schedule(card: Flashcard, verdict: str, score: int) -> Flashcard:
    """Update a card's review state from a grade. Intervals are in days."""
    today = date.today()
    if verdict == "incorrect":
        card.lapses += 1
        card.ease = max(1.3, card.ease - 0.2)
        card.interval = 1
    elif verdict == "partial":
        card.ease = max(1.3, card.ease - 0.05)
        card.interval = max(1, round(card.interval * 1.2)) if card.reps else 1
    else:
        card.ease = min(3.0, card.ease + 0.1)
        if card.reps == 0:
            card.interval = 1
        elif card.reps == 1:
            card.interval = 3
        else:
            card.interval = max(1, round(card.interval * card.ease))
    card.reps += 1
    card.last_score = score
    card.due = (today + timedelta(days=card.interval)).isoformat()
    return card


def is_due(card: Flashcard, today: date | None = None) -> bool:
    if not card.due:
        return True                       # never reviewed
    today = today or date.today()
    try:
        return datetime.fromisoformat(card.due).date() <= today
    except ValueError:
        return True


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

async def grade_answer(
    paper: Paper, card: Flashcard, user_answer: str
) -> GradeOut:
    return await parse_json(
        GradeOut,
        system=(
            "You grade a student's free-text answer against the reference answer from a "
            "research paper.\n\n"
            "Judge understanding, not wording: accept paraphrases, synonyms, and partial "
            "credit. Mark 'correct' when the core idea is right even if brief; 'partial' "
            "when it is on the right track but misses something important; 'incorrect' "
            "when the core idea is wrong or absent.\n"
            "Fill each field as follows:\n"
            "- verdict: correct | partial | incorrect\n"
            "- score: 0-100 for completeness and accuracy\n"
            "- feedback: 2-3 sentences addressed to the student as 'you', direct and "
            "encouraging, naming what was right before what was missing\n"
            "- missed: the specific points omitted or wrong; empty list if fully correct"
        ),
        user=(
            f"Paper: {paper.title}\n\n"
            f"Question: {card.question}\n\n"
            f"Reference answer: {card.answer}\n\n"
            f"Student's answer: {user_answer}"
        ),
        max_tokens=900,
    )


# ---------------------------------------------------------------------------
# Anki export
# ---------------------------------------------------------------------------

def _anki_clean(text: str) -> str:
    """Anki's basic importer is TSV; tabs and newlines break the row."""
    return re.sub(r"\s+", " ", text).replace("\t", " ").strip()


def to_anki_tsv(cards: list[Flashcard], papers: dict[str, Paper]) -> str:
    """Notes as TSV: Front, Back, Tags. Import with 'Fields separated by: Tab'."""
    lines = ["#separator:tab", "#html:false", "#tags column:3"]
    for card in cards:
        paper = papers.get(card.paper_id)
        source = f" ({paper.title})" if paper else ""
        tags = f"research-copilot {card.kind} arxiv-{card.paper_id.replace('.', '-')}"
        lines.append(
            "\t".join(
                [
                    _anki_clean(card.question),
                    _anki_clean(card.answer + source),
                    tags,
                ]
            )
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Field digest
# ---------------------------------------------------------------------------

async def build_digest(
    search: dict,
    new_papers: list[Paper],
    extractions: dict[str, Extraction],
    checked_count: int,
) -> Digest:
    consensus = "\n".join(f"- {c}" for c in search.get("consensus") or [])
    clusters = "\n".join(
        f"- {c['name']}: {c.get('description', '')}" for c in search.get("clusters") or []
    )
    listing = "\n\n".join(
        f"[{index}] {paper.title} ({paper.published})\n"
        + (extractions[paper.id].tldr if paper.id in extractions else paper.abstract[:300])
        for index, paper in enumerate(new_papers, start=1)
    )

    # Field descriptions don't reach the model under Ollama's grammar-based
    # structured output, so each field is specified here instead.
    result = await parse_json(
        DigestOut,
        system=(
            "You write a short 'what's new in this field' digest for a researcher who "
            "already knows the existing collection. Be selective and concrete: say what "
            "actually changed, not that papers exist.\n\n"
            "Fill each field as follows:\n"
            "- headline: one sentence naming what changed, e.g. '3 new papers, one "
            "challenges the consensus on retrieval noise'.\n"
            "- summary: 3-5 sentences on how the field moved.\n"
            "- highlights: one entry per genuinely notable new paper, where\n"
            "  · index = the paper's [index] from the list below\n"
            "  · why_it_matters = one full sentence on its significance\n"
            "  · relation = one full SENTENCE explaining how it connects to the existing "
            "themes or papers — never a bare label like 'Complementary'\n"
            "  · challenges_consensus = true ONLY if it contradicts or complicates one of "
            "the listed consensus points"
        ),
        user=(
            f"Field: {search.get('title') or search.get('query')}\n\n"
            f"Existing themes:\n{clusters}\n\n"
            f"Existing consensus:\n{consensus}\n\n"
            f"New papers found since the collection was built:\n\n{listing}"
        ),
        max_tokens=2000,
    )

    highlights: list[DigestHighlight] = []
    for item in result.highlights:
        if 1 <= item.index <= len(new_papers):
            highlights.append(
                DigestHighlight(
                    paper_id=new_papers[item.index - 1].id,
                    why_it_matters=item.why_it_matters,
                    challenges_consensus=item.challenges_consensus,
                    relation=item.relation,
                )
            )

    return Digest(
        search_id=search["id"],
        query=search.get("query", ""),
        created_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        checked_count=checked_count,
        new_paper_ids=[p.id for p in new_papers],
        headline=result.headline,
        summary=result.summary,
        highlights=highlights,
    )
