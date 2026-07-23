"""The leak guard, and the retry path it drives in llm.parse_json.

The false-positive tests carry the most weight: a pattern that fires on real
paper prose would silently delete a reader's content, which is worse than the
leak the guard exists to catch.
"""

from __future__ import annotations

import pytest

import llm
import meta_guard
from models import CritiqueOut

# The real failure, verbatim in shape: the model narrating its instructions
# instead of reviewing quant-ph/1511.04206.
OBSERVED_LEAK = (
    "The user wants me to write a peer review of this paper. I should focus on "
    "the claims and evidence and avoid mentioning the digest."
)


@pytest.mark.parametrize(
    "text",
    [
        OBSERVED_LEAK,
        "My task is to critique this work.",
        "As an AI, I cannot verify the experimental setup.",
        "Let me analyze the results section first.",
        "Here is my peer review of the paper.",
        "Based on the provided digests, the method is unclear.",
        "The section digests omit the ablation table.",
        "Okay, the paper proposes a new sampler.",
        "I'll summarize the weaknesses below.",
        # Typographic apostrophes: models mix these with ASCII ones freely,
        # and matching only ASCII would let the same phrase through.
        "I’ll summarize the weaknesses below.",
        "Here’s my peer review of the paper.",
        "I’ve been asked to critique this work.",
    ],
)
def test_flags_meta_commentary(text):
    assert meta_guard.find_leak(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        # Ordinary critique prose.
        "The paper does not report inference cost on the 70B model.",
        "Results are shown on a single dataset, so generalization is unclear.",
        "The authors assume the reward model is well calibrated.",
        # Reviewer voice — first person is legitimate here and must survive.
        "I would want to see an ablation over retrieval depth.",
        "I am not convinced the baseline is tuned fairly.",
        # Domain vocabulary that naive patterns would wreck: "prompt" is
        # everywhere in LLM papers and "digest" is a hashing term.
        "The prompt template used for few-shot evaluation is not released.",
        "Prompt sensitivity is not measured across paraphrases.",
        "The digest size of the SHA-256 hash bounds collision resistance.",
        "Instructions in the training set are synthetically generated.",
        "",
    ],
)
def test_leaves_real_prose_alone(text):
    assert meta_guard.find_leak(text) is None


def test_strip_meta_keeps_the_answer_after_the_preamble():
    text = "The user wants me to critique this. The paper omits a cost analysis."
    assert meta_guard.strip_meta(text) == "The paper omits a cost analysis."


def test_strip_meta_only_strips_leading_sentences():
    """A late match is more likely a false positive than a real leak, so
    sentences after the real content begins are preserved."""
    text = "The paper omits a cost analysis. My task is unclear here."
    assert meta_guard.strip_meta(text) == text


def test_strip_meta_returns_empty_when_everything_is_meta():
    assert meta_guard.strip_meta("The user wants a review. My task is to write it.") == ""


def _critique(not_solved: str) -> CritiqueOut:
    return CritiqueOut(
        not_solved=not_solved,
        assumptions=["Rewards are calibrated.", "The eval set is representative."],
        weaknesses=["Single dataset.", "No cost reported."],
        reviewer_questions=["How does it scale?", "What is the variance?", "Why this baseline?"],
    )


def test_find_leak_in_walks_every_string_field():
    dirty = _critique("Fine.")
    dirty.weaknesses.append("As an AI, I cannot assess novelty.")
    assert meta_guard.find_leak_in(dirty) is not None
    assert meta_guard.find_leak_in(_critique("The paper omits a cost analysis.")) is None


def test_scrub_cleans_fields_but_keeps_the_shape():
    dirty = _critique("The user wants me to review this. The paper omits costs.")
    clean = meta_guard.scrub(dirty)
    assert clean.not_solved == "The paper omits costs."
    assert len(clean.assumptions) == 2
    assert isinstance(clean, CritiqueOut)


def test_scrub_never_passes_through_a_wholly_meta_field():
    """The reported bug was the monologue being shown as if it were a
    critique. A field with no real content must say so, not echo it back."""
    dirty = _critique("The user wants a review.")
    assert meta_guard.scrub(dirty).not_solved == meta_guard.UNAVAILABLE


def test_scrub_reports_a_list_emptied_by_scrubbing():
    dirty = _critique("Fine.")
    dirty.weaknesses = ["As an AI, I cannot judge this.", "My task is to list weaknesses."]
    assert meta_guard.scrub(dirty).weaknesses == [meta_guard.UNAVAILABLE]


def test_scrub_leaves_an_originally_empty_list_empty():
    dirty = _critique("The user wants a review.")
    dirty.assumptions = []
    assert meta_guard.scrub(dirty).assumptions == []


# ---------------------------------------------------------------------------
# llm.parse_json guard/retry wiring
# ---------------------------------------------------------------------------

@pytest.fixture
def dispatches(monkeypatch):
    """Replace the provider call with a scripted list of results."""
    calls: list[str] = []

    def script(*results):
        queue = list(results)

        async def fake(schema, system, user, max_tokens, thinking):
            calls.append(system)
            item = queue.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(llm, "_dispatch", fake)
        return calls

    return script


GUARD = {
    "guard": meta_guard.find_leak_in,
    "repair": meta_guard.scrub,
    "retry_instruction": meta_guard.RETRY_INSTRUCTION,
}


async def test_clean_output_costs_no_retry(dispatches):
    calls = dispatches(_critique("The paper omits a cost analysis."))
    result = await llm.parse_json(CritiqueOut, "sys", "usr", **GUARD)
    assert result.not_solved == "The paper omits a cost analysis."
    assert len(calls) == 1


async def test_leak_triggers_one_retry_and_returns_the_clean_result(dispatches):
    calls = dispatches(_critique(OBSERVED_LEAK), _critique("The paper omits costs."))
    result = await llm.parse_json(CritiqueOut, "sys", "usr", **GUARD)
    assert result.not_solved == "The paper omits costs."
    assert len(calls) == 2
    # The retry must tell the model what was wrong, quoting the offending text.
    assert "leaked meta-commentary" in calls[1]
    assert "The user wants" in calls[1]


async def test_two_leaks_are_scrubbed_rather_than_raising(dispatches):
    """A deep dive costs minutes; the critique is its last stage. Losing the
    whole read to a cosmetic defect is the worse outcome."""
    dispatches(
        _critique(OBSERVED_LEAK),
        _critique("My task is to review. The sampler is undertested."),
    )
    result = await llm.parse_json(CritiqueOut, "sys", "usr", **GUARD)
    assert result.not_solved == "The sampler is undertested."


async def test_a_failed_retry_falls_back_to_the_scrubbed_first_answer(dispatches):
    """The observed leak is meta in both sentences, so nothing survives
    scrubbing and the field reports itself as unavailable."""
    dispatches(_critique(OBSERVED_LEAK), llm.LLMError("provider down"))
    result = await llm.parse_json(CritiqueOut, "sys", "usr", **GUARD)
    assert result.not_solved == meta_guard.UNAVAILABLE
    assert result.weaknesses == ["Single dataset.", "No cost reported."]


async def test_no_guard_means_no_extra_work(dispatches):
    calls = dispatches(_critique(OBSERVED_LEAK))
    result = await llm.parse_json(CritiqueOut, "sys", "usr")
    assert result.not_solved == OBSERVED_LEAK
    assert len(calls) == 1
