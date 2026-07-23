"""OpenRouter provider — hosted models via an OpenAI-compatible endpoint.

Two things make this materially different from the local Ollama path:

1. **Structured output is a request, not a guarantee.** Ollama compiles the JSON
   schema into a decoding grammar, so invalid JSON is impossible. OpenRouter
   passes `response_format` to whichever upstream provider it routes to, and
   compliance varies. Everything here is therefore defensive: sanitize the
   schema, extract JSON tolerantly, validate with pydantic, and retry once with
   an explicit repair instruction.

2. **The free tier is rate limited** (~20 requests/minute, and 50/day until the
   account has ever held $10 in credit). A sliding-window limiter keeps us under
   the per-minute cap, and 429s are retried with backoff that honours
   `Retry-After`.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

import meta_guard

T = TypeVar("T", bound=BaseModel)

URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = os.getenv("RC_OPENROUTER_MODEL", "nvidia/nemotron-3-ultra-550b-a55b:free")
RPM = int(os.getenv("RC_OPENROUTER_RPM", "18"))          # cap is 20; leave headroom
MAX_RETRIES = int(os.getenv("RC_OPENROUTER_RETRIES", "4"))
TIMEOUT = float(os.getenv("RC_OPENROUTER_TIMEOUT", "300"))
TOKEN_HEADROOM = float(os.getenv("RC_OPENROUTER_TOKEN_HEADROOM", "2.5"))
MIN_TOKENS = int(os.getenv("RC_OPENROUTER_MIN_TOKENS", "2000"))


def api_key() -> str:
    return os.getenv("OPENROUTER_API_KEY", "").strip()


class OpenRouterError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class _SlidingWindow:
    """Allow at most `per_minute` acquisitions in any rolling 60s window."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = max(1, per_minute)
        self._hits: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                while self._hits and now - self._hits[0] >= 60.0:
                    self._hits.popleft()
                if len(self._hits) < self.per_minute:
                    self._hits.append(now)
                    return
                wait = 60.0 - (now - self._hits[0]) + 0.05
            await asyncio.sleep(wait)


_limiter = _SlidingWindow(RPM)
_client: httpx.AsyncClient | None = None


# ---------------------------------------------------------------------------
# Daily usage tracking
# ---------------------------------------------------------------------------
#
# The free tier's per-minute cap is enforced live by `_limiter` above, but a
# 50 or 1000/day cap has no such graceful backpressure — you just get 429s
# for the rest of the day. Tracking usage ourselves lets the UI warn before a
# big search burns the day's budget, rather than the reader finding out mid-run.

# Default assumes the account has funded the one-time $10 that permanently
# raises the cap from 50/day to 1000/day (see module docstring); override if not.
DAILY_CAP = int(os.getenv("RC_OPENROUTER_DAILY_CAP", "1000"))
_USAGE_FILE = Path(__file__).parent / "data" / "openrouter_usage.json"
_usage_lock = asyncio.Lock()


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _load_usage() -> dict[str, Any]:
    try:
        data = json.loads(_USAGE_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    if data.get("date") != _today():
        return {"date": _today(), "count": 0}
    return data


def _save_usage(data: dict[str, Any]) -> None:
    _USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _USAGE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(_USAGE_FILE)


async def _record_call() -> None:
    """One unit per real HTTP attempt — a retried call still spends quota."""
    async with _usage_lock:
        data = _load_usage()
        data["count"] = data.get("count", 0) + 1
        _save_usage(data)


def daily_usage() -> dict[str, Any]:
    """Today's call count against the free-tier daily cap (UTC day boundary)."""
    used = _load_usage().get("count", 0)
    return {
        "used": used,
        "cap": DAILY_CAP,
        "remaining": max(DAILY_CAP - used, 0),
        "near_cap": used >= DAILY_CAP * 0.9,
    }


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, connect=15.0))
    return _client


# ---------------------------------------------------------------------------
# Schema handling
# ---------------------------------------------------------------------------

# Keywords that strict structured-output implementations reject. We drop them
# from the schema but fold their meaning into the field description so the
# model still gets the constraint.
_DROP = ("minItems", "maxItems", "minimum", "maximum", "minLength", "maxLength")


def _describe_bounds(node: dict[str, Any]) -> str:
    low, high = node.get("minItems"), node.get("maxItems")
    if low is not None and high is not None:
        return f" Provide between {low} and {high} items."
    if high is not None:
        return f" Provide at most {high} items."
    if low is not None:
        return f" Provide at least {low} items."
    return ""


def _sanitize(node: Any) -> Any:
    """Make a pydantic JSON schema acceptable to strict structured outputs."""
    if isinstance(node, list):
        return [_sanitize(item) for item in node]
    if not isinstance(node, dict):
        return node

    node = dict(node)
    hint = _describe_bounds(node)
    if hint:
        node["description"] = (node.get("description", "") + hint).strip()
    for key in _DROP:
        node.pop(key, None)

    if node.get("type") == "object" or "properties" in node:
        properties = node.get("properties") or {}
        node["properties"] = {k: _sanitize(v) for k, v in properties.items()}
        # Strict mode wants every property listed as required.
        node["required"] = list(node["properties"].keys())
        node["additionalProperties"] = False

    for key in ("items", "anyOf", "allOf", "oneOf"):
        if key in node:
            node[key] = _sanitize(node[key])

    # $defs / definitions map arbitrary names to schemas, so recurse per value
    # rather than treating the container itself as a schema node.
    for key in ("$defs", "definitions"):
        container = node.get(key)
        if isinstance(container, dict):
            node[key] = {name: _sanitize(value) for name, value in container.items()}

    return node


def build_schema(schema: Type[BaseModel]) -> dict[str, Any]:
    return _sanitize(copy.deepcopy(schema.model_json_schema()))


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)
# Deliberately excludes \b \f \r: those are valid single-char JSON escapes,
# but in model output the same letters almost always start a LaTeX command
# (\beta, \frac, \rho, \rangle, ...) rather than an intentional control
# character — treating them as "already valid" silently corrupts the text
# (e.g. "\beta" parses as backspace + "eta") instead of failing loudly.
_BAD_ESCAPE = re.compile(r'\\(?!["\\/ntu])')


def repair_escapes(text: str) -> str:
    r"""Escape backslashes that aren't valid JSON escapes.

    Models asked for math or LaTeX-flavored text (`\alpha`, `\beta`, `\%`)
    routinely emit it raw inside a JSON string, which is invalid JSON — `\a`
    is not a recognized escape. Doubling any backslash not already part of a
    conservatively-valid escape sequence fixes this without touching `\n`,
    `\"`, `\\`, `\uXXXX`.
    """
    return _BAD_ESCAPE.sub(r"\\\\", text)


def repair_control_chars(text: str) -> str:
    """Escape raw newlines/tabs that appear *inside* JSON string values.

    Weaker models often pretty-print prose across real line breaks inside a
    string, which json.loads rejects as an invalid control character. Walk the
    text tracking string state so only in-string control characters are
    escaped and the surrounding JSON formatting is left intact.
    """
    out: list[str] = []
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            if char == "\n":
                out.append("\\n")
                continue
            if char == "\r":
                out.append("\\r")
                continue
            if char == "\t":
                out.append("\\t")
                continue
        elif char == '"':
            in_string = True
        out.append(char)
    return "".join(out)


# Reasoning-tuned models sometimes leak their opening chain-of-thought
# ("The user wants me to write a peer review..." / "I need to act as...") into
# a string field of an otherwise well-formed structured response, instead of
# answering it. This is valid JSON that passes schema validation, so it has to
# be caught separately from JSON/schema errors.
#
# The patterns live in meta_guard because the same failure appears on Ollama's
# reasoning models too — one list, checked here inside the provider's own
# repair loop (cheap, it reuses the existing retry conversation) and again at
# the llm.parse_json layer, which is what catches it for the other providers.
def _leaked_instruction(parsed: BaseModel) -> str | None:
    return meta_guard.find_leak_in(parsed)


def extract_json(text: str) -> str | None:
    """Pull a JSON object out of a possibly chatty / fenced response."""
    if not text:
        return None
    text = text.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    if text.startswith("{") and text.endswith("}"):
        return text
    # Fall back to the first balanced {...} span.
    start = text.find("{")
    if start == -1:
        return None
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

async def _post(payload: dict[str, Any]) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise OpenRouterError(
            "OPENROUTER_API_KEY is not set. Add it to backend/.env and restart the backend."
        )
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        # Optional attribution headers OpenRouter uses for its rankings.
        "HTTP-Referer": "http://localhost:3000",
        "X-Title": "Research Copilot",
    }

    last_error = "unknown error"
    for attempt in range(MAX_RETRIES):
        await _limiter.acquire()
        await _record_call()
        try:
            response = await _http().post(URL, json=payload, headers=headers)
        except httpx.TimeoutException:
            last_error = "request timed out"
            await asyncio.sleep(2 ** attempt)
            continue
        except httpx.HTTPError as exc:
            last_error = f"network error: {exc}"
            await asyncio.sleep(2 ** attempt)
            continue

        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                last_error = "malformed JSON envelope"
                await asyncio.sleep(2 ** attempt)
                continue
            # OpenRouter can return HTTP 200 with an error envelope, or with an
            # empty `choices` array when the upstream provider hiccups. Both are
            # transient, so retry rather than failing the whole pipeline stage.
            envelope_error = data.get("error")
            if envelope_error:
                message = (
                    envelope_error.get("message")
                    if isinstance(envelope_error, dict)
                    else str(envelope_error)
                )
                code = (
                    envelope_error.get("code") if isinstance(envelope_error, dict) else None
                )
                if code in (401, 402, 403):
                    raise OpenRouterError(f"OpenRouter error {code}: {message}")
                last_error = f"upstream error: {message}"
                await asyncio.sleep(2 ** attempt * 2)
                continue
            if not data.get("choices"):
                last_error = "provider returned no choices"
                await asyncio.sleep(2 ** attempt * 2)
                continue
            return data

        if response.status_code == 401:
            raise OpenRouterError("OpenRouter rejected the API key (401). Check backend/.env.")
        if response.status_code == 402:
            raise OpenRouterError(
                "OpenRouter says this request needs credit (402) — the free daily quota "
                "may be exhausted, or the model requires a paid balance."
            )
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            delay = float(retry_after) if (retry_after or "").replace(".", "", 1).isdigit() else 2 ** attempt * 5
            last_error = "rate limited (429)"
            await asyncio.sleep(min(delay, 60.0))
            continue
        if response.status_code >= 500:
            last_error = f"upstream error {response.status_code}"
            await asyncio.sleep(2 ** attempt * 2)
            continue

        # 4xx that won't fix itself.
        detail = response.text[:300]
        raise OpenRouterError(f"OpenRouter error {response.status_code}: {detail}")

    raise OpenRouterError(f"OpenRouter request failed after {MAX_RETRIES} attempts: {last_error}")


def _content_of(data: dict[str, Any]) -> tuple[str, str]:
    """Returns (content, finish_reason). `_post` guarantees a choices array."""
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):      # some providers return content parts
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return content or "", choice.get("finish_reason") or ""


async def parse_json(
    schema: Type[T],
    system: str,
    user: str,
    max_tokens: int = 4096,
    include_reasoning: bool = False,
) -> T:
    """One structured call, validated into `schema`, with a single repair retry."""
    json_schema = build_schema(schema)
    # Hosted reasoning models are markedly more verbose than the local models
    # these budgets were tuned for, and a truncated reply is unparseable rather
    # than merely short — so give generous headroom from the start.
    budget = max(int(max_tokens * TOKEN_HEADROOM), MIN_TOKENS)
    payload: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": budget,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": schema.__name__.lower(),
                "strict": True,
                "schema": json_schema,
            },
        },
    }
    if not include_reasoning:
        # Keep reasoning traces out of the billed/streamed payload where the
        # provider supports it; harmless when ignored.
        payload["reasoning"] = {"exclude": True}

    raw = ""
    problem = ""
    leaked_parse: T | None = None
    for attempt in range(3):
        try:
            data = await _post(payload)
        except OpenRouterError as exc:
            # A provider that rejects our schema shape is worth one plain retry
            # in JSON-object mode before giving up.
            if attempt == 0 and "response_format" in str(exc).lower():
                payload["response_format"] = {"type": "json_object"}
                payload["messages"][0]["content"] = (
                    system + "\n\nRespond with a single JSON object matching this schema:\n"
                    + json.dumps(json_schema)
                )
                continue
            raise

        raw, finish_reason = _content_of(data)

        if finish_reason == "length":
            # Truncated mid-JSON. Retrying with the same budget would truncate
            # again, so grow it and ask for brevity instead of repairing.
            payload["max_tokens"] = min(int(payload["max_tokens"] * 2), 32000)
            payload["messages"] = payload["messages"][:2]
            payload["messages"][0] = {
                "role": "system",
                "content": system + "\n\nBe concise: keep every field short and do not "
                "exceed a few sentences per field.",
            }
            problem = "the reply was cut off (max_tokens)"
            continue

        candidate = extract_json(raw)
        if candidate:
            try:
                parsed = schema.model_validate(json.loads(candidate))
            except (json.JSONDecodeError, ValidationError) as exc:
                problem = str(exc)[:400]
            else:
                leak = _leaked_instruction(parsed)
                if leak:
                    problem = f"response echoed system-prompt/task framing instead of answering it (starts: {leak!r})"
                    # Schema-valid, just contaminated. Hold on to it: if every
                    # attempt leaks, returning this beats raising, because the
                    # llm.parse_json guard can strip the preamble and keep
                    # whatever real content followed it.
                    leaked_parse = parsed
                else:
                    return parsed
        else:
            problem = "no JSON object found in the response"

        payload["messages"] = payload["messages"][:2] + [
            {"role": "assistant", "content": raw[:2000]},
            {
                "role": "user",
                "content": (
                    "That response was not valid for the required schema "
                    f"({problem}). Reply again with ONLY a single JSON object "
                    "that matches the schema exactly — no prose, no code fences."
                ),
            },
        ]

    if leaked_parse is not None:
        # Every attempt leaked, but the last one was still schema-valid.
        # Degrade instead of raising: the caller's guard strips the preamble,
        # and losing a whole multi-minute deep dive over a contaminated field
        # is the worse outcome. A field with nothing left after scrubbing is
        # labelled rather than shown (see meta_guard.UNAVAILABLE).
        return leaked_parse

    raise OpenRouterError(
        f"Model did not return valid structured output after 3 attempts ({problem}). "
        f"Last reply began: {raw[:200]!r}"
    )


async def status() -> tuple[bool, str | None]:
    if not api_key():
        return False, (
            "OPENROUTER_API_KEY is not set. Add it to backend/.env "
            "(get a key at openrouter.ai/keys) and restart the backend."
        )
    try:
        response = await _http().get(
            "https://openrouter.ai/api/v1/auth/key",
            headers={"Authorization": f"Bearer {api_key()}"},
        )
    except httpx.HTTPError:
        return False, "Could not reach OpenRouter (network error)."
    if response.status_code == 401:
        return False, "OpenRouter rejected the API key. Check backend/.env."
    if response.status_code != 200:
        # The key endpoint is informational; don't block usage on it.
        return True, None
    return True, None
