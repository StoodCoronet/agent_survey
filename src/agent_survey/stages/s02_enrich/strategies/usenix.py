"""USENIX Security (USS) abstract fetcher.

USENIX presentation pages host their own abstracts in a Drupal field:
  <div class="field field-name-field-paper-description ...">...<p>abstract</p></div>
"""
from __future__ import annotations

import re

import httpx


def fetch_usenix_abstract(url: str, timeout: float = 15.0) -> str | None:
    """Fetch abstract from a usenix.org presentation page."""
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
    # Greedy match of the description field down to its first <p>
    m = re.search(
        r'<div class="field field-name-field-paper-description[^"]*"[^>]*>.*?'
        r'<div class="field-items[^"]*"><div class="field-item[^"]*"><p>(.*?)</p>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None

    text = m.group(1)
    text = re.sub(r"<[^>]+>", "", text)  # strip any inline tags
    text = text.strip()
    return text if len(text) >= 30 else None
