"""Which followed searches are due for an automatic digest — pure, time-
injectable, no waiting real days and no network."""

from __future__ import annotations

from datetime import datetime, timedelta

from scheduler import DIGEST_INTERVAL_DAYS, due_searches, is_digest_due

NOW = datetime(2026, 7, 23, 12, 0, 0)


def search(followed: bool = True) -> dict:
    return {"id": "s1", "query": "q", "followed": followed}


def digest(days_ago: float) -> dict:
    return {"created_at": (NOW - timedelta(days=days_ago)).isoformat()}


# ---------------------------------------------------------------------------
# is_digest_due
# ---------------------------------------------------------------------------

def test_an_unfollowed_search_is_never_due():
    """Following is the reader's explicit opt-in — age alone never triggers
    a run for a search nobody asked to keep current."""
    assert is_digest_due(search(followed=False), None, NOW) is False
    assert is_digest_due(search(followed=False), digest(30), NOW) is False


def test_a_followed_search_with_no_digest_yet_is_due():
    assert is_digest_due(search(), None, NOW) is True


def test_a_followed_search_with_a_recent_digest_is_not_due():
    assert is_digest_due(search(), digest(1), NOW) is False


def test_a_followed_search_past_the_interval_is_due():
    assert is_digest_due(search(), digest(DIGEST_INTERVAL_DAYS + 1), NOW) is True


def test_exactly_at_the_interval_boundary_is_due():
    """>=, not >  — a search shouldn't sit one tick past due forever."""
    assert is_digest_due(search(), digest(DIGEST_INTERVAL_DAYS), NOW) is True


def test_just_under_the_interval_is_not_due():
    assert is_digest_due(search(), digest(DIGEST_INTERVAL_DAYS - 0.01), NOW) is False


def test_a_malformed_timestamp_is_treated_as_due_rather_than_crashing():
    """A search shouldn't get permanently stuck un-refreshable because one
    stored digest has a bad or missing created_at."""
    assert is_digest_due(search(), {"created_at": "not-a-date"}, NOW) is True
    assert is_digest_due(search(), {}, NOW) is True


# ---------------------------------------------------------------------------
# due_searches
# ---------------------------------------------------------------------------

def test_due_searches_filters_a_mixed_list():
    searches = [
        {"id": "a", "followed": True},
        {"id": "b", "followed": True},
        {"id": "c", "followed": False},
    ]
    latest = {"a": digest(30), "b": digest(1), "c": digest(30)}
    result = due_searches(searches, latest, NOW)
    assert [s["id"] for s in result] == ["a"]


def test_due_searches_treats_a_missing_digest_entry_as_never_run():
    searches = [{"id": "a", "followed": True}]
    assert due_searches(searches, {}, NOW) == searches


def test_due_searches_returns_nothing_for_an_empty_list():
    assert due_searches([], {}, NOW) == []
