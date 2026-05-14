"""Fetchers for non-DBLP sources (COLM mini-conf, etc.)."""
from __future__ import annotations

import json
import time
from typing import Iterator

import httpx

from agent_survey.sources.dblp import make_paper_id


def fetch_json_papers(
    url: str,
    year: int,
    *,
    venue_name: str,
    venue_area: str = "",
    venue_type: str = "conference",
    client: httpx.Client | None = None,
) -> Iterator[dict]:
    """Yield papers from a JSON array endpoint (e.g. COLM serve_papers.json).

    Expects a JSON array where each element has at least 'title' and
    'authors' keys.  'authors' may be a list of strings or dicts.
    """
    if client is None:
        client = httpx.Client(
            timeout=30,
            headers={"User-Agent": "agent-survey/0.1"},
        )
    # For colmweb mini-conf sites, verify serve_config.json year before parsing
    if "colmweb.org" in url:
        config_url = url.replace("serve_papers.json", "serve_config.json")
        try:
            cfg_r = client.get(config_url, follow_redirects=True)
            if cfg_r.status_code == 200:
                cfg_data = cfg_r.json()
                config_date = cfg_data.get("date", "")
                if str(year) not in config_date:
                    # Data not yet updated for this year → yield nothing
                    return
        except Exception:
            pass
    r = client.get(url, follow_redirects=True)
    if r.status_code == 404:
        return
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array from {url}, got {type(data).__name__}")

    for item in data:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        raw_authors = item.get("authors") or []
        authors: list[str] = []
        for a in raw_authors:
            if isinstance(a, str):
                authors.append(a)
            elif isinstance(a, dict):
                authors.append(a.get("name") or a.get("full_name") or "")
            else:
                authors.append(str(a))
        authors = [a for a in authors if a]

        abstract = (item.get("abstract") or "").strip() or None
        uid = item.get("UID") or item.get("id") or ""
        doi = item.get("doi") or item.get("DOI") or None
        ee = item.get("url") or item.get("ee") or None

        paper = {
            "dblp_key": None,
            "title": title,
            "year": year,
            "authors": authors,
            "doi": doi,
            "url": ee,
            "venue": venue_name,
            "venue_area": venue_area,
            "venue_type": venue_type,
            "source_flags": ["external_json", venue_name.lower()],
            "abstract": abstract,
        }
        paper["paper_id"] = make_paper_id(
            {"dblp_key": uid, "doi": doi, "title": title, "year": year}
        )
        yield paper

    time.sleep(1)
