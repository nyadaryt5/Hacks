"""Tolerant JSON parsing for LLM output.

LLMs frequently wrap JSON in markdown fences, prose or code blocks.
:func:`parse_json_response` recovers the first parseable object or returns
``None`` for empty / error responses.
"""

from __future__ import annotations

import json
from typing import Any


def parse_json_response(response: str) -> Any | None:
    """Parse JSON out of an LLM response, tolerating common wrapping."""
    if not response or response.startswith("[ERROR]") or response.startswith(
        "[BUDGET]"
    ):
        return None
    try:
        return json.loads(response.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    if "```json" in response:
        try:
            code = response.split("```json")[1].split("```", maxsplit=1)[0].strip()
            return json.loads(code)
        except (json.JSONDecodeError, ValueError, IndexError):
            pass
    if "```" in response:
        parts = response.split("```")
        for i in range(1, len(parts), 2):
            try:
                return json.loads(parts[i].strip())
            except (json.JSONDecodeError, ValueError):
                continue
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(response[start:end])
    except (json.JSONDecodeError, ValueError):
        pass
    return None


__all__ = ["parse_json_response"]
