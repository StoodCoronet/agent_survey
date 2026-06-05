"""Response parsers for classification stage."""
from __future__ import annotations

import json
import re


def _strip_markdown_fences(raw: str) -> str:
    """Remove markdown code fences and optional 'json' label.

    Handles both leading fences and fences embedded in explanatory text.
    """
    raw = raw.strip()
    if raw.startswith("```"):
        # Remove opening fence (possibly with language tag)
        raw = re.sub(r"^```[\w]*\n?", "", raw, count=1)
        # Remove closing fence
        raw = re.sub(r"\n?```\s*$", "", raw, count=1)
        return raw.strip()
    # Sometimes the model wraps JSON inside a markdown block in the middle of text.
    # Extract the first ```...``` block.
    m = re.search(r"```(?:json)?\n?(.*?)\n?```", raw, re.DOTALL)
    if m:
        return m.group(1).strip()
    return raw


def _extract_json_prefix(text: str) -> object | None:
    """Try to parse the first well-formed JSON object or array from text."""
    # Try array first
    start = text.find("[")
    if start >= 0:
        for end in range(start + 1, len(text) + 1):
            try:
                candidate = text[start:end]
                # Quick heuristic: must end with ] and be valid JSON
                if candidate.rstrip().endswith("]"):
                    return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    # Try object
    start = text.find("{")
    if start >= 0:
        for end in range(start + 1, len(text) + 1):
            try:
                candidate = text[start:end]
                if candidate.rstrip().endswith("}"):
                    return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    return None


def normalize_result(item: dict) -> dict:
    """Normalize LLM result keys to the canonical schema.

    Maps common variant keys to the expected canonical keys:
    - domain -> domain_primary
    - method / methods -> method_tags
    - notes / reasoning / comment -> rationale
    - summary / description -> tldr
    """
    out = dict(item)
    # Map domain -> domain_primary
    if "domain_primary" not in out and "domain" in out:
        out["domain_primary"] = out.pop("domain")
    # Map method/methods -> method_tags
    if "method_tags" not in out:
        for k in ("method", "methods"):
            if k in out:
                v = out.pop(k)
                out["method_tags"] = v if isinstance(v, list) else [v] if v else []
                break
    # Map notes/reasoning/comment -> rationale
    if "rationale" not in out:
        for k in ("reasoning", "notes", "comment", "justification"):
            if k in out:
                out["rationale"] = out.pop(k)
                break
    # Map summary/description -> tldr
    if "tldr" not in out:
        for k in ("summary", "description", "abstract_summary"):
            if k in out:
                out["tldr"] = out.pop(k)
                break
    return out


def parse_batch_result(raw: str, expected_len: int) -> list[dict]:
    """Parse batch classification result from LLM response.

    Tries progressively more permissive strategies:
    1. Strip markdown fences and parse top-level JSON.
    2. If top-level is a list, return it.
    3. If top-level is a dict, look for common list keys.
    4. If nothing found, try to extract the first JSON array/object from raw text.
    5. Normalize keys in each item.
    6. If still nothing, raise ValueError with a snippet of the raw text.
    """
    cleaned = _strip_markdown_fences(raw)

    data = _extract_json_prefix(cleaned)
    if data is None:
        # Last resort: try the raw string directly
        data = _extract_json_prefix(raw)

    if data is None:
        raise ValueError(
            f"Could not parse batch result: expected {expected_len} items. "
            f"Raw snippet: {raw[:400]!r}"
        )

    results: list[dict] = []

    if isinstance(data, list):
        results = data
    elif isinstance(data, dict):
        for key in ("results", "papers", "data", "items", "result", "output", "classifications", "response"):
            if key in data and isinstance(data[key], list):
                results = data[key]
                break
        if not results:
            # Some models return a dict where values are the results (e.g. {"0": {...}, "1": {...}})
            dict_values = [v for v in data.values() if isinstance(v, dict)]
            if len(dict_values) == expected_len:
                results = dict_values

    if not results:
        raise ValueError(
            f"Could not parse batch result: expected {expected_len} items. "
            f"Parsed type={type(data).__name__!r} snippet: {raw[:400]!r}"
        )

    return [normalize_result(item) for item in results if isinstance(item, dict)]
