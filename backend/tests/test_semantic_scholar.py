"""Semantic Scholar's batch endpoint has two different shapes for "unknown
paper" depending on what shares the batch, and the client must treat them
the same.

Reproduced directly against the real API: a batch of {known, unknown} returns
200 with a per-id `null` for the unknown one; the same unknown id submitted
alone returns 400 {"error":"No valid paper ids given"}. The "Load citation
data" button broke on real data because exactly one paper was pending
(2403.02240, a real arXiv paper S2 simply hasn't indexed) — a batch of one
unknown id hits the 400 path, which the code treated as a hard failure and
raised, killing enrichment over a single unindexed paper.

No network: httpx.AsyncClient is stubbed throughout.
"""

from __future__ import annotations

import pytest

import semantic_scholar as s2
from semantic_scholar import S2Error, fetch_batch


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text else (str(payload) if payload is not None else "")

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for `httpx.AsyncClient(...)` as an async context manager."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[list[str]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, params=None, json=None, headers=None):
        self.calls.append(json["ids"])
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def client(monkeypatch):
    """Queue of responses/exceptions returned in order across calls."""
    holder: dict[str, FakeClient] = {}

    def script(*responses):
        fake = FakeClient(list(responses))
        holder["client"] = fake
        monkeypatch.setattr(s2, "httpx", type("M", (), {
            "AsyncClient": lambda *a, **kw: fake,
            "HTTPError": s2.httpx.HTTPError,
        }))
        return fake

    monkeypatch.setattr(s2, "_last_call", 0.0)
    monkeypatch.setattr(s2, "MIN_INTERVAL", 0.0)
    return script


# ---------------------------------------------------------------------------
# The all-unknown-batch 400
# ---------------------------------------------------------------------------

async def test_a_solo_unknown_id_does_not_raise(client):
    """This is the real failure: one pending paper, S2 doesn't have it."""
    client(FakeResponse(400, text='{"error":"No valid paper ids given"}'))
    result = await fetch_batch(["2403.02240"])
    assert result == {}


async def test_enrichment_of_other_papers_is_unaffected_by_one_unknown_paper(client):
    fake = client(FakeResponse(400, text='{"error":"No valid paper ids given"}'))
    result = await fetch_batch(["2403.02240"])
    assert result == {}
    assert fake.calls == [["ARXIV:2403.02240"]]


async def test_a_mixed_batch_still_uses_the_normal_per_id_null_path(client):
    """The 200 path already worked; this just pins it as a regression guard
    now that a second code path exists for the same underlying fact."""
    client(FakeResponse(200, payload=[{"title": "Attention Is All You Need", "citationCount": 9}, None]))
    result = await fetch_batch(["1706.03762", "2403.02240"])
    assert list(result.keys()) == ["1706.03762"]


async def test_the_400_match_is_specific_to_the_known_error_text(client):
    """A 400 for a different reason (malformed request, bad field list) must
    still surface as a real error rather than being silently swallowed."""
    client(FakeResponse(400, text='{"error":"Unrecognized field: bogus"}'))
    with pytest.raises(S2Error):
        await fetch_batch(["1706.03762"])


async def test_multiple_all_unknown_batches_all_resolve_to_empty(client, monkeypatch):
    """BATCH_SIZE is 16; a library with >16 consecutive unindexed papers must
    not raise partway through."""
    monkeypatch.setattr(s2, "BATCH_SIZE", 2)
    client(
        FakeResponse(400, text='{"error":"No valid paper ids given"}'),
        FakeResponse(400, text='{"error":"No valid paper ids given"}'),
    )
    result = await fetch_batch(["a.1", "a.2", "a.3", "a.4"])
    assert result == {}


# ---------------------------------------------------------------------------
# Existing retry/error behaviour must survive the new branch
# ---------------------------------------------------------------------------

async def test_a_transient_5xx_is_retried_not_raised(client, monkeypatch):
    monkeypatch.setattr(s2, "MAX_RETRIES", 3)
    client(
        FakeResponse(503, text="server error"),
        FakeResponse(200, payload=[{"title": "x", "citationCount": 1}]),
    )
    result = await fetch_batch(["1706.03762"])
    assert "1706.03762" in result


async def test_an_unrelated_client_error_still_raises(client):
    client(FakeResponse(404, text="not found"))
    with pytest.raises(S2Error):
        await fetch_batch(["1706.03762"])
