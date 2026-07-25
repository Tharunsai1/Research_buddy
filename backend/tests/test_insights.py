"""Results-ledger filtering and gap-report assembly.

The LLM calls themselves are not exercised here — these cover the code that
decides what survives the call, which is where the bugs live.
"""

from __future__ import annotations

import pytest

from insights import _gap_context, is_config_metric
from models import Extraction

from conftest import make_paper


# ---------------------------------------------------------------------------
# Config-vs-result filtering
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "metric",
    [
        "Adam β1",
        "Adam beta2",
        "learning rate",
        "Learning Rate",
        "warmup steps",
        "dropout",
        "label smoothing",
        "weight decay",
        "batch size",
        "training steps",
        "epochs",
        "num_layers",
        "d_model",
        "hidden size",
        "beam size",
        "top-k",
    ],
)
def test_configuration_values_are_not_results(metric):
    """The model reliably returns "Adam beta1 = 0.9" as a result row. A prompt
    rule does not stop it, so these are dropped in code — a scoreboard full of
    optimizer constants is not comparable across papers."""
    assert is_config_metric(metric) is True


@pytest.mark.parametrize(
    "metric",
    [
        "BLEU",
        "accuracy",
        "F1",
        "EM",
        "win rate",
        "perplexity",
        "training time",
        "FLOPs",
        "throughput",
        "latency",
        "step time",
        "Recall@5",
    ],
)
def test_real_evaluation_metrics_survive(metric):
    """Measured costs stay: papers genuinely compete on training time and
    FLOPs, unlike an optimizer constant."""
    assert is_config_metric(metric) is False


def test_empty_metric_is_not_treated_as_config():
    assert is_config_metric("") is False
    assert is_config_metric(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Gap context
# ---------------------------------------------------------------------------

def _extraction(tldr: str) -> Extraction:
    return Extraction(
        tldr=tldr,
        problem="p",
        method="m",
        key_results="k",
        why_it_matters="w",
        keywords=["a", "b", "c"],
        paper_type="method",
    )


def test_gap_context_numbers_papers_from_one():
    """Papers are referenced by position, so the numbering the model sees has
    to match the list used to map its answer back to ids."""
    papers = [make_paper("1", "First"), make_paper("2", "Second")]
    context, ordered = _gap_context(papers, {}, [])
    assert "[1] First" in context
    assert "[2] Second" in context
    assert [p.id for p in ordered] == ["1", "2"]


def test_gap_context_includes_open_problems_without_duplicates():
    """The same open problem recurs across searches on one topic; repeating it
    crowds out the paper list the model needs to reason over."""
    searches = [
        {"open_problems": [{"title": "Evaluation", "description": "No benchmark."}]},
        {"open_problems": [{"title": "Evaluation", "description": "No benchmark."}]},
    ]
    context, _ = _gap_context([make_paper("1", "First")], {}, searches)
    assert context.count("Evaluation: No benchmark.") == 1


def test_gap_context_survives_searches_without_open_problems():
    context, _ = _gap_context([make_paper("1", "First")], {}, [{}, {"open_problems": None}])
    assert "OPEN PROBLEMS" not in context


def test_gap_context_uses_the_extraction_summary_when_present():
    papers = [make_paper("1", "First")]
    context, _ = _gap_context(papers, {"1": _extraction("A crisp one-liner.")}, [])
    assert "A crisp one-liner." in context
