"""Field digests - what changed in a followed search since it was built."""

from __future__ import annotations

from datetime import datetime

from llm import parse_json
from models import (
    Digest,
    DigestHighlight,
    DigestOut,
    Extraction,
    Paper,
)

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
            "  Â· index = the paper's [index] from the list below\n"
            "  Â· why_it_matters = one full sentence on its significance\n"
            "  Â· relation = one full SENTENCE explaining how it connects to the existing "
            "themes or papers â€” never a bare label like 'Complementary'\n"
            "  Â· challenges_consensus = true ONLY if it contradicts or complicates one of "
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
