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


def search_title(client: httpx.Client, title: str) -> dict | None:
    """Search arXiv by exact title (first match)."""
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
    time.sleep(REQ_DELAY)
    if not entries:
        return None
    # fuzzy match: normalize lowercase + alnum
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", s.lower())
    if norm(entries[0]["title"]) == norm(title):
        return entries[0]
    # still return best match if similarity high enough (cheap check)
    return entries[0] if norm(entries[0]["title"])[:40] == norm(title)[:40] else None


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
