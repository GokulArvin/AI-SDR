"""Thin wrapper around the Gemini API for getting structured (JSON) output.

Gemini is told to respond as `application/json` and given the exact JSON Schema we
want back via `response_json_schema` -- the model is constrained to emit only text
matching that schema, so there's no "model wrapped the JSON in a markdown fence"
parsing failure to guard against.

Runs on Gemini's free tier (Google AI Studio, no credit card needed).
"""

import json
from typing import Any

from google import genai
from google.genai import types

from app.config import get_settings

_client: genai.Client | None = None

MODEL = "gemini-3.1-flash-lite"  # free tier: 10 req/min, 250 req/day -- plenty for a demo.
# Switched from gemini-3.6-flash (2026-09-29): that model and gemini-3.8-flash were both
# returning consistent 503 "high demand" errors from Google, while this one responded
# reliably to the same structured-output call pattern -- see explanations.md for the
# verification. Revisit if Google's availability changes.


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=get_settings().gemini_api_key)
    return _client


def call_structured(
    *,
    system: str,
    user: str,
    input_schema: dict[str, Any],
    max_tokens: int = 1500,
) -> dict[str, Any]:
    """Call Gemini and force its response to match `input_schema`, returning the
    parsed JSON as a dict."""

    response = get_client().models.generate_content(
        model=MODEL,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_json_schema=input_schema,
            max_output_tokens=max_tokens,
            # Flash's default "dynamic thinking" can burn the whole max_output_tokens
            # budget on invisible reasoning tokens and return truncated JSON. These are
            # short extraction/scoring/drafting calls that don't need it.
            thinking_config=types.ThinkingConfig(thinking_budget=1),
        ),
    )
    return json.loads(response.text)
