"""Which followed searches are due for an automatic digest refresh.

Pure and time-injectable so it's testable without waiting real days; the
actual asyncio loop that calls this on a timer lives in main.py alongside
the rest of the process/I/O orchestration (matching where _run_deep_dive
lives, not here).

This can only run while the backend process is alive — there is no external
cron. "Weekly" means "next time the check interval fires, a week has passed,
and the process happens to be up," not a guaranteed wall-clock trigger. Be
honest about that in anything user-facing.
"""

from __future__ import annotations

from datetime import datetime, timedelta

DIGEST_INTERVAL_DAYS = 7


def is_digest_due(search: dict, latest_digest: dict | None, now: datetime | None = None) -> bool:
    """True if a followed search has no digest yet, or its most recent one
    is at least DIGEST_INTERVAL_DAYS old. False for an unfollowed search
    regardless of age — following is the reader's explicit opt-in."""
    if not search.get("followed"):
        return False
    if latest_digest is None:
        return True
    try:
        created = datetime.fromisoformat(latest_digest["created_at"])
    except (KeyError, TypeError, ValueError):
        # Malformed timestamp shouldn't wedge a search into never refreshing.
        return True
    return (now or datetime.now()) - created >= timedelta(days=DIGEST_INTERVAL_DAYS)


def due_searches(
    searches: list[dict],
    latest_digest_by_id: dict[str, dict | None],
    now: datetime | None = None,
) -> list[dict]:
    """Filter a list of search metas down to the ones due for a refresh."""
    return [
        search
        for search in searches
        if is_digest_due(search, latest_digest_by_id.get(search["id"]), now)
    ]
