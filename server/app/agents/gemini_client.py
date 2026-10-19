"""Gemini wrapper (architecture.md §4): 20 s timeout, max 2 retries, 10-min cache.

A 429 (free-tier quota) raises GeminiUnavailable immediately so callers use
their fallback instead of retrying into the limit. Only weather/zone data is
ever sent (NFR-05).
"""

import hashlib
import json
import logging
import time
from functools import lru_cache

from ..config import check_fault, get_settings
from .. import repo

log = logging.getLogger("huda")

TIMEOUT_MS = 20_000
RETRIES = 2
CACHE_TTL_S = 600
_cache: dict[str, tuple[float, object]] = {}


class GeminiUnavailable(RuntimeError):
    pass


@lru_cache
def _client():
    from google import genai

    key = get_settings().gemini_api_key
    if not key:
        raise GeminiUnavailable("GEMINI_API_KEY is not set")
    return genai.Client(api_key=key)


def _types():
    from google.genai import types

    return types


def _key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def generate(contents, *, system: str, model: str | None = None, json_schema: dict | None = None,
             tools: list | None = None, agent: str = "agent", cache: bool = True):
    """One generate_content call with timeout, retries, cache and logging. Returns the response."""
    check_fault("gemini")
    types = _types()
    model = model or get_settings().gemini_model
    key = _key(model, system, contents if isinstance(contents, str) else repr(contents), json_schema, repr(tools))
    if cache and key in _cache and time.monotonic() - _cache[key][0] < CACHE_TTL_S:
        return _cache[key][1]

    config = types.GenerateContentConfig(
        system_instruction=system,
        http_options=types.HttpOptions(timeout=TIMEOUT_MS),
        temperature=0.3,
    )
    if json_schema:
        config.response_mime_type = "application/json"
        config.response_json_schema = json_schema
    if tools:
        config.tools = tools
        config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)

    from google.genai import errors

    started, last_exc = time.monotonic(), None
    for attempt in range(RETRIES + 1):
        try:
            response = _client().models.generate_content(model=model, contents=contents, config=config)
            repo.log_event("agent", f"{agent}: gemini ok", meta={
                "model": model, "latency_ms": int((time.monotonic() - started) * 1000), "attempt": attempt})
            if cache:
                _cache[key] = (time.monotonic(), response)
            return response
        except errors.APIError as exc:
            last_exc = exc
            if getattr(exc, "code", None) == 429:
                repo.log_event("agent", f"{agent}: gemini rate limited", "warn", meta={"model": model})
                raise GeminiUnavailable("Gemini quota exceeded") from exc
            if getattr(exc, "code", 500) < 500:
                break
        except Exception as exc:  # timeouts, network
            last_exc = exc
        time.sleep(1.5 * (attempt + 1))
    repo.log_event("agent", f"{agent}: gemini failed: {last_exc}", "error", meta={"model": model})
    raise GeminiUnavailable(str(last_exc))


def generate_json(prompt: str, *, system: str, schema: dict, model: str | None = None, agent: str = "agent"):
    response = generate(prompt, system=system, model=model, json_schema=schema, agent=agent)
    try:
        return json.loads(response.text)
    except (TypeError, ValueError) as exc:
        raise GeminiUnavailable(f"invalid JSON from model: {exc}") from exc
