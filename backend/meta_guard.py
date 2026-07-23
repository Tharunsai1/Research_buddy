"""Catch model meta-commentary before it reaches the reader.

Reasoning models restate the task to themselves before answering ("The user
wants me to write a peer review of this paper..."). That preamble normally
stays in the hidden reasoning channel, but it occasionally lands in the
structured output instead of the answer — observed on the critique stage for
quant-ph/1511.04206, where the whole card was the model narrating its own
instructions back at the reader.

A prompt cannot prevent this on its own: telling a model "do not restate the
task" is a request, not a guarantee, and the deep-dive prompts already carried
a similar rule when this leaked. So the output is also checked in code —
`find_leak` reports the offending phrase so the caller can retry, and `scrub`
strips the preamble when a retry still comes back dirty. Failing the whole
read is not an option; a deep dive costs minutes and the critique is its last
stage.
"""

from __future__ import annotations

import re
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Models emit either an ASCII apostrophe or a typographic one, sometimes both
# in the same reply, so every contraction below accepts either.
_AP = r"['’]"

# Phrases that are meta wherever they appear. A peer reviewer writing about a
# paper's evidence has no reason to reach for any of these, so matching them
# anywhere in the text is safe.
_ANYWHERE = [
    r"\bthe user (?:wants|is asking|asked|has asked|would like)",
    r"\bmy task is\b",
    rf"\bi (?:am|{_AP}m|was) asked to\b",
    rf"\bi(?:{_AP}ve| have) been asked\b",
    r"\bi (?:should|need to|must|will) (?:write|focus|provide|produce|generate)\b",
    r"\bas an ai\b",
    r"\bas a language model\b",
    # Deliberately narrow: "the prompt" and "the digest" are ordinary
    # vocabulary in LLM and hashing papers respectively, so only the
    # unmistakably self-referential forms are matched.
    r"\bthe system prompt\b",
    r"\bper the instructions\b",
    r"\bthe provided (?:text|digest|digests|summary|synthesis|content)\b",
    r"\bthe section digests?\b",
    r"\bbased on the provided\b",
    r"\bthe summary provided\b",
    r"\blet me (?:analy[sz]e|start|begin|write|think|first)\b",
    rf"\bhere(?:{_AP}s| is) my (?:peer )?(?:review|critique|analysis)\b",
    rf"\bhere(?:{_AP}s| is) the (?:peer )?(?:review|critique|analysis)\b",
]

# Conversational scaffolding that is only meta at the very start of a field.
# Mid-sentence these words are ordinary English, so they are anchored.
_PREFIX = [
    r"okay[,\s]",
    r"ok[,\s]",
    r"alright[,\s]",
    r"sure[,\s]",
    r"certainly[,\s]",
    r"first[,\s]+i\b",
    rf"i{_AP}ll\b",
    r"i will\b",
]

_ANYWHERE_RE = re.compile("|".join(_ANYWHERE), re.IGNORECASE)
_PREFIX_RE = re.compile(r"^\s*(?:" + "|".join(_PREFIX) + ")", re.IGNORECASE)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def find_leak(text: str) -> str | None:
    """Return the offending phrase if `text` reads as meta-commentary."""
    if not text or not text.strip():
        return None
    match = _ANYWHERE_RE.search(text)
    if match:
        return match.group(0).strip()
    match = _PREFIX_RE.match(text)
    if match:
        return match.group(0).strip()
    return None


def _strings(model: BaseModel):
    """Yield every string this model carries, one level of nesting deep."""
    for value in model.__dict__.values():
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield item
                elif isinstance(item, BaseModel):
                    yield from _strings(item)
        elif isinstance(value, BaseModel):
            yield from _strings(value)


def find_leak_in(model: BaseModel) -> str | None:
    """Guard for `llm.parse_json` — first leak found across the model's text."""
    for text in _strings(model):
        leak = find_leak(text)
        if leak:
            return leak
    return None


def strip_meta(text: str) -> str:
    """Drop leading meta sentences, keeping the real answer that follows.

    Only *leading* sentences are removed: the preamble sits at the front, and
    a later sentence that trips a pattern is more likely a false positive than
    a genuine leak worth deleting.
    """
    if not text or not text.strip():
        return text
    sentences = _SENTENCE_SPLIT.split(text.strip())
    kept = list(sentences)
    while kept and find_leak(kept[0]) is not None:
        kept.pop(0)
    return " ".join(kept).strip()


UNAVAILABLE = "(Not generated cleanly — rerun the deep dive to retry this section.)"


def _scrub_text(text: str) -> str:
    kept = strip_meta(text)
    if kept:
        return kept
    # Nothing survived, so the field was meta-commentary end to end. Say that
    # plainly instead of handing back the model's monologue dressed as
    # content — presenting it as a critique is the bug this module exists for.
    return UNAVAILABLE if find_leak(text) else text


def scrub(value: T) -> T:
    """Copy of `value` with meta-commentary stripped from its text.

    The last resort when a retry also leaks. Partially-leaked text keeps
    whatever real content followed the preamble; text that is meta all the way
    through is replaced with `UNAVAILABLE`, never passed through.
    """
    data = {}
    for name, field in value.__dict__.items():
        if isinstance(field, str):
            data[name] = _scrub_text(field)
        elif isinstance(field, list):
            cleaned = []
            for item in field:
                if isinstance(item, str):
                    kept = strip_meta(item)
                    if kept:
                        cleaned.append(kept)
                elif isinstance(item, BaseModel):
                    cleaned.append(scrub(item))
                else:
                    cleaned.append(item)
            # An originally-empty list stays empty; one emptied by scrubbing
            # is reported, so a silently-vanished list is never mistaken for
            # the model having nothing to say.
            data[name] = cleaned if cleaned or not field else [UNAVAILABLE]
        elif isinstance(field, BaseModel):
            data[name] = scrub(field)
        else:
            data[name] = field
    return value.__class__(**data)


RETRY_INSTRUCTION = (
    "Your previous reply leaked meta-commentary about the task itself "
    '(it contained "{leak}"). Do not restate, describe, or refer to these '
    "instructions, the request, yourself, or the source material you were "
    "given. Write only the finished content, as if published — start "
    "directly with the substance."
)
