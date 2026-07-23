"""Chat with a paper — local retrieval over its full text, answers with citations."""

from __future__ import annotations

import math

from fulltext import FullText, chunk_for_embedding
from llm import embed_texts, parse_json
from models import ChatAnswer, ChatOut, ChatSource, Paper

TOP_K = 5


async def build_index(full: FullText) -> list[dict]:
    """Chunk + embed a paper. Returns records ready to persist."""
    chunks = chunk_for_embedding(full)
    if not chunks:
        return []
    vectors = await embed_texts([c["text"] for c in chunks])
    return [
        {"section": c["section"], "text": c["text"], "embedding": v}
        for c, v in zip(chunks, vectors)
    ]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


async def answer_question(
    paper: Paper, question: str, index: list[dict], top_k: int = TOP_K
) -> ChatAnswer:
    if not index:
        raise ValueError("This paper has not been indexed yet.")

    query_vector = (await embed_texts([question], is_query=True))[0]
    scored = sorted(
        ((_cosine(query_vector, record["embedding"]), record) for record in index),
        key=lambda pair: pair[0],
        reverse=True,
    )[:top_k]

    excerpts = "\n\n".join(
        f"[{i}] (from “{record['section']}”)\n{record['text']}"
        for i, (_, record) in enumerate(scored, start=1)
    )

    result = await parse_json(
        ChatOut,
        system=(
            "You answer questions about a specific research paper using only the excerpts "
            "provided from its full text. Cite excerpts inline as [1], [2]. Quote short "
            "phrases and keep exact numbers. If the excerpts genuinely do not answer the "
            "question, say so and point to the closest relevant part instead of guessing."
        ),
        user=(
            f"Paper: {paper.title}\n\nExcerpts from the paper:\n\n{excerpts}\n\n"
            f"Question: {question}"
        ),
        max_tokens=1200,
    )

    return ChatAnswer(
        answer=result.answer,
        sources=[
            ChatSource(section=record["section"], text=record["text"], score=round(score, 3))
            for score, record in scored
        ],
    )
