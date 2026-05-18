"""OpenReview API client — fetch abstracts by title search."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ._curl_fallback import curl_get_json

OR_API = "https://api.openreview.net"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _get_field(content: dict, key: str) -> str | None:
    """Handle both API v1 (string) and v2 ({value: ...}) content formats."""
    v = content.get(key)
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("value")
    if isinstance(v, str):
        return v
    return None


def search_title(client: httpx.Client, title: str) -> dict | None:
    """Search OpenReview by title, return abstract + forum URL on fuzzy match.

    Returns dict with keys: abstract, url  (or None if not found / no abstract).
    """
    if not title or len(title) < 5:
        return None
    params = {"term": title, "limit": 10}
    data: dict | None = None
    try:
        r = client.get(
            f"{OR_API}/notes/search",
            params=params,
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        # macOS Anaconda OpenSSL 3.0 TLS handshake failure — fallback to curl
        data = curl_get_json(f"{OR_API}/notes/search", params=params)

    if not data:
        return None

    notes = data.get("notes") or []
    best_match = None
    best_score = 0.0

    for note in notes:
        content = note.get("content") or {}
        note_title = _get_field(content, "title") or ""
        note_abstract = _get_field(content, "abstract") or ""

        if not note_abstract:
            continue

        score = _similarity(note_title, title)
        if score > best_score:
            best_score = score
            forum = note.get("forum", "")
            best_match = {
                "abstract": note_abstract.strip(),
                "url": f"https://openreview.net/forum?id={forum}" if forum else None,
            }

    # accept match if similarity >= 0.75 (fairly generous)
    return best_match if best_score >= 0.75 else None
