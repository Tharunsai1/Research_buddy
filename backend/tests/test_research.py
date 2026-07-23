"""Search diffing and the field report — both pure, both LLM-free."""

from __future__ import annotations

from research import build_field_report, diff_searches

CARD_STATS = {
    "total": 12,
    "relationship": 9,
    "per_paper": 3,
    "reviewed": 4,
    "due": 2,
    "avg_score": 87.5,
}


# ---------------------------------------------------------------------------
# diff_searches
# ---------------------------------------------------------------------------

def test_diff_reports_papers_gained_and_lost(search_a, search_b, papers):
    diff = diff_searches(search_a, search_b, papers)
    assert [p["id"] for p in diff["new_papers"]] == ["2006.11239"]
    assert [p["id"] for p in diff["dropped_papers"]] == ["1706.03762"]
    assert diff["shared_paper_count"] == 1


def test_diff_carries_enough_to_render_a_paper_chip(search_a, search_b, papers):
    (brief,) = diff_searches(search_a, search_b, papers)["new_papers"]
    assert brief["title"] == "Denoising Diffusion Probabilistic Models"


def test_diff_tracks_theme_churn(search_a, search_b, papers):
    diff = diff_searches(search_a, search_b, papers)
    assert diff["clusters_added"] == ["Generative models"]
    assert diff["clusters_removed"] == ["Attention architectures"]


def test_diff_tracks_consensus_tensions_and_open_problems(search_a, search_b, papers):
    diff = diff_searches(search_a, search_b, papers)
    assert diff["consensus_added"] == ["Tool use is essential."]
    assert diff["consensus_removed"] == ["Scaling helps."]
    assert diff["tensions_added"] == ["Autonomy vs control"]
    assert diff["tensions_removed"] == ["Cost vs quality"]
    assert diff["open_problems_added"] == ["Evaluation"]
    assert diff["open_problems_removed"] == ["Long-horizon planning"]


def test_shared_items_appear_in_neither_column(search_a, search_b, papers):
    diff = diff_searches(search_a, search_b, papers)
    shared = "Retrieval reduces hallucination."
    assert shared not in diff["consensus_added"]
    assert shared not in diff["consensus_removed"]
    assert "Retrieval" not in diff["clusters_added"] + diff["clusters_removed"]


def test_a_search_against_itself_shows_no_change(search_a, papers):
    diff = diff_searches(search_a, search_a, papers)
    assert diff["new_papers"] == []
    assert diff["dropped_papers"] == []
    assert diff["shared_paper_count"] == 2
    for key in (
        "clusters_added", "clusters_removed",
        "consensus_added", "consensus_removed",
        "tensions_added", "tensions_removed",
        "open_problems_added", "open_problems_removed",
    ):
        assert diff[key] == [], key


def test_diff_is_directional(search_a, search_b, papers):
    """Swapping the operands swaps the columns — the UI labels one side
    'then' and the other 'now', so this must not be symmetric."""
    forward = diff_searches(search_a, search_b, papers)
    backward = diff_searches(search_b, search_a, papers)
    assert forward["new_papers"] == backward["dropped_papers"]
    assert forward["clusters_added"] == backward["clusters_removed"]


def test_diff_meta_labels_both_sides(search_a, search_b, papers):
    diff = diff_searches(search_a, search_b, papers)
    assert diff["a"]["id"] == search_a["id"]
    assert diff["a"]["paper_count"] == 2
    assert diff["b"]["created_at"] == "2026-07-23T10:00:00"


def test_diff_tolerates_a_paper_missing_from_the_library(search_a, search_b, papers):
    """A search can outlive a removed paper; the diff must not crash on it."""
    diff = diff_searches(search_a, search_b, {})
    assert diff["new_papers"] == []
    assert diff["shared_paper_count"] == 1


# ---------------------------------------------------------------------------
# build_field_report
# ---------------------------------------------------------------------------

def test_report_opens_with_the_search_title(search_a, papers):
    report = build_field_report(search_a, papers, CARD_STATS)
    assert report.startswith("# LLM Agents")


def test_report_includes_every_section_that_has_content(search_a, papers):
    report = build_field_report(search_a, papers, CARD_STATS)
    for heading in (
        "## Overview",
        "## Method clusters",
        "## Tensions",
        "## Consensus",
        "## Open problems",
        "## Suggested reading order",
        "## Study progress",
    ):
        assert heading in report, heading


def test_report_links_papers_to_arxiv(search_a, papers):
    report = build_field_report(search_a, papers, CARD_STATS)
    assert "[Attention Is All You Need](https://arxiv.org/abs/1706.03762)" in report


def test_report_groups_reading_order_by_stage(search_a, papers):
    report = build_field_report(search_a, papers, CARD_STATS)
    assert "### Foundations" in report
    assert "### Core methods" in report
    assert "### Frontier" not in report, "empty stages should be omitted"


def test_report_states_study_progress(search_a, papers):
    report = build_field_report(search_a, papers, CARD_STATS)
    assert "12 flashcards (9 relationship, 3 per-paper)" in report
    assert "4 reviewed at least once · 2 due now" in report
    assert "Average score so far: 88/100" in report


def test_report_omits_the_average_before_anything_is_graded(search_a, papers):
    stats = {**CARD_STATS, "avg_score": None}
    assert "Average score" not in build_field_report(search_a, papers, stats)


def test_report_skips_papers_that_are_no_longer_in_the_library(search_a):
    report = build_field_report(search_a, {}, CARD_STATS)
    assert "## Method clusters" in report
    assert "arxiv.org/abs" not in report


def test_report_omits_sections_a_sparse_search_never_produced(papers):
    bare = {
        "id": "bare-1", "query": "q", "title": "Bare", "created_at": "2026-07-23T00:00:00",
        "paper_ids": ["1706.03762"],
    }
    report = build_field_report(bare, papers, CARD_STATS)
    assert "## Overview" not in report
    assert "## Tensions" not in report
    assert "## Study progress" in report, "progress is always reported"
