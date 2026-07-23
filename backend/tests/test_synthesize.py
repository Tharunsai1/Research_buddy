"""Pure helpers behind the map.

_partition_map is the core of the incremental clustering that replaced a full
library re-cluster on every search — the change that took a Stable Diffusion
search from hanging near the 300s provider timeout down to ~36s for the map
stage. If it starts handing back the whole library as "pending", that cost
comes straight back, so its behaviour is pinned here.
"""

from __future__ import annotations

import pytest

from models import Extraction
from synthesize import UNSORTED, _clean_edges, _partition_map, _topic_cluster_name
from tests.conftest import make_paper


def extraction(tldr: str = "A paper.") -> Extraction:
    return Extraction(
        tldr=tldr,
        problem="A gap.",
        method="A method.",
        key_results="Some results.",
        why_it_matters="It matters.",
        keywords=["one", "two", "three"],
        paper_type="method",
    )


@pytest.fixture
def library():
    papers = [
        make_paper("2006.11239", "DDPM"),
        make_paper("1706.03762", "Attention"),
        make_paper("2005.11401", "RAG"),
    ]
    return papers, {p.id: extraction() for p in papers}


# ---------------------------------------------------------------------------
# _topic_cluster_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "topic, expected",
    [
        ("stable diffusion", "Stable Diffusion"),
        ("  stable   diffusion  ", "Stable Diffusion"),
        # Existing capitalisation is load-bearing: .title() would mangle these
        # into "Mcp Servers" and "Llm Agents".
        ("MCP servers", "MCP servers"),
        ("LLM agents", "LLM agents"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_topic_cluster_name(topic, expected):
    assert _topic_cluster_name(topic) == expected


def test_topic_cluster_name_is_bounded():
    assert len(_topic_cluster_name("a very long topic " * 10)) <= 40


# ---------------------------------------------------------------------------
# _partition_map
# ---------------------------------------------------------------------------

def test_only_unmapped_papers_are_pending(library):
    """The whole point: an existing map means the LLM is asked about the new
    arrivals only, not the entire library."""
    papers, extractions = library
    current = {"clusters": [{"name": "Generative", "paper_ids": ["2006.11239"]}]}
    settled, pending = _partition_map(papers, extractions, current)
    assert settled == [{"name": "Generative", "paper_ids": ["2006.11239"]}]
    assert [p.id for p in pending] == ["1706.03762", "2005.11401"]


def test_an_empty_map_leaves_everything_pending(library):
    papers, extractions = library
    settled, pending = _partition_map(papers, extractions, {"clusters": []})
    assert settled == []
    assert len(pending) == 3


def test_a_fully_mapped_library_has_nothing_pending(library):
    papers, extractions = library
    current = {"clusters": [{"name": "All", "paper_ids": [p.id for p in papers]}]}
    settled, pending = _partition_map(papers, extractions, current)
    assert pending == []
    assert settled[0]["paper_ids"] == [p.id for p in papers]


def test_unsorted_papers_get_another_chance_at_a_real_cluster(library):
    papers, extractions = library
    current = {
        "clusters": [
            {"name": "Generative", "paper_ids": ["2006.11239"]},
            {"name": UNSORTED, "paper_ids": ["1706.03762"]},
        ]
    }
    settled, pending = _partition_map(papers, extractions, current)
    assert [c["name"] for c in settled] == ["Generative"]
    assert "1706.03762" in [p.id for p in pending]


def test_papers_removed_from_the_library_drop_out_of_settled_clusters(library):
    """remove_paper can delete a paper the stored map still references."""
    papers, extractions = library
    current = {"clusters": [{"name": "Generative", "paper_ids": ["2006.11239", "gone.00000"]}]}
    settled, _ = _partition_map(papers, extractions, current)
    assert settled[0]["paper_ids"] == ["2006.11239"]


def test_a_cluster_left_empty_is_dropped_entirely(library):
    papers, extractions = library
    current = {"clusters": [{"name": "Ghost", "paper_ids": ["gone.00000"]}]}
    settled, pending = _partition_map(papers, extractions, current)
    assert settled == []
    assert len(pending) == 3


def test_papers_without_an_extraction_are_not_offered_for_placement(library):
    """Placement prompts are built from extractions; a paper without one has
    nothing to show the model."""
    papers, extractions = library
    del extractions["2005.11401"]
    _, pending = _partition_map(papers, extractions, {"clusters": []})
    assert [p.id for p in pending] == ["2006.11239", "1706.03762"]


# ---------------------------------------------------------------------------
# _clean_edges
# ---------------------------------------------------------------------------

def edge(source: int, target: int):
    from models import EdgeOut

    return EdgeOut(source=source, target=target, kind="builds_on", description="d")


def test_edges_pointing_outside_the_paper_list_are_dropped():
    assert _clean_edges([edge(1, 99), edge(0, 2), edge(1, 2)], 3) == [edge(1, 2)]


def test_self_edges_are_dropped():
    assert _clean_edges([edge(2, 2)], 3) == []


def test_duplicate_pairs_are_collapsed_regardless_of_direction():
    cleaned = _clean_edges([edge(1, 2), edge(2, 1), edge(1, 3)], 3)
    assert [(e.source, e.target) for e in cleaned] == [(1, 2), (1, 3)]
