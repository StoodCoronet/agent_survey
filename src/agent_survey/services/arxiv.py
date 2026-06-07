"""arXiv API client."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from typing import Iterator

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ._curl_fallback import curl_get_xml_text

ARXIV_API = "http://export.arxiv.org/api/query"
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
REQ_DELAY = 3.0  # arXiv official rate limit


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=10))
def _query(client: httpx.Client, params: dict) -> str:
    r = client.get(ARXIV_API, params=params)
    r.raise_for_status()
    return r.text


def _parse_entries(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out: list[dict] = []
    for entry in root.findall("a:entry", NS):
        arxiv_url = entry.findtext("a:id", default="", namespaces=NS)
        m = re.search(r"arxiv\.org/abs/([^v\s]+)(v\d+)?", arxiv_url)
        arxiv_id = m.group(1) if m else None
        title = (entry.findtext("a:title", default="", namespaces=NS) or "").strip()
        summary = (entry.findtext("a:summary", default="", namespaces=NS) or "").strip()
        published = entry.findtext("a:published", default="", namespaces=NS) or ""
        year = int(published[:4]) if published[:4].isdigit() else None
        authors = [a.findtext("a:name", default="", namespaces=NS) for a in entry.findall("a:author", NS)]
        # pdf url
        pdf_url = None
        for link in entry.findall("a:link", NS):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href")
                break
        if not pdf_url and arxiv_id:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        doi = entry.findtext("arxiv:doi", default=None, namespaces=NS)
        out.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "abstract": summary,
                "authors": authors,
                "year": year,
                "pdf_url": pdf_url,
                "url": arxiv_url,
                "doi": doi,
            }
        )
    return out


def search_title(client: httpx.Client, title: str, delay: float = REQ_DELAY) -> dict | None:
    """Search arXiv by exact title (first match).

    Args:
        delay: seconds to sleep after the request (override for bulk operations).
    """
    q = title.replace('"', "").strip()
    if not q:
        return None
    params = {
        "search_query": f'ti:"{q}"',
        "max_results": 1,
        "sortBy": "relevance",
    }
    xml_text: str | None = None
    try:
        xml_text = _query(client, params)
    except Exception:
        # macOS Anaconda OpenSSL 3.0 TLS handshake failure — fallback to curl
        # arXiv API is heavily rate-limited from some IPs; use short timeout
        xml_text = curl_get_xml_text(ARXIV_API, params=params, timeout=3)
    if xml_text is None:
        return None
    entries = _parse_entries(xml_text)
    time.sleep(delay)
    if not entries:
        return None
    # fuzzy match: strip all spaces and non-alphanumeric chars
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    def _match(e_title: str, db_title: str) -> bool:
        """Loose title matching: exact, substring (for long titles), or prefix."""
        e_norm = _norm(e_title)
        db_norm = _norm(db_title)
        if e_norm == db_norm:
            return True
        # Substring match for long titles (handles suffix differences like "Transformers")
        if len(db_norm) >= 20 and (db_norm in e_norm or e_norm in db_norm):
            return True
        # Prefix fallback
        if len(db_norm) > 30 and len(e_norm) > 30 and e_norm[:40] == db_norm[:40]:
            return True
        return False

    # Check all entries (arxiv search may return wrong first result)
    for e in entries:
        if _match(e["title"], title):
            return e
    return None


def _search_exact(client: httpx.Client, title: str, delay: float) -> dict | None:
    """Internal: single exact-title search."""
    q = title.replace('"', "").strip()
    if not q:
        return None
    params = {
        "search_query": f'ti:"{q}"',
        "max_results": 3,
        "sortBy": "relevance",
    }
    xml_text: str | None = None
    try:
        xml_text = _query(client, params)
    except Exception:
        xml_text = curl_get_xml_text(ARXIV_API, params=params, timeout=3)
    if xml_text is None:
        return None
    entries = _parse_entries(xml_text)
    time.sleep(delay)
    if not entries:
        return None
    def _norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())

    def _match(e_title: str, db_title: str) -> bool:
        e_norm = _norm(e_title)
        db_norm = _norm(db_title)
        if e_norm == db_norm:
            return True
        if len(db_norm) >= 20 and (db_norm in e_norm or e_norm in db_norm):
            return True
        if len(db_norm) > 30 and len(e_norm) > 30 and e_norm[:40] == db_norm[:40]:
            return True
        return False

    for e in entries:
        if _match(e["title"], title):
            return e
    return None


def _clean_title_for_search(title: str) -> str:
    """Replace non-alphabetic chars with spaces for arXiv search."""
    cleaned = re.sub(r"[^a-zA-Z]", " ", title)
    return re.sub(r"\s+", " ", cleaned).strip()


def _generate_search_variants(title: str) -> list[str]:
    """Generate multiple title variants for arXiv search."""
    variants: list[str] = [title]
    # 1. Cleaned version (non-alpha -> spaces)
    cleaned = _clean_title_for_search(title)
    if cleaned and cleaned != title:
        variants.append(cleaned)
    # 2. Colon split: "Title: Subtitle" -> try both parts
    if ":" in title:
        parts = title.split(":", 1)
        for p in parts:
            p = p.strip()
            if p and p not in variants:
                variants.append(p)
            p_clean = _clean_title_for_search(p)
            if p_clean and p_clean not in variants:
                variants.append(p_clean)
    # 3. CamelCase split
    camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", title)
    if camel != title and camel not in variants:
        variants.append(camel)
    # 4. Remove & and normalize
    no_amp = title.replace("&", " ")
    if no_amp != title and no_amp not in variants:
        variants.append(no_amp)
    # 5. First 5 words fallback
    words = title.split()[:5]
    if len(words) >= 3:
        short = " ".join(words)
        if short not in variants:
            variants.append(short)
    return variants


def search_title(client: httpx.Client, title: str, delay: float = REQ_DELAY) -> dict | None:
    """Search arXiv by title with multi-variant matching."""
    variants = _generate_search_variants(title)
    for v in variants:
        result = _search_exact(client, v, delay)
        if result:
            return result
    return None


def search_query(
    client: httpx.Client,
    query: str,
    *,
    max_results: int = 500,
    page_size: int = 100,
    year_start: int | None = None,
    year_end: int | None = None,
) -> Iterator[dict]:
    offset = 0
    total_yielded = 0
    while total_yielded < max_results:
        params = {
            "search_query": query,
            "start": offset,
            "max_results": min(page_size, max_results - total_yielded),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        try:
            xml_text = _query(client, params)
        except Exception:
            break
        entries = _parse_entries(xml_text)
        if not entries:
            break
        for e in entries:
            y = e.get("year")
            if year_start and (y or 0) < year_start:
                return
            if year_end and (y or 0) > year_end:
                continue
            yield e
            total_yielded += 1
            if total_yielded >= max_results:
                return
        offset += len(entries)
        time.sleep(REQ_DELAY)


def download_pdf(client: httpx.Client, arxiv_id: str, dest_path) -> bool:
    url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    try:
        with client.stream("GET", url, timeout=60, follow_redirects=True) as r:
            r.raise_for_status()
            with open(dest_path, "wb") as f:
                for chunk in r.iter_bytes(chunk_size=65536):
                    f.write(chunk)
        return True
    except Exception:
        return False
