"""ACL Anthology abstract fetcher — fast httpx + regex, no Playwright.

For EMNLP, NAACL, ACL venues.  Each ACL Anthology page has:
  <div class="card-body acl-abstract"><h5>Abstract</h5><span>{TEXT}</span>

Supports both direct ACL URLs and DOI-based URL construction.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx

_ABSTRACT_RE = re.compile(
    r'Abstract</h5>\s*<span[^>]*>(.*?)</span>',
    re.DOTALL,
)

# DOIs like 10.18653/v1/2023.emnlp-main.17 → https://aclanthology.org/2023.emnlp-main.17/
_ACL_DOI_RE = re.compile(r'^10\.18653/v\d+/(.+)$')


def _doi_to_acl_url(doi: str) -> str | None:
    m = _ACL_DOI_RE.match(doi.strip())
    if not m:
        return None
    return f"https://aclanthology.org/{m.group(1)}/"


def _resolve_acl_url(url_or_doi: str) -> str | None:
    """Given a URL or DOI, return the ACL Anthology page URL."""
    if not url_or_doi:
        return None
    s = url_or_doi.strip()
    # Already an ACL URL
    if "aclanthology.org" in s:
        return s if s.endswith("/") else s + "/"
    # DOI → ACL URL
    if s.startswith("10.18653/"):
        return _doi_to_acl_url(s)
    return None


def fetch_aclanthology_abstract(http: httpx.Client, url_or_doi: str) -> str | None:
    """Scrape abstract from an ACL Anthology paper page.

    Accepts either a direct ACL URL or an ACL DOI.
    """
    acl_url = _resolve_acl_url(url_or_doi)
    if not acl_url:
        return None
    try:
        r = http.get(acl_url, timeout=15)
        if r.status_code != 200:
            return None
        html = r.text
    except Exception:
        return None

    m = _ABSTRACT_RE.search(html)
    if not m:
        return None
    text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
    if len(text) >= 30:
        return text
    return None
