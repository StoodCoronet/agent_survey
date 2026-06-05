"""Crossref API fallback for papers with DOIs.

Crossref provides abstracts (often in JATS XML) for many publisher DOIs,
especially ACM, IEEE, Springer, Wiley, etc.  This is a *general* fallback
that can be used for any venue as long as the paper has a DOI URL.

Rate limit: Crossref asks for polite pool usage (include email in UA).
"""
from __future__ import annotations

import re

import httpx

# Strip common JATS / HTML tags that Crossref returns in abstracts
_JATS_TAG_RE = re.compile(r"<[^>]+>")


def fetch_crossref_abstract(http: httpx.Client, doi: str) -> str | None:
    """Query Crossref works API for an abstract by DOI.

    Args:
        http: shared httpx client
        doi: raw DOI (e.g. ``10.1145/3517036``)

    Returns:
        Clean abstract text, or *None* if not available / too short.
    """
    if not doi:
        return None

    url = f"https://api.crossref.org/works/{doi}"
    try:
        resp = http.get(url, timeout=15)
        resp.raise_for_status()
    except Exception:
        return None

    data = resp.json().get("message", {})
    abstract = data.get("abstract", "")
    if not abstract:
        return None

    # Crossref often wraps abstracts in <jats:p> tags; strip them.
    clean = _JATS_TAG_RE.sub("", abstract)
    clean = clean.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    clean = clean.strip()

    if len(clean) >= 30:
        return clean
    return None
