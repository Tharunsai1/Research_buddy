"""Shared fixtures.

The one rule that matters here: a test must never touch backend/data/. That
directory is the user's real library â€” papers, deep dives, appraisals
history â€” and `remove_paper` deletes files for a living. Every test that
reaches the storage layer goes through `isolated_store`, which repoints all of
store.py's path constants at a tmp directory and swaps in an empty collection.
"""

from __future__ import annotations

import json

import pytest

import store
from models import Paper

# Path constants in store.py are read from module scope inside each function,
# so monkeypatching the module attribute is enough to redirect every write â€”
# PROVIDED every constant is listed here. One was not: LIBRARY_INDEX_FILE was
# added to store.py without a matching line below, so a remove_paper test
# wrote a fake embedding straight into the real backend/data/library_index.json
# (caught by inspecting live output, not by this suite â€” nothing here would
# have failed). test_every_store_path_constant_is_sandboxed exists so the next
# omission fails loudly here instead of silently reaching real user data.
_STORE_DIRS = [
    "SEARCHES_DIR",
    "DEEP_DIR",
    "INDEX_DIR",
    "S2_DIR",
    "MATRIX_DIR",
    "APPRAISALS_DIR",
    "DIGEST_DIR",
    "UPLOADS_DIR",
    "RESULTS_DIR",
    "REVIEWS_DIR",
    "HIGHLIGHTS_DIR",
]
_STORE_FILES = [
    "COLLECTION_FILE",
    "SETTINGS_FILE",
    "LIBRARY_INDEX_FILE",
    "GAPS_FILE",
]


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    """Redirect the storage layer at a tmp dir with an empty collection."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(store, "DATA_DIR", root)
    for name in _STORE_DIRS:
        monkeypatch.setattr(store, name, root / name.replace("_DIR", "").lower())
    for name in _STORE_FILES:
        monkeypatch.setattr(store, name, root / name.replace("_FILE", "").lower())
    monkeypatch.setattr(store, "_collection", json.loads(json.dumps(store._EMPTY)))
    return store


def make_paper(paper_id: str, title: str, published: str = "2020-06-19") -> Paper:
    return Paper(
        id=paper_id,
        title=title,
        authors=["A. Researcher", "B. Coauthor"],
        abstract=f"We study {title}.",
        published=published,
        categories=["cs.LG"],
        primary_category="cs.LG",
        arxiv_url=f"https://arxiv.org/abs/{paper_id}",
        pdf_url=f"https://arxiv.org/pdf/{paper_id}",
    )


@pytest.fixture
def papers() -> dict[str, Paper]:
    """A small library, including a pre-2007 id whose slash has broken
    routing and file writes before (see store._safe)."""
    return {
        p.id: p
        for p in [
            make_paper("2006.11239", "Denoising Diffusion Probabilistic Models", "2020-06-19"),
            make_paper("1706.03762", "Attention Is All You Need", "2017-06-12"),
            make_paper("2005.11401", "Retrieval-Augmented Generation", "2020-05-22"),
            make_paper("quant-ph/9903061", "Quantum Algorithms: An Overview", "1999-03-18"),
        ]
    }


@pytest.fixture
def search_a() -> dict:
    return {
        "id": "llm-agents-aaa111",
        "query": "LLM agents",
        "title": "LLM Agents",
        "created_at": "2026-07-12T10:00:00",
        "paper_ids": ["1706.03762", "2005.11401"],
        "overview": "An early look at agent architectures.",
        "clusters": [
            {
                "name": "Attention architectures",
                "description": "Transformer foundations.",
                "paper_ids": ["1706.03762"],
            },
            {
                "name": "Retrieval",
                "description": "Grounding generation in documents.",
                "paper_ids": ["2005.11401"],
            },
        ],
        "edges": [
            {
                "source": "2005.11401",
                "target": "1706.03762",
                "kind": "builds_on",
                "description": "RAG uses the transformer as its generator backbone.",
            }
        ],
        "reading_order": [
            {"paper_id": "1706.03762", "stage": "foundation", "why": "The base architecture."},
            {"paper_id": "2005.11401", "stage": "core", "why": "Adds retrieval."},
        ],
        "consensus": ["Scaling helps.", "Retrieval reduces hallucination."],
        "tensions": [{"name": "Cost vs quality", "description": "Bigger is dearer."}],
        "open_problems": [{"title": "Long-horizon planning", "description": "Still unsolved."}],
    }


def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def make_test_pdf(pages: list[list[str]]) -> bytes:
    """A minimal, real, valid PDF with real text â€” no reportlab dependency
    just for tests. One Helvetica line per string, top-down from y=740.

    Used both for pdf_ingest's own unit tests and to drive a genuine
    end-to-end upload through the real /api/papers/upload endpoint.
    """
    objects: list[bytes] = []
    page_obj_nums = []
    next_num = 4  # 1=Catalog, 2=Pages, 3=Font; pages/streams start at 4

    page_refs = []
    content_objs = []
    for lines in pages:
        page_num = next_num
        next_num += 1
        content_num = next_num
        next_num += 1
        page_obj_nums.append(page_num)
        page_refs.append(page_num)

        ops = ["BT", "/F1 11 Tf", "72 740 Td"]
        for i, line in enumerate(lines):
            if i > 0:
                ops.append("0 -16 Td")
            ops.append(f"({_pdf_escape(line)}) Tj")
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1", errors="replace")

        page_body = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
        ).encode()
        objects.append((page_num, page_body))
        content_objs.append(
            (content_num, b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        )

    kids = " ".join(f"{n} 0 R" for n in page_refs)
    header_objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>".encode()),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    all_objects = header_objects + objects + content_objs
    all_objects.sort(key=lambda pair: pair[0])

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num, body in all_objects:
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_offset = len(out)
    total = len(all_objects) + 1
    out += f"xref\n0 {total}\n".encode()
    out += b"0000000000 65535 f \n"
    for num, _ in all_objects:
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {total} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF"
    ).encode()
    return bytes(out)


@pytest.fixture
def search_b() -> dict:
    return {
        "id": "llm-agents-bbb222",
        "query": "LLM agents",
        "title": "LLM Agents",
        "created_at": "2026-07-23T10:00:00",
        "paper_ids": ["2005.11401", "2006.11239"],
        "overview": "A later look, after diffusion entered the picture.",
        "clusters": [
            {
                "name": "Retrieval",
                "description": "Grounding generation in documents.",
                "paper_ids": ["2005.11401"],
            },
            {
                "name": "Generative models",
                "description": "Diffusion-based generation.",
                "paper_ids": ["2006.11239"],
            },
        ],
        "edges": [],
        "reading_order": [
            {"paper_id": "2005.11401", "stage": "foundation", "why": "Retrieval basics."},
        ],
        "consensus": ["Retrieval reduces hallucination.", "Tool use is essential."],
        "tensions": [{"name": "Autonomy vs control", "description": "Who is in charge."}],
        "open_problems": [{"title": "Evaluation", "description": "No agreed benchmark."}],
    }

