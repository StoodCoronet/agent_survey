"""DBLP harvester.

Uses the DBLP search API with `venue:XXX year:YYYY` filters.
DBLP returns up to 1000 hits per page; we paginate via `f` (first offset).
"""
from __future__ import annotations

import hashlib
import re
import time
import xml.etree.ElementTree as ET
from typing import Iterator

from urllib.parse import quote

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

DBLP_API = "https://dblp.org/search/publ/api"
PAGE_SIZE = 1000
REQ_DELAY = 1.5  # seconds between calls (DBLP is generous but let's be polite)


def _is_retryable(exc: BaseException) -> bool:
    """Retry on 5xx + TCP/TLS/protocol errors. Never retry 4xx (permanent)."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            return exc.response.status_code >= 500
        except Exception:
            return False
    return isinstance(
        exc,
        (
            httpx.RemoteProtocolError,
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadError,
            httpx.ReadTimeout,
            httpx.WriteError,
            httpx.PoolTimeout,
        ),
    )


def _slugify_title(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s[:80]


def make_paper_id(hit: dict) -> str:
    """Stable paper_id: prefer DBLP key, fallback to doi/title-year hash."""
    dblp_key = hit.get("dblp_key") or hit.get("@id")
    if dblp_key:
        return f"dblp:{dblp_key}"
    doi = hit.get("doi")
    if doi:
        return f"doi:{doi.lower()}"
    title = hit.get("title") or ""
    year = hit.get("year") or ""
    h = hashlib.sha1(f"{title.lower()}|{year}".encode()).hexdigest()[:12]
    return f"ti:{h}"


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=3, max=60),
    retry=retry_if_exception(_is_retryable),
)
def _fetch(client: httpx.Client, params: dict) -> dict:
    # DBLP's server returns HTTP 500 when the `q` value is encoded with `+` for
    # spaces; it only accepts %20. httpx/urllib default to `+`, so we build
    # the URL by hand using quote(..., safe="").
    p = dict(params)
    q = p.pop("q")
    extras = "&".join(f"{k}={v}" for k, v in p.items())
    url = f"{DBLP_API}?q={quote(q, safe='')}" + (f"&{extras}" if extras else "")
    r = client.get(url)
    r.raise_for_status()
    return r.json()


def _normalize_hit(hit: dict, venue_name: str, venue_area: str, venue_type: str) -> dict | None:
    info = hit.get("info", {}) or {}
    title = (info.get("title") or "").strip().rstrip(".")
    if not title:
        return None
    year = info.get("year")
    try:
        year = int(year) if year else None
    except Exception:
        year = None
    doi = info.get("doi")
    url = info.get("url")       # dblp rec URL
    ee = info.get("ee")         # external link (often DOI or paper URL)
    authors_field = (info.get("authors") or {}).get("author") or []
    if isinstance(authors_field, dict):
        authors_field = [authors_field]
    authors = [a.get("text") if isinstance(a, dict) else str(a) for a in authors_field]
    # dblp_key = info.get("key")  # e.g. "conf/icse/FooB24"
    dblp_key = info.get("key") or hit.get("@id")
    paper = {
        "dblp_key": dblp_key,
        "title": title,
        "year": year,
        "authors": authors,
        "doi": doi,
        "url": ee or url,
        "venue": venue_name,
        "venue_area": venue_area,
        "venue_type": venue_type,
        "source_flags": ["dblp"],
    }
    paper["paper_id"] = make_paper_id({"dblp_key": dblp_key, "doi": doi, "title": title, "year": year})
    return paper


def fetch_venue_year(
    venue_name: str,
    year: int,
    *,
    venue_area: str = "",
    venue_type: str = "conf",
    client: httpx.Client | None = None,
    aliases: list[str] | None = None,
    key_prefixes: list[str] | None = None,
) -> Iterator[dict]:
    """Yield normalized paper dicts for one (venue, year).

    DBLP `venue:` query over-matches co-located workshops, so we post-filter
    records by `key_prefixes` (e.g. ["conf/issta/"]) when provided.
    """
    if client is None:
        client = httpx.Client(
            timeout=30,
            headers={"User-Agent": "agent-survey/0.1", "Accept": "application/json"},
        )
    names = [venue_name] + (aliases or [])
    seen_keys: set[str] = set()
    for name in names:
        # venue: filter uses string containment; wrap in quotes if it has spaces/&
        q_name = f'"{name}"' if any(c in name for c in " /&") else name
        offset = 0
        while True:
            params = {
                "q": f"venue:{q_name} year:{year}",
                "format": "json",
                "h": PAGE_SIZE,
                "f": offset,
            }
            data = _fetch(client, params)
            hits_block = data.get("result", {}).get("hits", {}) or {}
            total = int(hits_block.get("@total", 0))
            hits = hits_block.get("hit", []) or []
            if isinstance(hits, dict):
                hits = [hits]
            if not hits:
                break
            for hit in hits:
                paper = _normalize_hit(hit, venue_name, venue_area, venue_type)
                if not paper:
                    continue
                k = paper.get("dblp_key") or ""
                if key_prefixes and not any(k.startswith(p) for p in key_prefixes):
                    continue
                if k in seen_keys:
                    continue
                seen_keys.add(k)
                yield paper
            offset += len(hits)
            if offset >= total:
                break
            time.sleep(REQ_DELAY)
        time.sleep(REQ_DELAY)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(min=3, max=60),
    retry=retry_if_exception(_is_retryable),
)
def _fetch_xml(client: httpx.Client, url: str) -> str:
    r = client.get(url, follow_redirects=True)
    r.raise_for_status()
    return r.text


def fetch_toc_xml(
    toc_stream: str,
    year: int,
    *,
    venue_name: str,
    venue_area: str = "",
    venue_type: str = "conf",
    client: httpx.Client | None = None,
) -> Iterator[dict]:
    """Yield papers for one (venue, year) by parsing DBLP's TOC XML directly.

    Use this for venues whose `venue:` search index is broken or missing
    (e.g. USENIX Security: every `venue:*` query returns 0 hits or HTTP 500).

    `toc_stream` is the DBLP TOC stem, e.g. "conf/uss/uss" → URL becomes
    https://dblp.org/db/conf/uss/uss<year>.xml
    """
    if client is None:
        client = httpx.Client(
            timeout=30,
            headers={"User-Agent": "agent-survey/0.1"},
        )
    url = f"https://dblp.org/db/{toc_stream}{year}.xml"
    try:
        xml = _fetch_xml(client, url)
    except httpx.HTTPStatusError as e:
        # 404 = non-existent TOC (e.g. future year not yet held). Treat as
        # an empty result, not an error — the harvest loop will mark this
        # (venue, year) as `empty` and skip it on subsequent runs.
        if e.response is not None and e.response.status_code == 404:
            return
        raise
    root = ET.fromstring(xml)
    for ip in root.iter("inproceedings"):
        key = ip.get("key") or ""
        title = (ip.findtext("title") or "").strip().rstrip(".")
        if not title:
            continue
        yr_text = ip.findtext("year")
        try:
            yr = int(yr_text) if yr_text else None
        except Exception:
            yr = None
        if yr is not None and yr != year:
            continue
        authors = [a.text for a in ip.findall("author") if a.text]
        ee = ip.findtext("ee")
        doi = None
        if ee and "doi.org/" in ee:
            doi = ee.split("doi.org/")[-1]
        paper = {
            "dblp_key": key,
            "title": title,
            "year": yr,
            "authors": authors,
            "doi": doi,
            "url": ee,
            "venue": venue_name,
            "venue_area": venue_area,
            "venue_type": venue_type,
            "source_flags": ["dblp", "toc"],
        }
        paper["paper_id"] = make_paper_id(
            {"dblp_key": key, "doi": doi, "title": title, "year": yr}
        )
        yield paper
    time.sleep(REQ_DELAY)


def fetch_journal_volumes(
    journal_stream: str,
    volumes: list[int],
    year: int,
    *,
    venue_name: str,
    venue_area: str = "",
    venue_type: str = "journal",
    client: httpx.Client | None = None,
) -> Iterator[dict]:
    """Yield papers for one (journal, year) by parsing per-volume XML.

    DBLP's `venue:` search index is missing recent-year entries for some
    journals (e.g. TOSEM, TSE). Instead, fetch the per-volume listing
    directly at https://dblp.org/db/<journal_stream><vol>.xml and filter
    <article> elements whose <year> equals `year`.
    """
    if client is None:
        client = httpx.Client(
            timeout=30,
            headers={"User-Agent": "agent-survey/0.1"},
        )
    for vol in volumes:
        url = f"https://dblp.org/db/{journal_stream}{vol}.xml"
        try:
            xml = _fetch_xml(client, url)
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                continue
            raise
        root = ET.fromstring(xml)
        for art in root.iter("article"):
            key = art.get("key") or ""
            title = (art.findtext("title") or "").strip().rstrip(".")
            if not title:
                continue
            yr_text = art.findtext("year")
            try:
                yr = int(yr_text) if yr_text else None
            except Exception:
                yr = None
            if yr != year:
                continue
            authors = [a.text for a in art.findall("author") if a.text]
            ee = art.findtext("ee")
            doi = None
            if ee and "doi.org/" in ee:
                doi = ee.split("doi.org/")[-1]
            paper = {
                "dblp_key": key,
                "title": title,
                "year": yr,
                "authors": authors,
                "doi": doi,
                "url": ee,
                "venue": venue_name,
                "venue_area": venue_area,
                "venue_type": venue_type,
                "source_flags": ["dblp", "journal_vol"],
            }
            paper["paper_id"] = make_paper_id(
                {"dblp_key": key, "doi": doi, "title": title, "year": yr}
            )
            yield paper
        time.sleep(REQ_DELAY)
