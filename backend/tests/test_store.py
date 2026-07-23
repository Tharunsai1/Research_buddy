"""Storage layer: id-to-filename safety and the remove_paper undo path.

Every test here goes through the `isolated_store` fixture. remove_paper
deletes files, and the real backend/data/ holds the user's library.
"""

from __future__ import annotations

import json

import pytest

import store


# ---------------------------------------------------------------------------
# Paper id <-> filename
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "paper_id",
    ["2006.11239", "quant-ph/9903061", "cs.LG/0102003", "1706.03762v2"],
)
def test_safe_roundtrips_real_arxiv_ids(paper_id):
    """Pre-2007 ids carry a slash, which is a directory separator on disk.
    Rejecting them silently dropped every deep dive, card and citation record
    for those papers, so they must fold to a filename and back."""
    stem = store._safe(paper_id)
    assert stem is not None
    assert "/" not in stem
    assert store._unsafe(stem) == paper_id


@pytest.mark.parametrize(
    "paper_id",
    ["../../etc/passwd", "..", "2006.11239/..", "id with spaces", "id;rm -rf", ""],
)
def test_safe_rejects_ids_that_should_never_reach_the_filesystem(paper_id):
    assert store._safe(paper_id) is None


def test_a_rejected_id_writes_nothing(isolated_store, tmp_path):
    isolated_store.save_deep_dive("../escape", {"deep_summary": "nope"})
    assert isolated_store.load_deep_dive("../escape") is None
    assert not list(tmp_path.rglob("*escape*"))


def test_old_style_ids_survive_a_save_load_roundtrip(isolated_store):
    """The bug this guards: _safe() used to reject slashes, so save_deep_dive
    returned early and every write for these papers was a silent no-op."""
    isolated_store.save_deep_dive("quant-ph/9903061", {"deep_summary": "Overview."})
    assert isolated_store.load_deep_dive("quant-ph/9903061") == {"deep_summary": "Overview."}
    assert isolated_store.deep_dive_ids() == ["quant-ph/9903061"]


def test_deep_dives_built_from_the_landing_page_are_withheld(isolated_store):
    """Records written before fulltext.py rejected the /abs/ page summarised
    an abstract as if it were the paper. They read as confidently as any other
    record, so they must not be served — reopening offers a fresh read, which
    now refuses with an explanation."""
    isolated_store.save_deep_dive(
        "quant-ph/9903061",
        {"source_url": "https://arxiv.org/abs/quant-ph/9903061", "total_words": 509},
    )
    assert isolated_store.load_deep_dive("quant-ph/9903061") is None


def test_a_withheld_record_is_not_deleted(isolated_store):
    """Withholding is not destruction — the file stays for inspection."""
    isolated_store.save_deep_dive(
        "2307.15883", {"source_url": "https://arxiv.org/abs/2307.15883"}
    )
    assert (isolated_store.DEEP_DIR / "2307.15883.json").exists()


@pytest.mark.parametrize(
    "source_url",
    [
        "https://arxiv.org/html/2401.15884",
        "https://arxiv.org/html/1706.03762v1",
        "https://ar5iv.labs.arxiv.org/html/quant-ph/9903061",
    ],
)
def test_real_deep_dives_are_served_normally(isolated_store, source_url):
    isolated_store.save_deep_dive("x.1", {"source_url": source_url, "total_words": 6000})
    assert isolated_store.load_deep_dive("x.1") is not None


def test_a_record_without_a_source_url_is_still_served(isolated_store):
    """Absent metadata is not evidence of the bug; don't withhold on a guess."""
    isolated_store.save_deep_dive("x.2", {"deep_summary": "..."})
    assert isolated_store.load_deep_dive("x.2") is not None


def test_cards_roundtrip_for_old_style_ids(isolated_store):
    isolated_store.save_cards("quant-ph/9903061", [{"id": "quant-ph/9903061:gen:0"}])
    assert isolated_store.card_paper_ids() == ["quant-ph/9903061"]
    assert isolated_store.load_cards("quant-ph/9903061")[0]["id"] == "quant-ph/9903061:gen:0"


# ---------------------------------------------------------------------------
# remove_paper (the "+ Add" undo)
# ---------------------------------------------------------------------------

@pytest.fixture
def populated(isolated_store, papers, search_a):
    s = isolated_store
    s._collection["papers"] = {pid: p.model_dump() for pid, p in papers.items()}
    s._collection["extractions"] = {"2005.11401": {"tldr": "RAG."}}
    s._collection["paper_search"] = {"2005.11401": "LLM agents"}
    s._collection["read"] = ["2005.11401", "1706.03762"]
    s._collection["map"] = {
        "clusters": [
            {"name": "Retrieval", "paper_ids": ["2005.11401"]},
            {"name": "Attention", "paper_ids": ["1706.03762", "2006.11239"]},
        ],
        "bridge_edges": [
            {"source": "2005.11401", "target": "1706.03762", "kind": "builds_on"},
            {"source": "1706.03762", "target": "2006.11239", "kind": "extends"},
        ],
    }
    s._collection["searches"] = [{"id": search_a["id"], "paper_count": 2}]
    s.save_search(search_a)
    for directory in ("deep", "index", "s2", "matrix", "cards"):
        (s.DATA_DIR / directory).mkdir(parents=True, exist_ok=True)
        (s.DATA_DIR / directory / "2005.11401.json").write_text("{}", encoding="utf-8")
    return s


def test_remove_paper_reports_what_it_touched(populated, search_a):
    result = populated.remove_paper("2005.11401")
    assert result["removed"] is True
    assert result["searches_updated"] == [search_a["id"]]


def test_remove_paper_clears_every_collection_reference(populated):
    populated.remove_paper("2005.11401")
    c = populated._collection
    assert "2005.11401" not in c["papers"]
    assert "2005.11401" not in c["extractions"]
    assert "2005.11401" not in c["paper_search"]
    assert "2005.11401" not in c["read"]
    assert "1706.03762" in c["papers"], "other papers must be untouched"


def test_remove_paper_drops_clusters_left_empty(populated):
    populated.remove_paper("2005.11401")
    clusters = populated._collection["map"]["clusters"]
    assert [c["name"] for c in clusters] == ["Attention"]


def test_remove_paper_drops_only_edges_touching_that_paper(populated):
    populated.remove_paper("2005.11401")
    edges = populated._collection["map"]["bridge_edges"]
    assert len(edges) == 1
    assert edges[0]["source"] == "1706.03762"


def test_remove_paper_rewrites_the_search_file(populated, search_a):
    populated.remove_paper("2005.11401")
    saved = populated.load_search(search_a["id"])
    assert saved["paper_ids"] == ["1706.03762"]
    assert [c["name"] for c in saved["clusters"]] == ["Attention architectures"]
    assert saved["edges"] == []
    assert [s["paper_id"] for s in saved["reading_order"]] == ["1706.03762"]


def test_remove_paper_keeps_the_search_paper_count_honest(populated, search_a):
    populated.remove_paper("2005.11401")
    (meta,) = populated._collection["searches"]
    assert meta["paper_count"] == 1


def test_remove_paper_deletes_the_per_paper_files(populated):
    populated.remove_paper("2005.11401")
    for directory in ("deep", "index", "s2", "matrix", "cards"):
        assert not (populated.DATA_DIR / directory / "2005.11401.json").exists()


def test_removing_an_unknown_paper_is_a_no_op(populated):
    result = populated.remove_paper("9999.99999")
    assert result["removed"] is False
    assert result["searches_updated"] == []
    assert len(populated._collection["papers"]) == 4


def test_remove_paper_persists_to_disk(populated):
    populated.remove_paper("2005.11401")
    on_disk = json.loads(populated.COLLECTION_FILE.read_text(encoding="utf-8"))
    assert "2005.11401" not in on_disk["papers"]


def test_remove_paper_handles_old_style_ids(populated):
    populated.save_deep_dive("quant-ph/9903061", {"deep_summary": "x"})
    assert populated.remove_paper("quant-ph/9903061")["removed"] is True
    assert populated.load_deep_dive("quant-ph/9903061") is None


# ---------------------------------------------------------------------------
# Search files
# ---------------------------------------------------------------------------

def test_search_ids_are_filename_safe(isolated_store):
    generated = isolated_store.make_search_id("Stable Diffusion / latent models!")
    assert "/" not in generated and " " not in generated


def test_load_search_rejects_traversal(isolated_store):
    assert isolated_store.load_search("../collection") is None


def test_load_search_returns_none_when_absent(isolated_store):
    assert isolated_store.load_search("never-saved") is None
