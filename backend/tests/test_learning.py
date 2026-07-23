"""Flashcards, spaced repetition, and Anki export — all LLM-free paths."""

from __future__ import annotations

from datetime import date, timedelta

from learning import is_due, relationship_cards, schedule, to_anki_tsv
from models import Flashcard


def card(**overrides) -> Flashcard:
    base = dict(
        id="2006.11239:gen:0",
        paper_id="2006.11239",
        question="Why does DDPM use a variance schedule?",
        answer="To control the signal-to-noise ratio across timesteps.",
        kind="concept",
    )
    return Flashcard(**{**base, **overrides})


# ---------------------------------------------------------------------------
# Relationship cards
# ---------------------------------------------------------------------------

def test_card_id_starts_with_the_paper_id(search_a, papers):
    """Regression: /api/cards/grade recovers the paper from the card id by
    splitting on the first colon (main.py). Relationship ids originally began
    with "rel:", so grading every one of them 404'd as "Card not found"."""
    cards = relationship_cards(search_a, papers)
    assert cards, "fixture should produce at least one relationship card"
    for c in cards:
        assert c.id.split(":")[0] == c.paper_id


def test_card_id_survives_a_pre_2007_arxiv_id(papers):
    """Old-style ids carry a slash but no colon, so the split still works."""
    search = {
        "id": "quantum-xyz",
        "edges": [
            {
                "source": "quant-ph/9903061",
                "target": "1706.03762",
                "kind": "builds_on",
                "description": "Both frame computation as sequence transformation.",
            }
        ],
    }
    (c,) = relationship_cards(search, papers)
    assert c.id.split(":")[0] == "quant-ph/9903061"
    assert c.paper_id == "quant-ph/9903061"


def test_relationship_card_records_both_ends(search_a, papers):
    (c,) = relationship_cards(search_a, papers)
    assert c.paper_id == "2005.11401"
    assert c.related_paper_id == "1706.03762"
    assert c.kind == "relationship"


def test_question_is_self_contained(search_a, papers):
    """A quiz shows the question alone, so both papers must be named in it."""
    (c,) = relationship_cards(search_a, papers)
    assert "Retrieval-Augmented Generation" in c.question
    assert "Attention Is All You Need" in c.question
    assert c.answer == "RAG uses the transformer as its generator backbone."


def test_edge_verb_reads_naturally(papers):
    search = {
        "id": "s1",
        "edges": [
            {"source": "2006.11239", "target": "1706.03762", "kind": k, "description": "d"}
            for k in ("builds_on", "compares_to", "mystery_kind")
        ],
    }
    questions = [c.question for c in relationship_cards(search, papers)]
    assert "build on" in questions[0]
    assert "compare to" in questions[1]
    assert "relate to" in questions[2]      # unknown kind falls back


def test_unusable_edges_are_skipped(papers):
    search = {
        "id": "s1",
        "edges": [
            {"source": "9999.99999", "target": "1706.03762", "kind": "builds_on", "d": "x"},
            {"source": "2006.11239", "target": "9999.99999", "kind": "builds_on", "d": "x"},
            {"source": "2006.11239", "target": "1706.03762", "kind": "builds_on",
             "description": "   "},
        ],
    }
    assert relationship_cards(search, papers) == []


def test_no_edges_means_no_cards(search_b, papers):
    assert relationship_cards(search_b, papers) == []


# ---------------------------------------------------------------------------
# Spaced repetition (SM-2 lite)
# ---------------------------------------------------------------------------

def test_first_correct_review_schedules_one_day_out():
    updated = schedule(card(), "correct", 90)
    assert updated.reps == 1
    assert updated.interval == 1
    assert updated.due == (date.today() + timedelta(days=1)).isoformat()
    assert updated.last_score == 90


def test_intervals_lengthen_over_consecutive_correct_reviews():
    """1 day, then 3, then interval * ease — ease is raised before it is
    applied, so the third interval is round(3 * 2.8) = 8, not 3 * 2.5."""
    c = card()
    intervals = [schedule(c, "correct", 95).interval for _ in range(4)]
    assert intervals[:3] == [1, 3, 8]
    assert intervals[3] > intervals[2], "interval should keep growing"


def test_an_incorrect_answer_resets_the_interval_and_counts_a_lapse():
    c = card(interval=30, reps=5, ease=2.5)
    updated = schedule(c, "incorrect", 10)
    assert updated.interval == 1
    assert updated.lapses == 1
    assert updated.ease == 2.3


def test_ease_never_falls_below_the_floor():
    c = card(ease=1.3)
    for _ in range(5):
        schedule(c, "incorrect", 0)
    assert c.ease == 1.3


def test_ease_is_capped_at_three():
    c = card(ease=3.0)
    for _ in range(5):
        schedule(c, "correct", 100)
    assert c.ease == 3.0


def test_a_never_reviewed_card_is_due():
    assert is_due(card()) is True


def test_due_dates_are_compared_against_today():
    today = date.today()
    assert is_due(card(due=(today - timedelta(days=1)).isoformat()), today) is True
    assert is_due(card(due=today.isoformat()), today) is True
    assert is_due(card(due=(today + timedelta(days=3)).isoformat()), today) is False


def test_an_unparseable_due_date_surfaces_the_card_rather_than_hiding_it():
    assert is_due(card(due="not-a-date")) is True


# ---------------------------------------------------------------------------
# Anki export
# ---------------------------------------------------------------------------

def test_anki_rows_have_exactly_three_tab_separated_fields(papers):
    cards = [card(question="Q\twith\ttabs", answer="A\nwith\nnewlines")]
    body = [
        line for line in to_anki_tsv(cards, papers).splitlines()
        if line and not line.startswith("#")
    ]
    assert len(body) == 1
    assert body[0].count("\t") == 2, "stray tabs would shift fields into the wrong column"


def test_anki_answer_carries_the_paper_title(papers):
    row = to_anki_tsv([card()], papers).splitlines()[-1]
    assert "Denoising Diffusion Probabilistic Models" in row
    assert "arxiv-2006-11239" in row
