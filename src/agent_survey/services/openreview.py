"""OpenReview API client — fetch abstracts by title search."""
from __future__ import annotations

import re
import time
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


def search_title_pdf(client: httpx.Client, title: str) -> dict | None:
    """Search OpenReview by title, return PDF URL on fuzzy match.

    Returns dict with keys: pdf_url, forum_id, title  (or None if not found).
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
        data = curl_get_json(f"{OR_API}/notes/search", params=params)

    if not data:
        return None

    notes = data.get("notes") or []
    best_match = None
    best_score = 0.0

    for note in notes:
        content = note.get("content") or {}
        note_title = _get_field(content, "title") or ""
        score = _similarity(note_title, title)
        if score > best_score:
            best_score = score
            forum = note.get("forum", "")
            if forum:
                best_match = {
                    "pdf_url": f"https://openreview.net/pdf?id={forum}",
                    "forum_id": forum,
                    "title": note_title.strip(),
                }

    return best_match if best_score >= 0.75 else None


def _extract_from_html(html: str) -> str | None:
    """Extract abstract from OpenReview forum page HTML."""
    # og:description usually contains the full abstract
    m = re.search(
        r'<meta[^>]*property=["\']og:description["\'][^>]*content=["\']([^"\'>]+)',
        html, re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r'<meta[^>]*name=["\']description["\'][^>]*content=["\']([^"\'>]+)',
            html, re.IGNORECASE,
        )
    if m:
        text = m.group(1).strip()
        if len(text) >= 30:
            return text
    return None


def fetch_forum_abstract(client: httpx.Client, forum_id: str) -> dict | None:
    """Fetch abstract directly by OpenReview forum ID.

    Tries API first, falls back to HTML meta scraping if API returns empty.
    Returns dict with keys: abstract, url, title  (or None if not found).
    """
    if not forum_id:
        return None

    # 1. Try API
    try:
        r = client.get(
            f"{OR_API}/notes",
            params={"id": forum_id},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        notes = data.get("notes") or []
        if notes:
            note = notes[0]
            content = note.get("content") or {}
            note_title = _get_field(content, "title") or ""
            note_abstract = _get_field(content, "abstract") or ""
            if note_abstract:
                return {
                    "title": note_title.strip(),
                    "abstract": note_abstract.strip(),
                    "url": f"https://openreview.net/forum?id={forum_id}",
                }
    except Exception:
        pass

    # 2. Fallback: scrape forum page HTML
    try:
        r = client.get(
            f"https://openreview.net/forum?id={forum_id}",
            timeout=30,
            follow_redirects=True,
        )
        if r.status_code == 200:
            abstract = _extract_from_html(r.text)
            if abstract:
                return {
                    "title": "",
                    "abstract": abstract,
                    "url": f"https://openreview.net/forum?id={forum_id}",
                }
    except Exception:
        pass

    return None


def fetch_batch_forum_abstracts(
    forum_ids: list[str],
    client: httpx.Client | None = None,
    delay: float = 1.0,
) -> dict[str, dict]:
    """Fetch abstracts for multiple forum IDs with rate limiting.

    Returns mapping forum_id -> result dict.
    """
    if client is None:
        client = httpx.Client(timeout=30)
    results: dict[str, dict] = {}
    for fid in forum_ids:
        res = fetch_forum_abstract(client, fid)
        if res:
            results[fid] = res
        time.sleep(delay)
    return results
