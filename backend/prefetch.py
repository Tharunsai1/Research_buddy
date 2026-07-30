"""Which papers to warm up ahead of the reader, and when to hold off.

Reading a paper in depth is the slow, expensive step — a couple of minutes and
a double-digit number of model calls. Warming the next paper in the reading
order while the reader is still on the current one hides that latency, but
only under two constraints:

* it must never compete with the read the reader is actually watching, and
* the look-ahead must be bounded. A 30-paper search warmed end to end would
  spend most of a day's cap on papers that never get opened.

Pure and injectable so the policy is testable without running a real deep
dive; the asyncio worker that acts on it lives in main.py alongside
_run_deep_dive (matching where scheduler.py's loop lives, not here).
"""

from __future__ import annotations

from typing import Any, Iterable

# How many papers past the one being read to keep warm. Two covers the reader
# who moves straight down the list without betting a day's cap on the guess.
LOOK_AHEAD = 2


def plan(
    reading_order: list[str],
    after_paper_id: str | None = None,
    look_ahead: int = LOOK_AHEAD,
) -> list[str]:
    """The papers worth warming given where the reader is.

    `after_paper_id` None means nothing has been opened yet — results have
    just landed — so the first paper in the order is the one most likely to be
    clicked. Otherwise warm the papers that follow the one being read. A paper
    that isn't in the order (removed, or belonging to another search) warms
    nothing rather than guessing at a position.
    """
    if not reading_order:
        return []
    if after_paper_id is None:
        return reading_order[:1]
    try:
        index = reading_order.index(after_paper_id)
    except ValueError:
        return []
    return reading_order[index + 1 : index + 1 + look_ahead]


def enqueue(
    queue: list[str],
    paper_ids: Iterable[str],
    *,
    deep_read: set[str],
    failed: set[str],
) -> list[str]:
    """`queue` with `paper_ids` appended, skipping duplicates and anything not
    worth warming. Returns a new list rather than mutating, and preserves
    order so the paper the reader is closest to stays at the front.
    """
    out = list(queue)
    for paper_id in paper_ids:
        if paper_id in out or paper_id in deep_read or paper_id in failed:
            continue
        out.append(paper_id)
    return out


def next_to_warm(
    queue: list[str], *, deep_read: set[str], failed: set[str]
) -> str | None:
    """The first queued paper still worth reading, or None if none is.

    Already-read papers drop out because the work is done. Failed ones drop
    out permanently: the usual cause is a paper with no HTML full text on
    arXiv, which no amount of retrying will produce, and a queue that keeps
    handing back the same unreadable paper never drains.
    """
    for paper_id in queue:
        if paper_id not in deep_read and paper_id not in failed:
            return paper_id
    return None


def should_hold(status: dict[str, Any], usage: dict[str, Any] | None) -> str | None:
    """Why warming should not start right now, or None to go ahead.

    A speculative read must never be the call that pushes the reader over the
    daily cap — their own explicit reads have a claim on the remaining budget
    that a guess does not.
    """
    if not status.get("ready"):
        return status.get("detail") or "the engine is not ready"
    if usage is not None and usage.get("near_cap"):
        return "the daily cap is nearly reached"
    return None
