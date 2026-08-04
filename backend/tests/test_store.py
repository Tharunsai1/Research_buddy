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
    Rejecting them silently dropped every deep dive, appraisal and citation record
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
    record, so they must not be served â€” reopening offers a fresh read, which
    now refuses with an explanation."""
    isolated_store.save_deep_dive(
        "quant-ph/9903061",
        {"source_url": "https://arxiv.org/abs/quant-ph/9903061", "total_words": 509},
    )
    assert isolated_store.load_deep_dive("quant-ph/9903061") is None


def test_a_withheld_record_is_not_deleted(isolated_store):
    """Withholding is not destruction â€” the file stays for inspection."""
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


def test_appraisals_roundtrip_for_old_style_ids(isolated_store):
    isolated_store.save_appraisal("quant-ph/9903061", {"paper_id": "quant-ph/9903061"})
    assert isolated_store.appraised_paper_ids() == ["quant-ph/9903061"]
    saved = isolated_store.load_appraisal("quant-ph/9903061")
    assert saved["paper_id"] == "quant-ph/9903061"


def test_deleting_an_appraisal_removes_it_from_the_queue(isolated_store):
    """Re-running an appraisal has to be possible: the queue is driven by which
    files exist, so a stale one would keep the paper marked done forever."""
    isolated_store.save_appraisal("2605.04956", {"paper_id": "2605.04956"})
    isolated_store.delete_appraisal("2605.04956")
    assert isolated_store.appraised_paper_ids() == []
    assert isolated_store.load_appraisal("2605.04956") is None


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
    for directory in ("deep", "index", "s2", "matrix", "appraisals"):
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
    for directory in ("deep", "index", "s2", "matrix", "appraisals"):
        assert not (populated.DATA_DIR / directory / "2005.11401.json").exists()


def test_remove_paper_deletes_its_uploaded_pdf(populated):
    """Removing an uploaded paper is the undo for a mistaken upload â€” the
    stored PDF must go with it, not linger as an orphaned file forever."""
    populated.save_upload("local-x-abc123", b"%PDF-1.4\nfake but real bytes")
    populated._collection["papers"]["local-x-abc123"] = populated._collection["papers"][
        "2005.11401"
    ]
    result = populated.remove_paper("local-x-abc123")
    assert result["removed"] is True
    assert populated.load_upload("local-x-abc123") is None


def test_removing_an_unknown_paper_is_a_no_op(populated):
    result = populated.remove_paper("9999.99999")
    assert result["removed"] is False
    assert result["searches_updated"] == []
    assert len(populated._collection["papers"]) == 4


def test_remove_paper_persists_to_disk(populated):
    populated.remove_paper("2005.11401")
    on_disk = json.loads(populated.COLLECTION_FILE.read_text(encoding="utf-8"))
    assert "2005.11401" not in on_disk["papers"]


def test_remove_paper_drops_the_stale_library_embedding(populated):
    populated.save_library_index({"2005.11401": [0.1] * 8, "1706.03762": [0.2] * 8})
    populated.remove_paper("2005.11401")
    index = populated.load_library_index()
    assert "2005.11401" not in index
    assert "1706.03762" in index


def test_remove_paper_handles_old_style_ids(populated):
    populated.save_deep_dive("quant-ph/9903061", {"deep_summary": "x"})
    assert populated.remove_paper("quant-ph/9903061")["removed"] is True
    assert populated.load_deep_dive("quant-ph/9903061") is None


# ---------------------------------------------------------------------------
# Search files
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Uploaded PDFs
# ---------------------------------------------------------------------------

def test_an_uploaded_pdf_round_trips_byte_for_byte(isolated_store):
    data = b"%PDF-1.4\nnot a real pdf but real bytes\n%%EOF"
    isolated_store.save_upload("local-x-abc123", data)
    assert isolated_store.load_upload("local-x-abc123") == data


def test_a_paper_with_no_upload_returns_none(isolated_store):
    assert isolated_store.load_upload("local-never-uploaded-000000") is None


def test_upload_ids_survive_the_same_slash_folding_as_arxiv_ids(isolated_store):
    """Not expected in practice for local- ids, but the storage layer applies
    the same _safe() convention uniformly regardless of id shape."""
    isolated_store.save_upload("weird/id-with-slash", b"data")
    assert isolated_store.load_upload("weird/id-with-slash") == b"data"


def test_an_unsafe_upload_id_writes_nothing(isolated_store, tmp_path):
    isolated_store.save_upload("../escape", b"data")
    assert isolated_store.load_upload("../escape") is None
    assert not list(tmp_path.rglob("*escape*"))


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

def test_a_paper_with_no_note_returns_empty_string(isolated_store):
    assert isolated_store.get_note("2006.11239") == ""


def test_a_saved_note_round_trips(isolated_store):
    saved = isolated_store.set_note("2006.11239", "  Contradicts the RAG paper's claim.  ")
    assert saved == "Contradicts the RAG paper's claim."
    assert isolated_store.get_note("2006.11239") == "Contradicts the RAG paper's claim."


def test_saving_whitespace_clears_the_note_rather_than_storing_blanks(isolated_store):
    isolated_store.set_note("2006.11239", "a real note")
    isolated_store.set_note("2006.11239", "   ")
    assert isolated_store.get_note("2006.11239") == ""
    assert "2006.11239" not in isolated_store.all_notes()


def test_notes_persist_to_disk(isolated_store):
    isolated_store.set_note("2006.11239", "note text")
    on_disk = json.loads(isolated_store.COLLECTION_FILE.read_text(encoding="utf-8"))
    assert on_disk["notes"]["2006.11239"] == "note text"


def test_all_notes_only_returns_papers_with_a_note(isolated_store):
    isolated_store.set_note("a.1", "first")
    isolated_store.set_note("b.1", "second")
    assert isolated_store.all_notes() == {"a.1": "first", "b.1": "second"}


def test_remove_paper_drops_its_note(populated):
    populated.set_note("2005.11401", "a thought about RAG")
    populated.remove_paper("2005.11401")
    assert populated.get_note("2005.11401") == ""
    assert "2005.11401" not in populated.all_notes()


def test_search_ids_are_filename_safe(isolated_store):
    generated = isolated_store.make_search_id("Stable Diffusion / latent models!")
    assert "/" not in generated and " " not in generated


def test_load_search_rejects_traversal(isolated_store):
    assert isolated_store.load_search("../collection") is None


def test_load_search_returns_none_when_absent(isolated_store):
    assert isolated_store.load_search("never-saved") is None


# ---------------------------------------------------------------------------
# followed_searches â€” the digest scheduler's input
# ---------------------------------------------------------------------------

def test_followed_searches_sees_a_search_the_follow_endpoint_marked(
    isolated_store, search_a
):
    """The regression that made scheduled digests dead on arrival.

    /follow writes `followed` onto the *search file* (via save_search), but the
    scheduler used to filter collection.json's search metas â€” which are built
    once at search-creation time and never carry `followed`. The filter matched
    nothing on every tick, so no automatic digest could ever run while the
    feature looked correct in the UI (which reads the search file).
    """
    isolated_store._collection["searches"] = [{"id": search_a["id"], "paper_count": 2}]
    isolated_store.save_search({**search_a, "followed": True})

    followed = isolated_store.followed_searches()

    assert [s["id"] for s in followed] == [search_a["id"]]
    # The meta deliberately has no `followed` key â€” proving the lookup reads
    # the search file and does not regress to trusting the meta.
    assert "followed" not in isolated_store._collection["searches"][0]


def test_followed_searches_skips_unfollowed_and_missing(isolated_store, search_a, search_b):
    isolated_store._collection["searches"] = [
        {"id": search_a["id"]},
        {"id": search_b["id"]},
        {"id": "deleted-from-disk"},
    ]
    isolated_store.save_search({**search_a, "followed": False})
    isolated_store.save_search({**search_b, "followed": True})

    assert [s["id"] for s in isolated_store.followed_searches()] == [search_b["id"]]


def test_following_survives_a_reload_of_the_search(isolated_store, search_a):
    isolated_store._collection["searches"] = [{"id": search_a["id"]}]
    isolated_store.save_search({**search_a, "followed": True})

    reloaded = isolated_store.load_search(search_a["id"])
    assert reloaded is not None and reloaded["followed"] is True


# ---------------------------------------------------------------------------
# _write_atomic â€” concurrent writers
# ---------------------------------------------------------------------------

def test_concurrent_writers_to_one_file_do_not_crash(isolated_store):
    """Background warm-up reads and scheduled digests run alongside whatever
    the reader is doing, so two writers can land on the same paper. On Windows
    that used to raise PermissionError from os.replace and abort the save,
    leaving the real file stale."""
    import threading

    errors: list[Exception] = []

    def writer(n: int) -> None:
        try:
            for _ in range(40):
                isolated_store.save_appraisal("2605.04956", {"writer": n})
        except Exception as exc:  # noqa: BLE001 - the point is to catch any
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    saved = isolated_store.load_appraisal("2605.04956")
    assert saved is not None, "a torn write would leave truncated or invalid JSON"


def test_a_failed_write_leaves_no_temp_file_behind(isolated_store):
    """Temp files are skipped by every glob in the module, but they should not
    accumulate either."""
    isolated_store.save_appraisal("2605.04956", {"q": "a"})
    strays = list(isolated_store.APPRAISALS_DIR.glob("*.tmp"))
    assert strays == []


# ---------------------------------------------------------------------------
# Highlights
# ---------------------------------------------------------------------------

def _mark(paper_id="2106.06097", quote="attention is all you need",
          created_at="2026-07-27T10:00:00", hid="h_1"):
    return {"id": hid, "paper_id": paper_id, "tab": "summary",
            "quote": quote, "prefix": "", "suffix": "", "note": "",
            "created_at": created_at}


def test_highlights_round_trip(isolated_store):
    isolated_store.save_highlights("2106.06097", [_mark()])
    assert isolated_store.load_highlights("2106.06097")[0]["quote"] == "attention is all you need"


def test_a_paper_with_no_highlights_reads_as_empty(isolated_store):
    assert isolated_store.load_highlights("2106.06097") == []


def test_all_highlights_spans_papers_newest_first(isolated_store):
    isolated_store.save_highlights("a.1", [_mark("a.1", "older", created_at="2026-07-01T00:00:00", hid="h_a")])
    isolated_store.save_highlights("b.2", [_mark("b.2", "newer", created_at="2026-07-20T00:00:00", hid="h_b")])
    assert [h["quote"] for h in isolated_store.all_highlights()] == ["newer", "older"]


def test_one_unreadable_file_does_not_empty_the_library_view(isolated_store):
    """A corrupt file should cost its own highlights, not everyone else's."""
    isolated_store.save_highlights("a.1", [_mark("a.1", "kept")])
    isolated_store.HIGHLIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    (isolated_store.HIGHLIGHTS_DIR / "broken.json").write_text("{not json", encoding="utf-8")
    assert [h["quote"] for h in isolated_store.all_highlights()] == ["kept"]


def test_removing_a_paper_removes_its_highlights(isolated_store):
    """Highlights quote the paper's own text; leaving them behind would strand
    passages pointing at something no longer in the library."""
    from tests.conftest import make_paper

    paper = make_paper("2106.06097", "Neural Optimization Kernel")
    isolated_store.merge_search_results("kernels", [paper], {})
    isolated_store.save_highlights("2106.06097", [_mark()])

    isolated_store.remove_paper("2106.06097")

    assert isolated_store.load_highlights("2106.06097") == []


