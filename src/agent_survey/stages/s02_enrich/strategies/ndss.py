"""NDSS abstract fetcher.

NDSS symposium pages are WordPress posts where the abstract lives in
<article class="... post ..."> as a sequence of <p> tags.  The first <p>
is the author list; subsequent paragraphs form the abstract.
"""
from __future__ import annotations

import re

import httpx


def fetch_ndss_abstract(url: str, timeout: float = 15.0) -> str | None:
    """Fetch abstract from an ndss-symposium.org paper page."""
    try:
        r = httpx.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; agent-survey/0.1)"},
            follow_redirects=True,
        )
        if r.status_code != 200:
            return None
    except Exception:
        return None

    html = r.text
    # Isolate the WordPress post content inside <article>
    article_m = re.search(
        r'<article[^>]*class="[^"]*post[^"]*"[^>]*>(.*?)</article>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not article_m:
        return None

    paragraphs = re.findall(r"<p>(.*?)</p>", article_m.group(1), re.DOTALL | re.IGNORECASE)
    if len(paragraphs) < 2:
        return None

    # Skip first paragraph (author list), keep the rest
    texts: list[str] = []
    for p in paragraphs[1:]:
        text = re.sub(r"<[^>]+>", "", p).strip()
        if text:
            texts.append(text)

    abstract = " ".join(texts)
    return abstract if len(abstract) >= 30 else None
