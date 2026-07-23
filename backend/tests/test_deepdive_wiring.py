"""The deep-dive pipeline must actually apply the leak guard.

meta_guard's own tests prove the detector works; these prove run_deep_dive is
wired to use it. That distinction matters — the original bug shipped with a
prompt that already forbade the leaked phrasing, so "the rule exists" and "the
rule is enforced on the output" are different claims.

Every provider call is stubbed, so this makes no network requests.
"""

from __future__ import annotations

import pytest

import llm
import meta_guard
from deepdive import run_deep_dive
from fulltext import FullText, Section
from models import (
    CritiqueOut,
    ExplanationsOut,
    GlossaryOut,
    GlossaryTermOut,
    SectionDigestOut,
    SynthesisOut,
)
from tests.conftest import make_paper

# The shape of the real failure: the model narrating the task, then answering.
PREAMBLE = "The user wants me to write a peer review of this paper."
REAL = "The paper reports no runtime cost for the 550B configuration."


def leaked(schema):
    """A valid instance of `schema` whose every text field starts with the
    model restating its instructions."""
    text = f"{PREAMBLE} {REAL}"
    if schema is SectionDigestOut:
        return SectionDigestOut(summary=text, key_points=[text])
    if schema is SynthesisOut:
        return SynthesisOut(deep_summary=text, contributions=[text], results_detail=text)
    if schema is ExplanationsOut:
        return ExplanationsOut(undergrad=text, grad=text, expert=text)
    if schema is GlossaryOut:
        return GlossaryOut(terms=[GlossaryTermOut(term="Qubit", definition=text, in_this_paper=text)])
    if schema is CritiqueOut:
        return CritiqueOut(
            not_solved=text, assumptions=[text], weaknesses=[text], reviewer_questions=[text]
        )
    raise AssertionError(f"unhandled schema {schema}")


@pytest.fixture
def paper():
    return make_paper("quant-ph/1511.04206", "Quantum Algorithms: An Overview", "2015-11-13")


@pytest.fixture
def full(paper):
    return FullText(
        paper_id=paper.id,
        source_url="https://arxiv.org/abs/quant-ph/1511.04206",
        abstract="An overview of quantum algorithms.",
        sections=[Section(title="Introduction", text="word " * 400)],
    )


@pytest.fixture
def always_leaks(monkeypatch):
    """Every call to the provider returns meta-commentary, retries included."""
    calls = []

    async def fake(schema, system, user, max_tokens, thinking):
        calls.append(schema)
        return leaked(schema)

    monkeypatch.setattr(llm, "_dispatch", fake)
    return calls


@pytest.fixture
def leaks_once(monkeypatch):
    """Leaks on the first attempt per schema, then answers cleanly — the case
    the retry is meant to rescue."""
    seen = set()

    async def fake(schema, system, user, max_tokens, thinking):
        if schema in seen:
            clean = leaked(schema)
            return meta_guard.scrub(clean.__class__(**{
                k: (REAL if isinstance(v, str) else
                    [REAL if isinstance(i, str) else i for i in v] if isinstance(v, list) else v)
                for k, v in clean.__dict__.items()
            }))
        seen.add(schema)
        return leaked(schema)

    monkeypatch.setattr(llm, "_dispatch", fake)


def texts(deep) -> list[str]:
    """Every string a reader can see in a finished deep dive."""
    out = [deep.deep_summary, deep.results_detail, *deep.contributions]
    out += [deep.explanations.undergrad, deep.explanations.grad, deep.explanations.expert]
    for term in deep.glossary:
        out += [term.definition, term.in_this_paper]
    out += [deep.critique.not_solved, *deep.critique.assumptions]
    out += [*deep.critique.weaknesses, *deep.critique.reviewer_questions]
    for section in deep.sections:
        out += [section.summary, *section.key_points]
    return out


async def test_a_retry_rescues_the_read(paper, full, leaks_once):
    deep = await run_deep_dive(paper, full, on_progress=lambda _: None)
    for text in texts(deep):
        assert meta_guard.find_leak(text) is None, text
        assert PREAMBLE not in text


async def test_persistent_leaks_are_scrubbed_not_shipped(paper, full, always_leaks):
    """Even when every attempt leaks, no preamble reaches the reader."""
    deep = await run_deep_dive(paper, full, on_progress=lambda _: None)
    for text in texts(deep):
        assert PREAMBLE not in text, text
    # The real sentence that followed the preamble survives.
    assert REAL in deep.critique.not_solved


async def test_the_read_still_completes_rather_than_raising(paper, full, always_leaks):
    """A deep dive costs minutes; the critique is its last stage. Failing the
    whole job over a cosmetic defect would be the worse outcome."""
    deep = await run_deep_dive(paper, full, on_progress=lambda _: None)
    assert deep.paper_id == "quant-ph/1511.04206"
    assert deep.sections and deep.glossary and deep.critique


async def test_every_stage_is_guarded(paper, full, always_leaks):
    """If a new stage is added without **_NO_META, this catches it: an
    unguarded schema is called once, a guarded one retries on a leak."""
    calls = always_leaks
    await run_deep_dive(paper, full, on_progress=lambda _: None)
    for schema in {SectionDigestOut, SynthesisOut, ExplanationsOut, GlossaryOut, CritiqueOut}:
        assert calls.count(schema) == 2, f"{schema.__name__} is missing the leak guard"


async def test_partial_reveal_emits_clean_content(paper, full, always_leaks):
    """Progressive reveal shows each stage the moment it lands, so the partial
    payload must be scrubbed too — not just the final object."""
    partials: dict = {}
    await run_deep_dive(
        paper, full, on_progress=lambda _: None,
        on_partial=lambda key, value: partials.__setitem__(key, value),
    )
    assert PREAMBLE not in str(partials["critique"])
    assert PREAMBLE not in str(partials["synthesis"])
    assert PREAMBLE not in str(partials["sections"])
