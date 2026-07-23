"""Shared fixtures.

The one rule that matters here: a test must never touch backend/data/. That
directory is the user's real library — papers, deep dives, flashcard review
history — and `remove_paper` deletes files for a living. Every test that
reaches the storage layer goes through `isolated_store`, which repoints all of
store.py's path constants at a tmp directory and swaps in an empty collection.
"""

from __future__ import annotations

import json

import pytest

import store
from models import Paper

# Path constants in store.py are read from module scope inside each function,
# so monkeypatching the module attribute is enough to redirect every write.
_STORE_PATHS = [
    "DATA_DIR",
    "SEARCHES_DIR",
    "DEEP_DIR",
    "INDEX_DIR",
    "S2_DIR",
    "MATRIX_DIR",
    "CARDS_DIR",
    "DIGEST_DIR",
]


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Redirect the storage layer at a tmp dir with an empty collection."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(store, "DATA_DIR", root)
    for name in _STORE_PATHS[1:]:
        monkeypatch.setattr(store, name, root / name.replace("_DIR", "").lower())
    monkeypatch.setattr(store, "COLLECTION_FILE", root / "collection.json")
    monkeypatch.setattr(store, "SETTINGS_FILE", root / "settings.json")
    monkeypatch.setattr(store, "_collection", json.loads(json.dumps(store._EMPTY)))
    return store


def make_paper(paper_id: str, title: str, published: str = "2020-06-19") -> Paper:
    return Paper(
        id=paper_id,
        title=title,
        authors=["A. Researcher", "B. Coauthor"],
        abstract=f"We study {title}.",
        published=published,
        categories=["cs.LG"],
        primary_category="cs.LG",
        arxiv_url=f"https://arxiv.org/abs/{paper_id}",
        pdf_url=f"https://arxiv.org/pdf/{paper_id}",
    )


@pytest.fixture
def papers() -> dict[str, Paper]:
    """A small library, including a pre-2007 id whose slash has broken
    routing and file writes before (see store._safe)."""
    return {
        p.id: p
        for p in [
            make_paper("2006.11239", "Denoising Diffusion Probabilistic Models", "2020-06-19"),
            make_paper("1706.03762", "Attention Is All You Need", "2017-06-12"),
            make_paper("2005.11401", "Retrieval-Augmented Generation", "2020-05-22"),
            make_paper("quant-ph/9903061", "Quantum Algorithms: An Overview", "1999-03-18"),
        ]
    }


@pytest.fixture
def search_a() -> dict:
    return {
        "id": "llm-agents-aaa111",
        "query": "LLM agents",
        "title": "LLM Agents",
        "created_at": "2026-07-12T10:00:00",
        "paper_ids": ["1706.03762", "2005.11401"],
        "overview": "An early look at agent architectures.",
        "clusters": [
            {
                "name": "Attention architectures",
                "description": "Transformer foundations.",
                "paper_ids": ["1706.03762"],
            },
            {
                "name": "Retrieval",
                "description": "Grounding generation in documents.",
                "paper_ids": ["2005.11401"],
            },
        ],
        "edges": [
            {
                "source": "2005.11401",
                "target": "1706.03762",
                "kind": "builds_on",
                "description": "RAG uses the transformer as its generator backbone.",
            }
        ],
        "reading_order": [
            {"paper_id": "1706.03762", "stage": "foundation", "why": "The base architecture."},
            {"paper_id": "2005.11401", "stage": "core", "why": "Adds retrieval."},
        ],
        "consensus": ["Scaling helps.", "Retrieval reduces hallucination."],
        "tensions": [{"name": "Cost vs quality", "description": "Bigger is dearer."}],
        "open_problems": [{"title": "Long-horizon planning", "description": "Still unsolved."}],
    }


@pytest.fixture
def search_b() -> dict:
    return {
        "id": "llm-agents-bbb222",
        "query": "LLM agents",
        "title": "LLM Agents",
        "created_at": "2026-07-23T10:00:00",
        "paper_ids": ["2005.11401", "2006.11239"],
        "overview": "A later look, after diffusion entered the picture.",
        "clusters": [
            {
                "name": "Retrieval",
                "description": "Grounding generation in documents.",
                "paper_ids": ["2005.11401"],
            },
            {
                "name": "Generative models",
                "description": "Diffusion-based generation.",
                "paper_ids": ["2006.11239"],
            },
        ],
        "edges": [],
        "reading_order": [
            {"paper_id": "2005.11401", "stage": "foundation", "why": "Retrieval basics."},
        ],
        "consensus": ["Retrieval reduces hallucination.", "Tool use is essential."],
        "tensions": [{"name": "Autonomy vs control", "description": "Who is in charge."}],
        "open_problems": [{"title": "Evaluation", "description": "No agreed benchmark."}],
    }
