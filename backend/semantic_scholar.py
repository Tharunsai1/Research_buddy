"""Semantic Scholar — real citation counts and reference lists per arXiv paper.

The public Graph API needs no key but shares a global rate limit, so every
response is cached to disk and requests are serialized behind a minimum
interval with backoff on 429.
"""

from __future__ import annotations

import asyncio
import os
import time

import httpx

from models import S2Paper, S2Reference

API = "https://api.semanticscholar.org/graph/v1/paper/batch"
API_KEY = os.getenv("S2_API_KEY", "").strip()

FIELDS = ",".join(
    [
        "title",
        "year",
        "citationCount",
        "influentialCitationCount",
        "referenceCount",
        "externalIds",
        "references.externalIds",
        "references.title",
        "references.citationCount",
        "references.year",
    ]
)

BATCH_SIZE = 16          # responses carry full reference lists; keep them small
MIN_INTERVAL = 1.3       # seconds between calls on the shared public pool
MAX_RETRIES = 4

_gate = asyncio.Lock()
_last_call = 0.0


class S2Error(RuntimeError):
    pass


async def _post(ids: list[str]) -> list[dict | None]:
    """One rate-limited batch call, retrying through 429/5xx."""
    global _last_call
    headers = {"x-api-key": API_KEY} if API_KEY else {}

    for attempt in range(MAX_RETRIES):
        async with _gate:
            wait = MIN_INTERVAL - (time.monotonic() - _last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(timeout=90.0) as client:
                    response = await client.post(
                        API,
                        params={"fields": FIELDS},
                        json={"ids": ids},
                        headers=headers,
                    )
            except httpx.HTTPError as exc:
                if attempt == MAX_RETRIES - 1:
                    raise S2Error(f"Semantic Scholar unreachable: {exc}") from exc
                response = None
            finally:
                _last_call = time.monotonic()

        if response is None:
            await asyncio.sleep(2 ** attempt)
            continue
        if response.status_code == 200:
            return response.json()
        if response.status_code in (429, 500, 502, 503, 504):
            await asyncio.sleep(2 ** attempt * 2)
            continue
        raise S2Error(
            f"Semantic Scholar error {response.status_code}: {response.text[:200]}"
        )
    raise S2Error("Semantic Scholar rate limit — try again in a minute.")


def _parse(entry: dict, requested_id: str) -> S2Paper:
    external = entry.get("externalIds") or {}
    references: list[S2Reference] = []
    for raw in entry.get("references") or []:
        if not raw:
            continue
        ids = raw.get("externalIds") or {}
        references.append(
            S2Reference(
                arxiv_id=(ids.get("ArXiv") or None),
                title=raw.get("title") or "",
                citation_count=raw.get("citationCount") or 0,
                year=raw.get("year"),
            )
        )
    return S2Paper(
        arxiv_id=external.get("ArXiv") or requested_id,
        title=entry.get("title") or "",
        year=entry.get("year"),
        citation_count=entry.get("citationCount") or 0,
        influential_count=entry.get("influentialCitationCount") or 0,
        reference_count=entry.get("referenceCount") or 0,
        references=references,
        fetched_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
    )


async def fetch_batch(arxiv_ids: list[str]) -> dict[str, S2Paper]:
    """Fetch metadata for arXiv ids. Unknown papers are simply absent."""
    results: dict[str, S2Paper] = {}
    for start in range(0, len(arxiv_ids), BATCH_SIZE):
        chunk = arxiv_ids[start : start + BATCH_SIZE]
        entries = await _post([f"ARXIV:{pid}" for pid in chunk])
        for requested, entry in zip(chunk, entries):
            if entry:
                results[requested] = _parse(entry, requested)
    return results
