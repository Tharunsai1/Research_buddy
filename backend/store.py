"""Disk persistence (JSON files under backend/data) + in-memory job registry."""

from __future__ import annotations

import json
import re
import secrets
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from models import DeepJob, Extraction, Job, Paper

DATA_DIR = Path(__file__).parent / "data"
SEARCHES_DIR = DATA_DIR / "searches"
DEEP_DIR = DATA_DIR / "deep"
INDEX_DIR = DATA_DIR / "index"
S2_DIR = DATA_DIR / "s2"
MATRIX_DIR = DATA_DIR / "matrix"
CARDS_DIR = DATA_DIR / "cards"
DIGEST_DIR = DATA_DIR / "digests"
COLLECTION_FILE = DATA_DIR / "collection.json"

_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Collection (papers + extractions + read state + global map + search index)
# ---------------------------------------------------------------------------

_EMPTY: dict[str, Any] = {
    "papers": {},        # id -> Paper dict
    "extractions": {},   # id -> Extraction dict
    "read": [],          # list of paper ids
    "paper_search": {},  # id -> query of the search that first added it
    "map": {"clusters": [], "bridge_edges": []},
    "searches": [],      # [{id, query, title, created_at, paper_count}]
}


def _load_collection() -> dict[str, Any]:
    if COLLECTION_FILE.exists():
        try:
            data = json.loads(COLLECTION_FILE.read_text(encoding="utf-8"))
            return {**_EMPTY, **data}
        except Exception:
            pass
    return json.loads(json.dumps(_EMPTY))


_collection = _load_collection()


def _save_collection() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = COLLECTION_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_collection, indent=1), encoding="utf-8")
    tmp.replace(COLLECTION_FILE)


def get_cached_extractions(paper_ids: list[str]) -> dict[str, Extraction]:
    with _lock:
        return {
            pid: Extraction(**_collection["extractions"][pid])
            for pid in paper_ids
            if pid in _collection["extractions"]
        }


def merge_search_results(
    query: str,
    papers: list[Paper],
    extractions: dict[str, Extraction],
) -> None:
    with _lock:
        for paper in papers:
            _collection["papers"][paper.id] = paper.model_dump()
            _collection["paper_search"].setdefault(paper.id, query)
        for pid, ex in extractions.items():
            _collection["extractions"][pid] = ex.model_dump()
        _save_collection()


def add_search_meta(meta: dict[str, Any]) -> None:
    with _lock:
        _collection["searches"].append(meta)
        _save_collection()


def set_global_map(clusters: list[dict], bridge_edges: list[dict]) -> None:
    with _lock:
        _collection["map"] = {"clusters": clusters, "bridge_edges": bridge_edges}
        _save_collection()


def set_read(paper_id: str, read: bool) -> list[str]:
    with _lock:
        read_set = set(_collection["read"])
        (read_set.add if read else read_set.discard)(paper_id)
        _collection["read"] = sorted(read_set)
        _save_collection()
        return _collection["read"]


def collection_snapshot() -> dict[str, Any]:
    with _lock:
        return json.loads(json.dumps(_collection))


def all_papers() -> list[Paper]:
    with _lock:
        return [Paper(**p) for p in _collection["papers"].values()]


def all_extractions() -> dict[str, Extraction]:
    with _lock:
        return {pid: Extraction(**e) for pid, e in _collection["extractions"].items()}


def paper_search_map() -> dict[str, str]:
    with _lock:
        return dict(_collection["paper_search"])


def existing_cluster_names() -> list[str]:
    with _lock:
        return [c["name"] for c in _collection["map"]["clusters"]]


def existing_map() -> dict[str, Any]:
    with _lock:
        return json.loads(json.dumps(_collection["map"]))


# ---------------------------------------------------------------------------
# Search results (one JSON file per search)
# ---------------------------------------------------------------------------

def make_search_id(query: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")[:40] or "search"
    return f"{slug}-{secrets.token_hex(3)}"


def save_search(search: dict[str, Any]) -> None:
    SEARCHES_DIR.mkdir(parents=True, exist_ok=True)
    path = SEARCHES_DIR / f"{search['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(search, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_search(search_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[a-z0-9-]+", search_id):
        return None
    path = SEARCHES_DIR / f"{search_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# arXiv's pre-2007 ids carry a slash ("quant-ph/9903061"). A slash is a
# directory separator on disk, so it is folded into the filename rather than
# rejected — rejecting it silently dropped every deep dive, index, card and
# citation record for those papers.
_SAFE_ID = re.compile(r"[A-Za-z0-9._/-]+")


def _safe(paper_id: str) -> str | None:
    """Filename stem for a paper id, or None when the id is not storable."""
    if not _SAFE_ID.fullmatch(paper_id) or ".." in paper_id:
        return None
    return paper_id.replace("/", "__")


def _unsafe(stem: str) -> str:
    """Inverse of `_safe` — recover the paper id from a filename stem."""
    return stem.replace("__", "/")


def save_deep_dive(paper_id: str, deep: dict[str, Any]) -> None:
    if not _safe(paper_id):
        return
    DEEP_DIR.mkdir(parents=True, exist_ok=True)
    path = DEEP_DIR / f"{_safe(paper_id)}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(deep, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_deep_dive(paper_id: str) -> dict[str, Any] | None:
    if not _safe(paper_id):
        return None
    path = DEEP_DIR / f"{_safe(paper_id)}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def deep_dive_ids() -> list[str]:
    if not DEEP_DIR.exists():
        return []
    return sorted(_unsafe(p.stem) for p in DEEP_DIR.glob("*.json"))


def save_index(paper_id: str, records: list[dict[str, Any]]) -> None:
    if not _safe(paper_id):
        return
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    path = INDEX_DIR / f"{_safe(paper_id)}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(records), encoding="utf-8")
    tmp.replace(path)


def load_index(paper_id: str) -> list[dict[str, Any]]:
    if not _safe(paper_id):
        return []
    path = INDEX_DIR / f"{_safe(paper_id)}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_s2(paper_id: str, data: dict[str, Any]) -> None:
    if not _safe(paper_id):
        return
    S2_DIR.mkdir(parents=True, exist_ok=True)
    path = S2_DIR / f"{_safe(paper_id)}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def load_s2(paper_id: str) -> dict[str, Any] | None:
    if not _safe(paper_id):
        return None
    path = S2_DIR / f"{_safe(paper_id)}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def all_s2() -> dict[str, dict[str, Any]]:
    if not S2_DIR.exists():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for path in S2_DIR.glob("*.json"):
        try:
            out[_unsafe(path.stem)] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return out


SETTINGS_FILE = DATA_DIR / "settings.json"


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge and persist UI-level settings (e.g. the chosen model)."""
    current = load_settings()
    current.update(patch)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=1), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)
    return current


def load_settings() -> dict[str, Any]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_matrix_row(paper_id: str, row: dict[str, Any]) -> None:
    if not _safe(paper_id):
        return
    MATRIX_DIR.mkdir(parents=True, exist_ok=True)
    path = MATRIX_DIR / f"{_safe(paper_id)}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(row, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_matrix_row(paper_id: str) -> dict[str, Any] | None:
    if not _safe(paper_id):
        return None
    path = MATRIX_DIR / f"{_safe(paper_id)}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_cards(paper_id: str, cards: list[dict[str, Any]]) -> None:
    if not _safe(paper_id):
        return
    CARDS_DIR.mkdir(parents=True, exist_ok=True)
    path = CARDS_DIR / f"{_safe(paper_id)}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cards, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_cards(paper_id: str) -> list[dict[str, Any]]:
    if not _safe(paper_id):
        return []
    path = CARDS_DIR / f"{_safe(paper_id)}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def all_cards() -> list[dict[str, Any]]:
    if not CARDS_DIR.exists():
        return []
    cards: list[dict[str, Any]] = []
    for path in sorted(CARDS_DIR.glob("*.json")):
        try:
            cards.extend(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return cards


def card_paper_ids() -> list[str]:
    if not CARDS_DIR.exists():
        return []
    return sorted(_unsafe(p.stem) for p in CARDS_DIR.glob("*.json"))


def update_card(card: dict[str, Any]) -> None:
    """Persist one card's review state back into its paper's file."""
    paper_id = card.get("paper_id", "")
    cards = load_cards(paper_id)
    for index, existing in enumerate(cards):
        if existing.get("id") == card.get("id"):
            cards[index] = card
            save_cards(paper_id, cards)
            return


def save_digest(search_id: str, digest: dict[str, Any]) -> None:
    if not re.fullmatch(r"[a-z0-9-]+", search_id):
        return
    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    path = DIGEST_DIR / f"{search_id}.json"
    history: list[dict[str, Any]] = []
    if path.exists():
        try:
            history = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.insert(0, digest)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(history[:20], indent=1), encoding="utf-8")
    tmp.replace(path)


def load_digests(search_id: str) -> list[dict[str, Any]]:
    if not re.fullmatch(r"[a-z0-9-]+", search_id):
        return []
    path = DIGEST_DIR / f"{search_id}.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def remove_paper(paper_id: str) -> dict[str, Any]:
    """Undo: drop a paper from the library, every search, and every per-paper file.

    Exists mainly for the "+ Add" prerequisite flow — a paper placed in the
    wrong cluster (or the wrong search entirely) previously had no way back
    out short of asking for a manual fix. Works for any paper, not just added
    prerequisites.
    """
    with _lock:
        was_in_library = paper_id in _collection["papers"]
        _collection["papers"].pop(paper_id, None)
        _collection["extractions"].pop(paper_id, None)
        _collection["paper_search"].pop(paper_id, None)
        _collection["read"] = [p for p in _collection["read"] if p != paper_id]

        clusters = [
            {**c, "paper_ids": [p for p in c["paper_ids"] if p != paper_id]}
            for c in _collection["map"]["clusters"]
        ]
        _collection["map"]["clusters"] = [c for c in clusters if c["paper_ids"]]
        _collection["map"]["bridge_edges"] = [
            e
            for e in _collection["map"]["bridge_edges"]
            if paper_id not in (e["source"], e["target"])
        ]

        touched_searches: list[str] = []
        if SEARCHES_DIR.exists():
            for path in SEARCHES_DIR.glob("*.json"):
                try:
                    search = json.loads(path.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if paper_id not in search.get("paper_ids", []):
                    continue
                search["paper_ids"] = [p for p in search["paper_ids"] if p != paper_id]
                search["clusters"] = [
                    {**c, "paper_ids": [p for p in c["paper_ids"] if p != paper_id]}
                    for c in search.get("clusters", [])
                ]
                search["clusters"] = [c for c in search["clusters"] if c["paper_ids"]]
                search["edges"] = [
                    e
                    for e in search.get("edges", [])
                    if paper_id not in (e["source"], e["target"])
                ]
                search["reading_order"] = [
                    s for s in search.get("reading_order", []) if s["paper_id"] != paper_id
                ]
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(search, indent=1), encoding="utf-8")
                tmp.replace(path)
                touched_searches.append(search["id"])
                for meta in _collection["searches"]:
                    if meta["id"] == search["id"]:
                        meta["paper_count"] = len(search["paper_ids"])

        _save_collection()

    safe = _safe(paper_id)
    if safe:
        for directory in (DEEP_DIR, INDEX_DIR, S2_DIR, MATRIX_DIR, CARDS_DIR):
            path = directory / f"{safe}.json"
            if path.exists():
                path.unlink()

    return {"removed": was_in_library, "searches_updated": touched_searches}


def all_search_edges() -> list[dict[str, Any]]:
    """Union of relationship edges across every saved search (for the global map)."""
    edges: list[dict[str, Any]] = []
    if SEARCHES_DIR.exists():
        for path in SEARCHES_DIR.glob("*.json"):
            try:
                edges.extend(json.loads(path.read_text(encoding="utf-8")).get("edges", []))
            except Exception:
                continue
    return edges


# ---------------------------------------------------------------------------
# Jobs (in-memory)
# ---------------------------------------------------------------------------

JOBS: dict[str, Job] = {}
DEEP_JOBS: dict[str, DeepJob] = {}


def create_job(query: str) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], query=query)
    JOBS[job.id] = job
    _prune_jobs()
    return job


def create_deep_job(paper_id: str) -> DeepJob:
    job = DeepJob(id=uuid.uuid4().hex[:12], paper_id=paper_id)
    DEEP_JOBS[job.id] = job
    cutoff = time.time() - 3600.0
    for job_id in [j for j, existing in DEEP_JOBS.items() if existing.created_at < cutoff]:
        del DEEP_JOBS[job_id]
    return job


def running_deep_job(paper_id: str) -> DeepJob | None:
    return next(
        (j for j in DEEP_JOBS.values() if j.paper_id == paper_id and j.status == "running"),
        None,
    )


def _prune_jobs(max_age_seconds: float = 3600.0) -> None:
    cutoff = time.time() - max_age_seconds
    for job_id in [j for j, job in JOBS.items() if job.created_at < cutoff]:
        del JOBS[job_id]
