"""Quiz-aware reading recommendations: cross-referencing flashcard scores
with the reading order's own dependency edges, no LLM call."""

from __future__ import annotations

import pytest

from learning import WEAK_SCORE_THRESHOLD, reading_nudges
from models import Flashcard
from tests.conftest import make_paper


def card(paper_id, score, kind="concept", reps=1, related=None):
    return Flashcard(
        id=f"{paper_id}:gen:0", paper_id=paper_id, question="q", answer="a",
        kind=kind, reps=reps, last_score=score, related_paper_id=related,
    )


@pytest.fixture
def papers():
    return {
        p.id: p for p in [
            make_paper("foundation.1", "The Foundation Paper"),
            make_paper("core.1", "The Core Paper"),
            make_paper("frontier.1", "The Frontier Paper"),
        ]
    }


@pytest.fixture
def search():
    return {
        "id": "s1",
        "reading_order": [
            {"paper_id": "foundation.1", "stage": "foundation"},
            {"paper_id": "core.1", "stage": "core"},
            {"paper_id": "frontier.1", "stage": "frontier"},
        ],
        "edges": [
            {"source": "core.1", "target": "foundation.1", "kind": "builds_on", "description": "d"},
            {"source": "frontier.1", "target": "core.1", "kind": "extends", "description": "d"},
        ],
    }


def test_a_weak_paper_with_a_dependent_produces_a_nudge(search, papers):
    cards = {"foundation.1": [card("foundation.1", 40)], "core.1": [], "frontier.1": []}
    (nudge,) = reading_nudges(search, papers, cards)
    assert nudge.weak_paper_id == "foundation.1"
    assert nudge.weak_paper_title == "The Foundation Paper"
    assert nudge.avg_score == 40.0
    assert nudge.blocks == ["core.1"]
    assert nudge.blocks_titles == ["The Core Paper"]


def test_a_strong_score_produces_no_nudge(search, papers):
    cards = {"foundation.1": [card("foundation.1", 95)], "core.1": [], "frontier.1": []}
    assert reading_nudges(search, papers, cards) == []


def test_a_weak_score_right_at_the_threshold_does_not_nudge(search, papers):
    """< threshold, not <=  — a borderline score shouldn't nag."""
    cards = {"foundation.1": [card("foundation.1", WEAK_SCORE_THRESHOLD)], "core.1": [], "frontier.1": []}
    assert reading_nudges(search, papers, cards) == []


def test_a_weak_paper_with_no_dependents_is_not_actionable(search, papers):
    """Weak on the frontier paper — nothing in this search builds on it, so
    there's nothing to reread first. The Study Deck already shows the score."""
    cards = {"foundation.1": [], "core.1": [], "frontier.1": [card("frontier.1", 20)]}
    assert reading_nudges(search, papers, cards) == []


def test_multiple_weak_papers_are_sorted_worst_first(search, papers):
    cards = {
        "foundation.1": [card("foundation.1", 55)],
        "core.1": [card("core.1", 30)],
        "frontier.1": [],
    }
    nudges = reading_nudges(search, papers, cards)
    assert [n.weak_paper_id for n in nudges] == ["core.1", "foundation.1"]


def test_average_is_computed_across_multiple_reviewed_cards(search, papers):
    cards = {
        "foundation.1": [card("foundation.1", 40), card("foundation.1", 60)],
        "core.1": [], "frontier.1": [],
    }
    (nudge,) = reading_nudges(search, papers, cards)
    assert nudge.avg_score == 50.0
    assert nudge.reviewed_count == 2


def test_unreviewed_cards_do_not_count_as_a_score(search, papers):
    """reps=0 / last_score=None means never graded — must not read as 0."""
    never_reviewed = Flashcard(
        id="foundation.1:gen:0", paper_id="foundation.1", question="q", answer="a",
        kind="concept", reps=0, last_score=None,
    )
    cards = {"foundation.1": [never_reviewed], "core.1": [], "frontier.1": []}
    assert reading_nudges(search, papers, cards) == []


def test_relationship_cards_are_excluded_from_the_average(search, papers):
    """A relationship card's score reflects understanding of a connection
    between two papers, not mastery of either paper alone."""
    cards = {
        "foundation.1": [
            card("foundation.1", 90, kind="relationship", related="core.1"),
            card("foundation.1", 30),
        ],
        "core.1": [], "frontier.1": [],
    }
    (nudge,) = reading_nudges(search, papers, cards)
    assert nudge.avg_score == 30.0
    assert nudge.reviewed_count == 1


def test_a_paper_outside_the_reading_order_is_ignored(search, papers):
    """cards_by_paper can contain library-wide data; only this search's own
    reading order should be scored."""
    cards = {
        "foundation.1": [], "core.1": [], "frontier.1": [],
        "outsider.1": [card("outsider.1", 10)],
    }
    assert reading_nudges(search, papers, cards) == []


def test_only_builds_on_and_extends_edges_create_a_dependency(search, papers):
    """A 'compares_to' or 'evaluates' edge is not a prerequisite relationship
    — being weak on a paper another merely compares against isn't blocking."""
    search = {**search, "edges": [
        {"source": "core.1", "target": "foundation.1", "kind": "compares_to", "description": "d"},
    ]}
    cards = {"foundation.1": [card("foundation.1", 20)], "core.1": [], "frontier.1": []}
    assert reading_nudges(search, papers, cards) == []


def test_no_weak_papers_returns_empty_without_walking_edges(search, papers):
    assert reading_nudges(search, papers, {}) == []


def test_a_removed_dependent_paper_is_not_listed_as_a_blocker(search, papers):
    """An edge can reference a paper no longer in this search's reading
    order (e.g. after remove_paper) — it must not appear as a blocker."""
    search = {**search, "reading_order": [
        {"paper_id": "foundation.1", "stage": "foundation"},
    ], "edges": [
        {"source": "core.1", "target": "foundation.1", "kind": "builds_on", "description": "d"},
    ]}
    cards = {"foundation.1": [card("foundation.1", 20)]}
    assert reading_nudges(search, papers, cards) == []
