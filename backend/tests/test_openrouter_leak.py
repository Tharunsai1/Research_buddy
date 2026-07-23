"""The provider-level half of the leak defence.

openrouter.parse_json checks for leaks inside its own repair loop, which is
cheaper than a fresh call because it reuses the retry conversation already
being built for JSON/schema failures. Two properties matter:

  * it shares meta_guard's patterns, so the two layers cannot drift apart;
  * exhausting the retries degrades to the contaminated-but-valid parse
    instead of raising, leaving llm.parse_json's guard to scrub it.

No network: _post is stubbed throughout.
"""

from __future__ import annotations

import json

import pytest

import meta_guard
import openrouter
from models import CritiqueOut

CLEAN = {
    "not_solved": "The paper omits a cost analysis.",
    "assumptions": ["Rewards are calibrated.", "The eval set is representative."],
    "weaknesses": ["Single dataset.", "No cost reported."],
    "reviewer_questions": ["How does it scale?", "What variance?", "Why this baseline?"],
}


def reply(payload: dict) -> dict:
    return {"choices": [{"message": {"content": json.dumps(payload)}}]}


@pytest.fixture
def responses(monkeypatch):
    """Script _post with a queue of message payloads."""
    calls = []

    def script(*payloads):
        queue = list(payloads)

        async def fake_post(payload):
            calls.append(payload)
            return reply(queue.pop(0) if queue else queue_last)

        nonlocal queue_last
        queue_last = payloads[-1]
        monkeypatch.setattr(openrouter, "_post", fake_post)
        return calls

    queue_last = CLEAN
    return script


async def test_detection_is_shared_with_meta_guard():
    """One pattern list. If these drift, a leak caught at one layer sails
    through the other."""
    dirty = CritiqueOut(**{**CLEAN, "not_solved": "As an AI, I cannot judge novelty."})
    assert openrouter._leaked_instruction(dirty) == meta_guard.find_leak_in(dirty)
    assert openrouter._leaked_instruction(CritiqueOut(**CLEAN)) is None


async def test_a_leak_is_retried_inside_the_provider_loop(responses):
    calls = responses({**CLEAN, "not_solved": "The user wants me to review this."}, CLEAN)
    result = await openrouter.parse_json(CritiqueOut, "sys", "usr", 800)
    assert result.not_solved == "The paper omits a cost analysis."
    assert len(calls) == 2


async def test_the_retry_tells_the_model_what_went_wrong(responses):
    calls = responses({**CLEAN, "not_solved": "The user wants me to review this."}, CLEAN)
    await openrouter.parse_json(CritiqueOut, "sys", "usr", 800)
    followup = json.dumps(calls[1]["messages"])
    assert "echoed system-prompt" in followup


async def test_mid_text_leaks_are_caught_not_just_opening_ones(responses):
    """The previous detector was anchored to the start of the field, so a
    preamble that began with real prose slipped through. This leak was found
    in real stored data (2401.15884)."""
    leaked = {**CLEAN, "weaknesses": ["The section digests accurately represent the paper."]}
    calls = responses(leaked, CLEAN)
    result = await openrouter.parse_json(CritiqueOut, "sys", "usr", 800)
    assert len(calls) == 2, "a mid-text leak must still trigger a retry"
    assert result.weaknesses == CLEAN["weaknesses"]


async def test_persistent_leaks_degrade_instead_of_raising(responses):
    """Raising here would discard an otherwise-complete deep dive at its last
    stage. The caller's guard scrubs what comes back instead."""
    leaked = {**CLEAN, "not_solved": "The user wants me to review this. Costs are omitted."}
    calls = responses(leaked, leaked, leaked)
    result = await openrouter.parse_json(CritiqueOut, "sys", "usr", 800)
    assert len(calls) == 3
    assert meta_guard.scrub(result).not_solved == "Costs are omitted."


async def test_malformed_output_still_fails_loudly(monkeypatch):
    """Degrading is only right for contaminated-but-valid content. A reply
    that never parses is a real error and must surface."""
    async def fake_post(payload):
        return {"choices": [{"message": {"content": "not json at all"}}]}

    monkeypatch.setattr(openrouter, "_post", fake_post)
    with pytest.raises(openrouter.OpenRouterError):
        await openrouter.parse_json(CritiqueOut, "sys", "usr", 800)


async def test_clean_output_returns_on_the_first_call(responses):
    calls = responses(CLEAN)
    result = await openrouter.parse_json(CritiqueOut, "sys", "usr", 800)
    assert result.not_solved == "The paper omits a cost analysis."
    assert len(calls) == 1
