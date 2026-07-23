"""LLM provider layer: OpenRouter, Ollama, or the Anthropic API.

All three return schema-validated pydantic instances:
  - openrouter → hosted models, `response_format: json_schema` (+ repair retry)
  - ollama     → local models, grammar-constrained decoding (`format`)
  - anthropic  → structured outputs (`messages.parse`)

The active engine is switchable at runtime (see ENGINES / set_engine) so the UI
can flip between the hosted and local model without restarting the backend; the
env vars below only supply the defaults.

Embeddings for chat-with-paper always run locally through Ollama — OpenRouter
is a chat-completions gateway and does not serve the embedding model.
"""

from __future__ import annotations

import json
import os
from typing import Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

import openrouter

T = TypeVar("T", bound=BaseModel)

OLLAMA_URL = os.getenv("RC_OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("RC_OLLAMA_MODEL", "qwen3:8b")
OLLAMA_CTX = int(os.getenv("RC_OLLAMA_CTX", "16384"))
EMBED_MODEL = os.getenv("RC_EMBED_MODEL", "nomic-embed-text")
# Thinking models (gemma4, qwen3, …) reason into a separate `thinking` field
# and can exhaust num_predict before emitting any constrained JSON content —
# keep it off for pipeline calls unless explicitly enabled.
OLLAMA_THINK = os.getenv("RC_OLLAMA_THINK") == "1"

ANTHROPIC_MODEL = os.getenv("RC_MODEL", "claude-opus-4-8")


class LLMError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Selectable engines
# ---------------------------------------------------------------------------

ENGINES: dict[str, dict] = {
    "nemotron": {
        "id": "nemotron",
        "label": "Nemotron 3 Ultra",
        "provider": "openrouter",
        "model": openrouter.MODEL,
        "blurb": "Hosted · 550B MoE. Deeper analysis and real numbers; ~4 min per paper.",
        "speed": "slower",
    },
    "qwen3": {
        "id": "qwen3",
        "label": "Qwen3 8B",
        "provider": "ollama",
        "model": OLLAMA_MODEL,
        "blurb": "Local · runs offline and free. Faster but shallower; ~90s per paper.",
        "speed": "faster",
    },
    "anthropic": {
        "id": "anthropic",
        "label": "Claude",
        "provider": "anthropic",
        "model": ANTHROPIC_MODEL,
        "blurb": "Anthropic API. Requires ANTHROPIC_API_KEY.",
        "speed": "fast",
    },
}

# Which engine the env vars point at, used as the startup default.
_DEFAULT_ENGINE = next(
    (
        key
        for key, spec in ENGINES.items()
        if spec["provider"] == os.getenv("RC_PROVIDER", "openrouter").strip().lower()
    ),
    "nemotron",
)

_active_engine = _DEFAULT_ENGINE


def active_engine() -> dict:
    return ENGINES[_active_engine]


def set_engine(engine_id: str) -> dict:
    global _active_engine
    if engine_id not in ENGINES:
        raise LLMError(f"Unknown engine '{engine_id}'.")
    _active_engine = engine_id
    return active_engine()


def has_api_key() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

_ollama: httpx.AsyncClient | None = None


def _ollama_client() -> httpx.AsyncClient:
    global _ollama
    if _ollama is None:
        # Local generation on a 12B model can take minutes per call.
        _ollama = httpx.AsyncClient(
            base_url=OLLAMA_URL,
            timeout=httpx.Timeout(900.0, connect=10.0),
        )
    return _ollama


async def _ollama_call(schema: Type[T], system: str, user: str, num_predict: int) -> dict:
    model = active_engine()["model"]
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "think": OLLAMA_THINK,
        "format": schema.model_json_schema(),
        "options": {
            "num_ctx": OLLAMA_CTX,
            "num_predict": num_predict,
            "temperature": 0.2,
            # Small local models can loop under grammar-constrained decoding;
            # a mild penalty breaks repetition without hurting JSON syntax
            # (the grammar forces structural tokens regardless).
            "repeat_penalty": 1.1,
        },
    }
    try:
        response = await _ollama_client().post("/api/chat", json=payload)
    except httpx.ConnectError as e:
        raise LLMError(
            f"Ollama is not reachable at {OLLAMA_URL}. Start the Ollama app (or `ollama serve`)."
        ) from e
    except httpx.TimeoutException as e:
        raise LLMError("Ollama call timed out — the model may be overloaded.") from e

    if response.status_code == 404:
        raise LLMError(
            f"Model '{model}' is not available in Ollama. Run `ollama pull {model}`."
        )
    if response.status_code != 200:
        try:
            detail = response.json().get("error", "")
        except Exception:
            detail = response.text
        raise LLMError(f"Ollama error {response.status_code}: {str(detail)[:300]}")
    return response.json()


def _example_shape(node: dict, defs: dict | None = None, depth: int = 0):
    """Build a placeholder instance from a JSON schema.

    Used in repair prompts so the model sees the exact shape it must produce,
    including the required keys of nested objects — the common failure is
    omitting a required field inside a list of sub-objects.
    """
    defs = defs if defs is not None else node.get("$defs", {})
    if depth > 4:
        return "<...>"

    ref = node.get("$ref")
    if ref:
        return _example_shape(defs.get(ref.rsplit("/", 1)[-1], {}), defs, depth + 1)
    for key in ("anyOf", "allOf", "oneOf"):
        if node.get(key):
            return _example_shape(node[key][0], defs, depth + 1)

    node_type = node.get("type")
    if node_type == "object" or "properties" in node:
        return {
            name: _example_shape(spec, defs, depth + 1)
            for name, spec in (node.get("properties") or {}).items()
        }
    if node_type == "array":
        return [_example_shape(node.get("items") or {}, defs, depth + 1)]
    if node.get("enum"):
        return f"<one of: {', '.join(map(str, node['enum']))}>"
    return f"<{node_type or 'string'}>"


async def _ollama_parse(
    schema: Type[T], system: str, user: str, max_tokens: int
) -> T:
    # Newer/larger local models (e.g. qwen3.5:35b) write noticeably longer
    # responses than the 8B budgets this default was tuned for, and a
    # truncated reply is unparseable rather than merely short — so start with
    # headroom and grow it if the model still runs out of room.
    budget = max(int(max_tokens * 2.5), 2000)
    problem = ""
    for attempt in range(3):
        data = await _ollama_call(schema, system, user, budget)
        if data.get("done_reason") == "length":
            budget = min(budget * 2, 32000)
            continue

        content = data.get("message", {}).get("content", "")
        # Ollama's `format` grammar is not honored by every model — some
        # (observed on qwen3.5:9b) write plain prose regardless. Extract
        # tolerantly the same way the OpenRouter path does before giving up.
        candidate = openrouter.extract_json(content) or content

        # Weaker models produce a predictable set of JSON defects; try the
        # repairs in increasing order of intervention before re-prompting.
        parsed = None
        repaired = openrouter.repair_escapes(candidate)
        for text in (
            candidate,
            repaired,
            openrouter.repair_control_chars(repaired),
        ):
            try:
                parsed = json.loads(text)
                break
            except json.JSONDecodeError as e:
                problem = str(e)[:300]

        if parsed is not None:
            try:
                return schema.model_validate(parsed)
            except ValidationError as e:
                problem = str(e)[:300]

        if attempt < 2:
            # A generic "match the schema" nudge isn't enough — the model
            # needs the field names restated explicitly, since it may invent
            # its own (e.g. `section_title` instead of `summary`) or omit
            # required keys inside nested objects. Show an EXAMPLE shape, not
            # the raw JSON-schema document — dumping the schema itself risks
            # the model parroting its own keys (`title`, `properties`, …)
            # back as if they were the answer.
            example = _example_shape(schema.model_json_schema())
            system = (
                system + "\n\nYour previous reply was not valid JSON for this task "
                f"({problem}). Reply again with ONLY one JSON object shaped exactly "
                "like this example, with real content in place of the placeholders "
                "(do not include this example's placeholder text or explain the "
                "schema — just answer using these field names):\n"
                + json.dumps(example)
            )
            continue
        raise LLMError(f"Model returned invalid structured output: {problem}")
    raise LLMError(
        f"Model output was truncated (num_predict) even after retries with a larger budget ({problem})."
    )


async def embed_texts(texts: list[str], is_query: bool = False) -> list[list[float]]:
    """Embed with Ollama. nomic-embed-text expects task prefixes on each input."""
    if not texts:
        return []
    prefix = "search_query: " if is_query else "search_document: "
    try:
        response = await _ollama_client().post(
            "/api/embed",
            json={"model": EMBED_MODEL, "input": [prefix + t for t in texts]},
        )
    except httpx.ConnectError as e:
        raise LLMError(f"Ollama is not reachable at {OLLAMA_URL}.") from e
    except httpx.TimeoutException as e:
        raise LLMError("Embedding request timed out.") from e

    if response.status_code == 404:
        raise LLMError(
            f"Embedding model '{EMBED_MODEL}' is missing. Run `ollama pull {EMBED_MODEL}`."
        )
    if response.status_code != 200:
        raise LLMError(f"Ollama embedding error {response.status_code}: {response.text[:200]}")
    embeddings = response.json().get("embeddings")
    if not embeddings:
        raise LLMError("Ollama returned no embeddings.")
    return embeddings


async def ollama_status() -> tuple[bool, str | None]:
    """(ready, human-readable problem or None)."""
    try:
        response = await _ollama_client().get("/api/tags")
        response.raise_for_status()
    except Exception:
        return False, (
            f"Ollama is not reachable at {OLLAMA_URL} — start the Ollama app "
            "(or run `ollama serve`)."
        )
    names = [m.get("name", "") for m in response.json().get("models", [])]
    model = active_engine()["model"]
    if model not in names:
        return False, (
            f"Model '{model}' isn't pulled — run `ollama pull {model}` "
            f"(installed: {', '.join(names) if names else 'none'})."
        )
    return True, None


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

_anthropic = None


async def _anthropic_parse(
    schema: Type[T], system: str, user: str, max_tokens: int, thinking: bool
) -> T:
    global _anthropic
    import anthropic

    if _anthropic is None:
        if not has_api_key():
            raise LLMError(
                "ANTHROPIC_API_KEY is not set. Add it to backend/.env and restart the backend."
            )
        _anthropic = anthropic.AsyncAnthropic()

    kwargs: dict = {}
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    try:
        response = await _anthropic.messages.parse(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            **kwargs,
        )
    except anthropic.AuthenticationError as e:
        raise LLMError(f"Anthropic API key was rejected ({e.message}). Check backend/.env.") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Anthropic API rate limit hit; wait a minute and retry.") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Could not reach the Anthropic API (network error).") from e

    if response.stop_reason == "refusal":
        raise LLMError("The model declined this request.")
    if response.stop_reason == "max_tokens":
        raise LLMError("Model output was truncated (max_tokens); try a smaller search.")
    if response.parsed_output is None:
        raise LLMError("Model returned no parseable structured output.")
    return response.parsed_output


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def parse_json(
    schema: Type[T],
    system: str,
    user: str,
    max_tokens: int = 4096,
    thinking: bool = False,
) -> T:
    """One structured-output call; returns a validated instance of `schema`."""
    provider = active_engine()["provider"]
    if provider == "anthropic":
        return await _anthropic_parse(schema, system, user, max_tokens, thinking)
    if provider == "openrouter":
        try:
            return await openrouter.parse_json(schema, system, user, max_tokens)
        except openrouter.OpenRouterError as exc:
            raise LLMError(str(exc)) from exc
    return await _ollama_parse(schema, system, user, max_tokens)


async def embeddings_status() -> tuple[bool, str | None]:
    """Chat-with-paper needs the local embedding model regardless of provider."""
    try:
        response = await _ollama_client().get("/api/tags")
        response.raise_for_status()
    except Exception:
        return False, (
            f"Ollama is not reachable at {OLLAMA_URL}; chat-with-paper needs it for "
            "embeddings. Start the Ollama app (other features work without it)."
        )
    names = [m.get("name", "") for m in response.json().get("models", [])]
    if not any(n.split(":")[0] == EMBED_MODEL.split(":")[0] for n in names if n):
        return False, (
            f"Embedding model '{EMBED_MODEL}' isn't pulled — run "
            f"`ollama pull {EMBED_MODEL}` to enable chat-with-paper."
        )
    return True, None


async def provider_status() -> dict:
    """Health info for the active engine."""
    engine = active_engine()
    provider = engine["provider"]
    if provider == "anthropic":
        ready = has_api_key()
        detail = (
            None if ready else "Add ANTHROPIC_API_KEY to backend/.env and restart the backend."
        )
    elif provider == "openrouter":
        ready, detail = await openrouter.status()
    else:
        ready, detail = await ollama_status()

    status = {
        "engine": engine["id"],
        "provider": provider,
        "model": engine["model"],
        "ready": ready,
        "detail": detail,
    }

    embeddings_ready, embeddings_detail = await embeddings_status()
    status["embeddings_ready"] = embeddings_ready
    status["embeddings_detail"] = embeddings_detail
    return status
