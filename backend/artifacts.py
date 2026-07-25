"""Can you actually build on this paper?

Scans a paper's own text for released code and for the details you need to
reproduce a result — seeds, hyperparameters, hardware, error bars. Pure text
analysis on purpose: no LLM call and no network, so this runs over the whole
library instantly and costs nothing against the daily cap. That also makes it
deterministic and unit-testable, unlike an LLM judgement.

These are *signals*, not ground truth. A paper can name a learning rate in a
figure caption this never sees, and a repo link can 404. Anything user-facing
should say "the paper mentions", not "the paper has".
"""

from __future__ import annotations

import re

# Repo hosts worth surfacing. Deliberately not matching bare "git" or personal
# homepages: a link the reader cannot immediately clone is noise here.
_REPO_HOSTS = r"(?:github\.com|gitlab\.com|bitbucket\.org|huggingface\.co)"

# arXiv HTML and PDF text both wrap URLs, and PDF extraction frequently glues
# a trailing sentence period onto the path. Capture generously, then trim.
_URL = re.compile(
    r"(?:https?://)?(?:www\.)?(" + _REPO_HOSTS + r"/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+)",
    re.IGNORECASE,
)

# Trailing characters that are almost always sentence punctuation rather than
# part of the path.
_TRIM = ".,;:)]}>\"'`"

# A bare host, or a host plus one path segment that is a well-known non-repo
# route, is not a usable code link.
_NOT_A_REPO = re.compile(
    r"^(?:" + _REPO_HOSTS + r")/(?:about|pricing|features|login|signup|search|topics)?/?$",
    re.IGNORECASE,
)


def find_repo_links(text: str) -> list[str]:
    """Every distinct code-repository URL mentioned in the text, in order.

    Deduplicates case-insensitively but preserves the first spelling seen —
    GitHub paths are case-sensitive in practice even though the host is not.
    """
    out: list[str] = []
    seen: set[str] = set()
    for match in _URL.finditer(text or ""):
        path = match.group(1).rstrip(_TRIM)
        # A URL split across a line break in PDF text can pick up the next
        # word; stop at whitespace defensively.
        path = path.split()[0] if path.split() else ""
        if not path or _NOT_A_REPO.match(path):
            continue
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(f"https://{path}")
    return out


# Each signal: (key, human label, patterns). Phrases are chosen to be specific
# enough to avoid the obvious false positive — "seed" alone matches "seed set"
# and "seeded", so require the reproducibility sense.
_SIGNALS: list[tuple[str, str, list[str]]] = [
    (
        "seeds",
        "random seeds",
        [r"random seed", r"\bseed(?:s)?\s*(?:=|:)\s*\d", r"averaged over \d+ seeds", r"\d+ random seeds"],
    ),
    (
        "hyperparameters",
        "hyperparameters",
        [
            r"hyper-?parameter",
            r"learning rate",
            r"batch size",
            r"weight decay",
            r"\boptimiz(?:er|ation) (?:was|is|:)",
            r"\bAdam\b",
            r"\bAdamW\b",
            r"dropout rate",
            r"\d+ epochs",
        ],
    ),
    (
        "hardware",
        "hardware / compute",
        [
            r"\bGPUs?\b",
            r"\bTPUs?\b",
            r"\b[AVHP]100\b",
            r"\bRTX\b",
            r"GPU[- ]hours",
            r"compute budget",
            r"\bFLOPs?\b",
        ],
    ),
    (
        "variance",
        "error bars / variance",
        [
            r"standard deviation",
            r"standard error",
            r"error bars?",
            r"confidence interval",
            r"±",
            r"averaged over \d+ runs",
            r"\d+ independent runs",
        ],
    ),
    (
        "data",
        "data availability",
        [
            r"dataset is (?:publicly )?available",
            r"we release",
            r"publicly available",
            r"open[- ]sourced?",
            r"available at",
        ],
    ),
]

_COMPILED = [
    (key, label, [re.compile(p, re.IGNORECASE) for p in pats]) for key, label, pats in _SIGNALS
]


def repro_signals(text: str) -> dict[str, bool]:
    """Which reproducibility details the text actually mentions."""
    body = text or ""
    return {key: any(p.search(body) for p in pats) for key, _label, pats in _COMPILED}


SIGNAL_LABELS: dict[str, str] = {key: label for key, label, _ in _SIGNALS}


def assess(text: str, *, scanned_full_text: bool) -> dict:
    """Everything the UI needs for one paper.

    `scanned_full_text` matters a lot for how the result should be read: an
    abstract-only scan finding no hyperparameters means almost nothing, while
    a full-text scan finding none is genuinely informative. The caller knows
    which it did, so it is passed in rather than guessed from length.
    """
    repos = find_repo_links(text)
    signals = repro_signals(text)
    return {
        "repos": repos,
        "has_code": bool(repos),
        "signals": signals,
        "signal_count": sum(1 for v in signals.values() if v),
        "signal_total": len(signals),
        "scanned_full_text": scanned_full_text,
    }
