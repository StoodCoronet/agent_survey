"""Fetch abstracts from publisher websites by URL or DOI.

Covers the most common academic publishers found in DBLP `ee` links.
ACM Digital Library often returns 403 for uncredentialed requests;
it is attempted but expected to fall back to S2 enrichment later.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import httpx

# ------------------------------------------------------------------
# Per-domain extractors
# ------------------------------------------------------------------

def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    # Unescape common HTML entities
    text = text.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    if len(text) < 30:
        return None
    return text


def _extract_meta(html: str, **attrs: str) -> str | None:
    """Extract content from a <meta> tag matching **attrs."""
    # Build a regex that matches all given attributes in any order
    attr_patterns = []
    for k, v in attrs.items():
        attr_patterns.append(rf'{re.escape(k)}=["\']?{re.escape(v)}["\']?')
    # Match <meta ... content="...">
    combined = r"\s+".join(attr_patterns)
    pattern = rf'<meta\s+[^>]*{combined}[^>]*content=["\']?([^"\'>]+)'
    m = re.search(pattern, html, re.IGNORECASE)
    if m:
        return _clean(m.group(1))
    # Try reversed order (content before name/property)
    pattern2 = rf'<meta\s+[^>]*content=["\']?([^"\'>]+)["\']?[^>]*{combined}'
    m2 = re.search(pattern2, html, re.IGNORECASE)
    if m2:
        return _clean(m2.group(1))
    return None


def _extract_json_ld(html: str) -> str | None:
    """Try to grab abstract from JSON-LD script tag."""
    m = re.search(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    try:
        import json
        data = json.loads(m.group(1))
        if isinstance(data, dict):
            ab = data.get("abstract")
            if ab:
                return _clean(str(ab))
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and "abstract" in item:
                    return _clean(item["abstract"])
    except Exception:
        pass
    return None


def _extract_ieee(html: str) -> str | None:
    # og:description on IEEE is usually the abstract
    return _extract_meta(html, property="og:description")


def _extract_acm(html: str) -> str | None:
    return _extract_meta(html, name="citation_abstract")


def _extract_springer(html: str) -> str | None:
    ab = _extract_json_ld(html)
    if ab:
        return ab
    return _extract_meta(html, name="description")


def _extract_elsevier(html: str) -> str | None:
    return _extract_meta(html, name="citation_abstract")


def _extract_wiley(html: str) -> str | None:
    return _extract_meta(html, name="citation_abstract")


def _extract_pmlr(html: str) -> str | None:
    m = re.search(r'<div[^>]*class=["\']abstract["\'][^>]*>(.*?)</div>', html, re.DOTALL | re.IGNORECASE)
    if m:
        return _clean(re.sub(r'<[^>]+>', '', m.group(1)))
    return None


def _extract_neurips(html: str) -> str | None:
    # New NeurIPS proceedings use <p class="paper-abstract">
    m = re.search(r'<p[^>]*class=["\']paper-abstract["\'][^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
    if m:
        return _clean(re.sub(r'<[^>]+>', '', m.group(1)))
    # Old format: first substantial <p> after the title
    m = re.search(r'<div[^>]*class=["\']container["\'][^>]*>.*?<h4[^>]*>.*?</h4>\s*<p>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
    if m:
        return _clean(re.sub(r'<[^>]+>', '', m.group(1)))
    # Fallback: any <p> with substantial text (skip redirect notices)
    for m in re.finditer(r'<p>(.*?)</p>', html, re.DOTALL | re.IGNORECASE):
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if len(text) >= 60 and "document has moved" not in text.lower():
            return _clean(text)
    return None


def _extract_aaai(html: str) -> str | None:
    # AAAI uses <section class="item abstract"> <h2 class="label">Abstract</h2> text ... </section>
    m = re.search(
        r'<section[^>]*class=["\']item abstract["\'][^>]*>.*?<h[^>]*>\s*Abstract\s*</h[^>]*>(.*?)</section>',
        html, re.DOTALL | re.IGNORECASE,
    )
    if m:
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if len(text) >= 30:
            return _clean(text)
    # Fallback: search for "Abstract" heading followed by paragraph
    m2 = re.search(r'<h[23][^>]*>\s*Abstract\s*</h[23]>\s*<p>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
    if m2:
        return _clean(re.sub(r'<[^>]+>', '', m2.group(1)))
    return None


def _extract_aclanthology(html: str) -> str | None:
    """Extract abstract from aclanthology.org."""
    # Primary: <div class="card-body"> contains the abstract text
    m = re.search(
        r'<div[^>]*class=["\']card-body["\'][^>]*>(.*?)</div>',
        html, re.DOTALL | re.IGNORECASE,
    )
    if m:
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        if len(text) >= 60:
            return _clean(text)
    # Fallback: og:description meta
    ab = _extract_meta(html, property="og:description")
    if ab:
        return ab
    # Last resort: first substantial paragraph after abstract heading
    m2 = re.search(
        r'<h[^>]*>\s*Abstract\s*</h[^>]*>\s*<p[^>]*>(.*?)</p>',
        html, re.DOTALL | re.IGNORECASE,
    )
    if m2:
        return _clean(re.sub(r'<[^>]+>', '', m2.group(1)))
    return None


def _extract_ndss(html: str) -> str | None:
    """Extract abstract from ndss-symposium.org."""
    # NDSS uses WordPress article tags
    m = re.search(
        r'<article[^>]*class=["\'][^"\']*post[^"\']*["\'][^>]*>.*?</article>',
        html, re.DOTALL | re.IGNORECASE,
    )
    if m:
        article = m.group(0)
        # Find the abstract section within the article
        abs_match = re.search(r'<p>(.{50,5000}?)</p>', article, re.DOTALL)
        if abs_match:
            text = re.sub(r'<[^>]+>', '', abs_match.group(1)).strip()
            if len(text) >= 30:
                return _clean(text)
    # Fallback: og:description
    return _extract_meta(html, property="og:description")


def _extract_usenix(html: str) -> str | None:
    """Extract abstract from usenix.org."""
    # USENIX uses Drupal field-name-field-paper-description
    m = re.search(
        r'<div class="field field-name-field-paper-description[^"]*"[^>]*>.*?'
        r'<div class="field-items[^"]*"><div class="field-item[^"]*"><p>(.*?)</p>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if m:
        text = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if len(text) >= 30:
            return _clean(text)
    # Fallback: og:description
    return _extract_meta(html, property="og:description")


# Domain -> extractor mapping (partial match on hostname)
EXTRACTORS: list[tuple[str, Callable[[str], str | None]]] = [
    ("ieeexplore.ieee.org", _extract_ieee),
    ("dl.acm.org", _extract_acm),
    ("link.springer.com", _extract_springer),
    ("sciencedirect.com", _extract_elsevier),
    ("linkinghub.elsevier.com", _extract_elsevier),
    ("onlinelibrary.wiley.com", _extract_wiley),
    ("proceedings.mlr.press", _extract_pmlr),
    ("papers.nips.cc", _extract_neurips),
    ("proceedings.neurips.cc", _extract_neurips),
    ("ojs.aaai.org", _extract_aaai),
    ("aclanthology.org", _extract_aclanthology),
    ("ndss-symposium.org", _extract_ndss),
    ("usenix.org", _extract_usenix),
]


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def resolve_doi_url(client: httpx.Client, doi_url: str, timeout: int = 15) -> str | None:
    """Follow doi.org redirect and return final URL (or None on failure)."""
    try:
        r = client.head(doi_url, follow_redirects=True, timeout=timeout)
        if r.status_code in (200, 301, 302, 307, 308):
            return str(r.url)
        # HEAD may not be supported or returns error; try GET
        r2 = client.get(doi_url, follow_redirects=True, timeout=timeout)
        # Return final URL even if GET returns 403/404 — callers need the
        # resolved domain to decide whether to attempt extraction.
        return str(r2.url)
    except Exception:
        return None


def extract_abstract(html: str, url: str) -> str | None:
    """Try to extract abstract from HTML given the source URL."""
    domain = url.split("/")[2].lower()
    if domain.startswith("www."):
        domain = domain[4:]

    for pattern, fn in EXTRACTORS:
        if pattern in domain:
            return fn(html)
    return None


def fetch_abstract(
    client: httpx.Client,
    url: str,
    *,
    timeout: int = 15,
    resolve_doi: bool = True,
) -> str | None:
    """Fetch abstract from a publisher URL.

    Returns the abstract text, or None if extraction failed / unsupported domain.
    """
    # Skip domains handled by dedicated modules
    domain = url.split("/")[2].lower()
    if "arxiv.org" in domain or "openreview.net" in domain:
        return None

    final_url = url
    if resolve_doi and "doi.org" in domain:
        resolved = resolve_doi_url(client, url, timeout=timeout)
        if not resolved:
            return None
        final_url = resolved

    # Check if resolved domain is supported
    resolved_domain = final_url.split("/")[2].lower()
    if resolved_domain.startswith("www."):
        resolved_domain = resolved_domain[4:]
    supported = any(p in resolved_domain for p, _ in EXTRACTORS)
    if not supported:
        return None

    try:
        r = client.get(final_url, timeout=timeout, follow_redirects=True)
        if r.status_code != 200:
            return None
        return extract_abstract(r.text, final_url)
    except Exception:
        return None


def fetch_batch(
    urls: list[tuple[str, str]],
    client: httpx.Client | None = None,
    *,
    workers: int = 3,
    delay: float = 0.5,
    timeout: int = 15,
) -> dict[str, str | None]:
    """Fetch abstracts for multiple papers with controlled concurrency.

    Args:
        urls: list of (paper_id, url) tuples.
        client: shared httpx client.
        workers: max concurrent requests.
        delay: minimum delay between starting requests (coarse rate limit).
        timeout: per-request timeout.

    Returns:
        Mapping paper_id -> abstract (or None).
    """
    if client is None:
        client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"},
        )

    results: dict[str, str | None] = {}

    def _task(paper_id: str, url: str) -> tuple[str, str | None]:
        return paper_id, fetch_abstract(client, url, timeout=timeout)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {}
        for pid, url in urls:
            f = pool.submit(_task, pid, url)
            futures[f] = pid
            time.sleep(delay)  # coarse rate limit between submissions

        for future in as_completed(futures):
            pid, abstract = future.result()
            results[pid] = abstract

    return results
