"""Which papers get warmed ahead of the reader. Pure policy — the asyncio
worker that acts on it lives in main.py and is not exercised here."""

from __future__ import annotations

import prefetch


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------

ORDER = ["a.1", "b.2", "c.3", "d.4", "e.5"]


def test_nothing_open_yet_warms_the_first_paper():
    """Results have just landed; the top of the reading order is the one the
    reader is most likely to click."""
    assert prefetch.plan(ORDER, None) == ["a.1"]


def test_opening_a_paper_warms_the_ones_after_it():
    assert prefetch.plan(ORDER, "b.2", look_ahead=2) == ["c.3", "d.4"]


def test_the_look_ahead_is_bounded():
    """Warming a whole search would spend most of a day's cap on papers that
    never get opened."""
    assert len(prefetch.plan(ORDER, "a.1", look_ahead=2)) == 2


def test_the_last_paper_warms_nothing():
    assert prefetch.plan(ORDER, "e.5") == []


def test_a_paper_outside_the_order_warms_nothing():
    """Opened from the library rather than this search — guessing a position
    would warm arbitrary papers."""
    assert prefetch.plan(ORDER, "zz.9") == []


def test_an_empty_order_warms_nothing():
    assert prefetch.plan([], None) == []
    assert prefetch.plan([], "a.1") == []


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------

def test_enqueue_appends_in_order():
    queue = prefetch.enqueue([], ["a.1", "b.2"], deep_read=set(), failed=set())
    assert queue == ["a.1", "b.2"]


def test_enqueue_does_not_duplicate_a_queued_paper():
    queue = prefetch.enqueue(["a.1"], ["a.1", "b.2"], deep_read=set(), failed=set())
    assert queue == ["a.1", "b.2"]


def test_enqueue_skips_papers_already_read():
    queue = prefetch.enqueue([], ["a.1", "b.2"], deep_read={"a.1"}, failed=set())
    assert queue == ["b.2"]


def test_enqueue_skips_papers_that_failed():
    queue = prefetch.enqueue([], ["a.1", "b.2"], deep_read=set(), failed={"b.2"})
    assert queue == ["a.1"]


def test_enqueue_does_not_mutate_the_queue_it_is_given():
    original = ["a.1"]
    prefetch.enqueue(original, ["b.2"], deep_read=set(), failed=set())
    assert original == ["a.1"]


# ---------------------------------------------------------------------------
# next_to_warm
# ---------------------------------------------------------------------------

def test_next_to_warm_takes_the_front_of_the_queue():
    assert prefetch.next_to_warm(
        ["a.1", "b.2"], deep_read=set(), failed=set()
    ) == "a.1"


def test_next_to_warm_skips_a_paper_read_since_it_was_queued():
    """A paper can be queued and then read by hand before its turn comes."""
    assert prefetch.next_to_warm(
        ["a.1", "b.2"], deep_read={"a.1"}, failed=set()
    ) == "b.2"


def test_next_to_warm_never_returns_a_failed_paper():
    """arXiv publishes some papers as PDF only; those fail identically every
    time, and a queue that keeps handing one back never drains."""
    assert prefetch.next_to_warm(["a.1"], deep_read=set(), failed={"a.1"}) is None


def test_next_to_warm_is_none_for_an_empty_queue():
    assert prefetch.next_to_warm([], deep_read=set(), failed=set()) is None


# ---------------------------------------------------------------------------
# should_hold
# ---------------------------------------------------------------------------

READY = {"ready": True, "detail": None}


def test_a_ready_engine_under_the_cap_goes_ahead():
    assert prefetch.should_hold(READY, {"near_cap": False}) is None


def test_warming_holds_off_when_the_engine_is_not_ready():
    reason = prefetch.should_hold({"ready": False, "detail": "Ollama is not running."}, None)
    assert reason == "Ollama is not running."


def test_warming_holds_off_near_the_daily_cap():
    """A speculative read must never be the call that spends the reader's last
    budget — their own explicit reads have a claim on it that a guess doesn't."""
    assert prefetch.should_hold(READY, {"near_cap": True}) is not None


def test_a_local_engine_has_no_cap_to_check():
    assert prefetch.should_hold(READY, None) is None
