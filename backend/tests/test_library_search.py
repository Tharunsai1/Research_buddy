"""Semantic search over the library — cosine ranking and incremental
embedding. embed_texts is stubbed throughout; no Ollama calls."""

from __future__ import annotations

import pytest

import library_search
from tests.conftest import make_paper


def extraction(tldr="A paper.", keywords=("one", "two", "three")):
    from models import Extraction

    return Extraction(
        tldr=tldr, problem="p", method="m", key_results="r", why_it_matters="w",
        keywords=list(keywords), paper_type="method",
    )


@pytest.fixture
def embedder(monkeypatch):
    """Deterministic vectors: one axis per distinct word so cosine similarity
    is predictable without a real model."""
    vocab: dict[str, int] = {}

    def vectorize(text: str) -> list[float]:
        vec = [0.0] * 64
        for word in text.lower().split():
            idx = vocab.setdefault(word, len(vocab) % 64)
            vec[idx] += 1.0
        return vec

    calls = []

    async def fake_embed(texts, is_query=False):
        calls.append((list(texts), is_query))
        return [vectorize(t) for t in texts]

    monkeypatch.setattr(library_search, "embed_texts", fake_embed)
    return calls


# ---------------------------------------------------------------------------
# _paper_text
# ---------------------------------------------------------------------------

def test_paper_text_prefers_the_extraction():
    p = make_paper("2006.11239", "DDPM")
    text = library_search._paper_text(p, extraction(tldr="Denoising diffusion."))
    assert "Denoising diffusion." in text
    assert "one, two, three" in text


def test_paper_text_falls_back_to_the_abstract_without_an_extraction():
    p = make_paper("2006.11239", "DDPM")
    text = library_search._paper_text(p, None)
    assert p.title in text
    assert p.abstract in text


# ---------------------------------------------------------------------------
# _cosine
# ---------------------------------------------------------------------------

def test_cosine_of_identical_vectors_is_one():
    assert library_search._cosine([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)


def test_cosine_of_orthogonal_vectors_is_zero():
    assert library_search._cosine([1, 0], [0, 1]) == pytest.approx(0.0)


def test_cosine_handles_a_zero_vector_without_dividing_by_zero():
    assert library_search._cosine([0, 0], [1, 1]) == 0.0


# ---------------------------------------------------------------------------
# ensure_index — the incremental promise
# ---------------------------------------------------------------------------

async def test_only_papers_missing_from_the_index_are_embedded(isolated_store, embedder):
    papers = {"a.1": make_paper("a.1", "A"), "b.1": make_paper("b.1", "B")}
    isolated_store.save_library_index({"a.1": [1.0] * 64})
    await library_search.ensure_index(papers, {})
    (texts, is_query), = embedder
    assert len(texts) == 1, "the already-indexed paper must not be re-embedded"
    assert is_query is False


async def test_a_fully_indexed_library_makes_no_embed_call(isolated_store, embedder):
    papers = {"a.1": make_paper("a.1", "A")}
    isolated_store.save_library_index({"a.1": [1.0] * 64})
    await library_search.ensure_index(papers, {})
    assert embedder == []


async def test_the_index_persists_across_calls(isolated_store, embedder):
    papers = {"a.1": make_paper("a.1", "A")}
    await library_search.ensure_index(papers, {})
    assert "a.1" in isolated_store.load_library_index()


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

async def test_search_ranks_by_relevance(isolated_store, embedder):
    papers = {
        "diffusion.1": make_paper("diffusion.1", "Denoising Diffusion Models"),
        "attention.1": make_paper("attention.1", "Attention Is All You Need"),
    }
    extractions = {
        "diffusion.1": extraction(tldr="Diffusion models generate images via denoising."),
        "attention.1": extraction(tldr="Transformers use self attention for sequences."),
    }
    results = await library_search.search("diffusion denoising", papers, extractions)
    assert results[0]["paper_id"] == "diffusion.1"
    assert results[0]["score"] > results[1]["score"]


async def test_search_respects_the_limit(isolated_store, embedder):
    papers = {f"p.{i}": make_paper(f"p.{i}", f"Paper {i}") for i in range(5)}
    results = await library_search.search("paper", papers, {}, limit=2)
    assert len(results) == 2


async def test_an_empty_query_returns_nothing_without_calling_the_embedder(isolated_store, embedder):
    papers = {"a.1": make_paper("a.1", "A")}
    assert await library_search.search("   ", papers, {}) == []
    assert embedder == []


async def test_an_empty_library_returns_nothing_without_calling_the_embedder(isolated_store, embedder):
    assert await library_search.search("anything", {}, {}) == []
    assert embedder == []


async def test_a_stale_index_entry_does_not_eat_a_result_slot(isolated_store, embedder):
    """A removed paper can outlive its cached vector. Ranking over the raw
    index let that dead entry occupy a slot in the top-N, so the caller — which
    drops ids it cannot resolve — silently returned fewer than `limit` hits."""
    papers = {f"p.{i}": make_paper(f"p.{i}", f"Paper {i}") for i in range(3)}
    await library_search.search("warm the index", papers, {})

    index = isolated_store.load_library_index()
    index["ghost.1"] = [0.9] * len(next(iter(index.values())))
    isolated_store.save_library_index(index)

    results = await library_search.search("paper", papers, {}, limit=3)
    assert len(results) == 3
    assert all(hit["paper_id"] in papers for hit in results)


async def test_the_query_is_embedded_as_a_query_not_a_document(isolated_store, embedder):
    """nomic-embed-text expects different prefixes for queries vs documents
    (see llm.embed_texts) — mixing them up silently degrades every result."""
    papers = {"a.1": make_paper("a.1", "A")}
    await library_search.search("find me something", papers, {})
    query_calls = [c for c in embedder if c[1] is True]
    assert len(query_calls) == 1
    assert query_calls[0][0] == ["find me something"]
