"""Chat-with-paper, with and without a highlighted-passage anchor.

The anchor is the reader's own literal selection — injected verbatim as
excerpt [0] rather than searched for, since retrieval over the chunk index
could rank the exact highlighted sentence lower than a paraphrase elsewhere,
or miss it entirely if the selection crosses a chunk boundary. embed_texts
and parse_json are stubbed throughout; no network, no Ollama, no OpenRouter.
"""

from __future__ import annotations

import pytest

import chat
from models import ChatOut
from tests.conftest import make_paper


def index_of(*sections: str) -> list[dict]:
    """One fake indexed chunk per section, each with a distinct embedding
    axis so cosine ranking is deterministic and inspectable."""
    return [
        {"section": name, "text": f"Text from {name}.", "embedding": vec}
        for name, vec in zip(sections, ([1, 0, 0], [0, 1, 0], [0, 0, 1]))
    ]


@pytest.fixture
def paper():
    return make_paper("2401.15884", "CRAG")


@pytest.fixture
def llm_stub(monkeypatch):
    """Query embeddings mirror the corresponding chunk's axis so the top
    match is predictable; parse_json records what it was called with."""
    calls: dict = {}

    async def fake_embed(texts, is_query=False):
        calls["embed_input"] = list(texts)
        calls["embed_is_query"] = is_query
        return [[1, 0, 0] for _ in texts]

    async def fake_parse_json(schema, system, user, max_tokens):
        calls["system"] = system
        calls["user"] = user
        return ChatOut(answer="The paper reports 78% accuracy.", used_excerpts=[1])

    monkeypatch.setattr(chat, "embed_texts", fake_embed)
    monkeypatch.setattr(chat, "parse_json", fake_parse_json)
    return calls


# ---------------------------------------------------------------------------
# No anchor — must behave exactly as before this feature existed
# ---------------------------------------------------------------------------

async def test_no_anchor_numbers_excerpts_from_one(paper, llm_stub):
    await chat.answer_question(paper, "What accuracy?", index_of("Intro", "Results"), top_k=2)
    assert "[1] (from" in llm_stub["user"]
    assert "[0]" not in llm_stub["user"]


async def test_no_anchor_omits_the_highlighted_passage_instruction(paper, llm_stub):
    await chat.answer_question(paper, "What accuracy?", index_of("Intro"))
    assert "highlighted" not in llm_stub["system"].lower()


async def test_no_anchor_embeds_the_bare_question(paper, llm_stub):
    await chat.answer_question(paper, "What accuracy?", index_of("Intro"))
    assert llm_stub["embed_input"] == ["What accuracy?"]
    assert llm_stub["embed_is_query"] is True


async def test_no_anchor_produces_no_highlighted_source(paper, llm_stub):
    answer = await chat.answer_question(paper, "What accuracy?", index_of("Intro"))
    assert all(s.section != "Highlighted passage" for s in answer.sources)


async def test_an_empty_index_still_raises(paper, llm_stub):
    with pytest.raises(ValueError):
        await chat.answer_question(paper, "q", [])


# ---------------------------------------------------------------------------
# With an anchor
# ---------------------------------------------------------------------------

ANCHOR = "the retrieval evaluator was trained only on PopQA"


async def test_the_anchor_is_injected_as_excerpt_zero_verbatim(paper, llm_stub):
    await chat.answer_question(
        paper, "Does this hold for other datasets?", index_of("Intro"), anchor=ANCHOR
    )
    assert f"[0] (the passage you highlighted)\n{ANCHOR}" in llm_stub["user"]


async def test_retrieved_excerpts_are_numbered_one_and_two_after_the_anchor(paper, llm_stub):
    """The anchor claims [0] exclusively; retrieved excerpts still start at
    [1] rather than being pushed to [2] — numbering must not skip 1."""
    await chat.answer_question(
        paper, "q", index_of("Intro", "Results"), top_k=2, anchor=ANCHOR
    )
    assert "[1] (from" in llm_stub["user"]
    assert "[2] (from" in llm_stub["user"]
    assert "[3]" not in llm_stub["user"]


async def test_the_anchor_folds_into_the_retrieval_query(paper, llm_stub):
    """Retrieval should surface context for the highlighted passage, not
    just for the bare question — the whole point of anchoring."""
    await chat.answer_question(paper, "Is this a limitation?", index_of("Intro"), anchor=ANCHOR)
    assert llm_stub["embed_input"] == [f"{ANCHOR}\n\nIs this a limitation?"]


async def test_the_system_prompt_tells_the_model_excerpt_zero_is_the_anchor(paper, llm_stub):
    await chat.answer_question(paper, "q", index_of("Intro"), anchor=ANCHOR)
    assert "excerpt [0]" in llm_stub["system"].lower()
    assert "primary anchor" in llm_stub["system"]


async def test_the_highlighted_passage_becomes_the_first_source(paper, llm_stub):
    answer = await chat.answer_question(paper, "q", index_of("Intro"), anchor=ANCHOR)
    assert answer.sources[0].section == "Highlighted passage"
    assert answer.sources[0].text == ANCHOR
    assert answer.sources[0].score == 1.0


async def test_retrieved_sources_still_follow_the_highlighted_one(paper, llm_stub):
    answer = await chat.answer_question(
        paper, "q", index_of("Intro", "Results"), top_k=2, anchor=ANCHOR
    )
    assert len(answer.sources) == 3
    assert [s.section for s in answer.sources[1:]] == ["Intro", "Results"]


async def test_an_empty_index_still_raises_with_an_anchor(paper, llm_stub):
    with pytest.raises(ValueError):
        await chat.answer_question(paper, "q", [], anchor=ANCHOR)
