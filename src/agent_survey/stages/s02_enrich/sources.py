"""Source query logic for enrich: venue-optimized parallel queries."""
from __future__ import annotations

import html as _html
import threading

import httpx

from ...services import arxiv as arxiv_src
from ...services.openreview import search_title as or_search_title
from .core import _clear_worker_job, _get_s2, _set_worker_job

# Based on probe results — which *general* sources to launch per venue.
# Venue fetchers (USS/NDSS) and Crossref (DOI) are added independently.
# Keys missing from this map fall back to _DEFAULT_SOURCES.
# Default strategies — fallback when enrich_config.yaml is missing or incomplete.
_DEFAULT_VENUE_STRATEGIES: dict[str, list[str]] = {
    "CHI": ["s2"], "FSE": ["s2"], "ISSTA": ["s2"], "UIST": ["s2"],
    "ASE": ["s2"], "ICSE": ["s2"], "TSE": ["s2"], "SP": ["s2"],
    "TOSEM": ["s2"], "NDSS": ["s2"], "CCS": ["s2"], "NeurIPS": ["playwright", "s2"],
    "ICML": ["meta", "s2"], "ICLR": ["meta", "playwright", "s2"],
    "ACL": ["aclanthology", "meta", "s2"], "COLM": ["s2"],
    "AAAI": ["crossref", "meta", "s2"],
    "EMNLP": ["aclanthology", "meta", "s2"],
    "NAACL": ["aclanthology", "meta", "s2"],
    "USS": [],
}

_DEFAULT_SOURCES = ["meta", "s2", "arxiv"]

# Loaded at runtime from enrich_config.yaml
_venue_strategies: dict[str, list[str]] | None = None
_source_workers: dict[str, int] | None = None


def _load_config():
    """Load enrich config from stage-specific YAML file."""
    global _venue_strategies, _source_workers
    if _venue_strategies is not None:
        return
    from pathlib import Path
    import yaml

    config_path = Path(__file__).resolve().parent / "enrich_config.yaml"
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text()) or {}
        _venue_strategies = data.get("venue_strategies", {}) or {}
        _source_workers = data.get("source_workers", {}) or {}
    # Merge with defaults for any missing venues
    merged = dict(_DEFAULT_VENUE_STRATEGIES)
    merged.update(_venue_strategies or {})
    _venue_strategies = merged


def get_venue_strategies() -> dict[str, list[str]]:
    _load_config()
    return _venue_strategies or _DEFAULT_VENUE_STRATEGIES


def get_source_workers() -> dict[str, int]:
    _load_config()
    return _source_workers or {}


def _try_one_source(
    http: httpx.Client,
    api_key: str,
    row: dict,
    source_name: str,
    cache_db_path: str = "",
) -> tuple[str | None, str | None, str | None, str | None]:
    """Run ONE source for a paper.  Returns (abstract, arxiv_id, pdf_url, source) or Nones."""
    import html as _html_module

    title = _html_module.unescape(row.get("title") or "")
    venue = row.get("venue")
    url = row.get("url")
    doi = row.get("doi") or ""
    _set_worker_job(row, source_name)

    def _valid(text):
        return bool(text) and len(str(text).strip()) >= 30

    # ── Cache check (once per paper, regardless of source) ────
    if cache_db_path:
        from ...services.abstract_cache import lookup
        cached = lookup(cache_db_path, venue, title)
        if cached and len(cached.strip()) >= 30:
            _clear_worker_job()
            return cached, None, None, "cache"

    # ── Dispatch to source handler ──────────────────────────
    if source_name == "s2":
        from ...services.s2 import S2Client
        s2 = S2Client(api_key=api_key, timeout=15)
        try:
            data = s2.search_by_title(title)
            if data and _valid(data.get("abstract")):
                ext = data.get("externalIds") or {}
                oa = data.get("openAccessPdf") or {}
                _clear_worker_job()
                return data["abstract"], ext.get("ArXiv"), oa.get("url"), "s2"
        finally:
            s2.close()

    elif source_name == "arxiv":
        from ...services import arxiv as arxiv_src
        ax = arxiv_src.search_title(http, title)
        if ax and _valid(ax.get("abstract")):
            _clear_worker_job()
            return ax["abstract"], ax.get("arxiv_id"), ax.get("pdf_url"), "arxiv"

    elif source_name == "openreview":
        from ...services.openreview import search_title as or_search
        or_data = or_search(http, title)
        if or_data and _valid(or_data.get("abstract")):
            _clear_worker_job()
            return or_data["abstract"], None, or_data.get("url"), "openreview"

    elif source_name == "openreview_forum":
        import re
        if url and "openreview.net/forum?id=" in url:
            m = re.search(r'forum\?id=([\w_-]+)', url)
            fid = m.group(1) if m else None
            if fid:
                try:
                    r = http.get(f"https://api.openreview.net/notes?forum={fid}", timeout=15)
                    for note in r.json().get("notes", []):
                        content = note.get("content", {})
                        abst = content.get("abstract", "")
                        if isinstance(abst, dict):
                            abst = abst.get("value", "")
                        if isinstance(abst, str) and len(abst.strip()) >= 50:
                            _clear_worker_job()
                            return abst.strip(), None, None, "openreview_forum"
                except Exception:
                    pass

    elif source_name == "aclanthology":
        from .strategies.aclanthology import fetch_aclanthology_abstract
        text = fetch_aclanthology_abstract(http, url)
        if not text and doi:
            text = fetch_aclanthology_abstract(http, doi)
        if text and _valid(text):
            _clear_worker_job()
            return text, None, None, "aclanthology"

    elif source_name == "crossref":
        if doi:
            from .strategies.crossref import fetch_crossref_abstract
            text = fetch_crossref_abstract(http, doi)
            if text and _valid(text):
                _clear_worker_job()
                return text, None, None, "crossref"

    elif source_name == "meta":
        # Fast HTTP: extract abstract from HTML meta tags + page structure regex.
        # Covers: ICLR, ICML, NeurIPS, AAAI, and any venue with server-rendered abstracts.
        import re as _re
        target_url = url or ""

        # AAAI: DOI 10.1609/aaai.v37i1.25137 → ojs.aaai.org/index.php/AAAI/article/view/25137
        # Needs browser UA (site blocks default httpx agent)
        _aaai = doi and doi.startswith("10.1609/")
        if _aaai:
            article_id = doi.rsplit(".", 1)[-1]
            target_url = f"https://ojs.aaai.org/index.php/AAAI/article/view/{article_id}"

        # NeurIPS: papers.nips.cc → proceedings.neurips.cc
        _neurips = "papers.nips.cc" in (target_url or "")
        if _neurips:
            target_url = target_url.replace("http://papers.nips.cc", "https://proceedings.neurips.cc")

        if _neurips:
            try:
                r = http.get(target_url, timeout=10)
                m = _re.search(r'<p class="paper-abstract">\s*(.*?)</p>', r.text, _re.DOTALL)
                if m:
                    text = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    if len(text) >= 50:
                        _clear_worker_job()
                        return text, None, None, "meta"
            except Exception:
                pass
            return None  # Don't fall through

        # Generic: meta tag or page body extraction
        if target_url:
            try:
                _headers = {"User-Agent": "Mozilla/5.0"} if (_aaai or "ojs.aaai.org" in target_url) else {}
                r = http.get(target_url, timeout=10, headers=_headers if _headers else None)
                html = r.text

                # Meta tags (relaxed regex to allow intermediate attrs like xml:lang)
                for tag_re in [
                    r'<meta\s+name="citation_abstract"[^>]*content="([^"]+)"',
                    r'<meta\s+property="og:description"[^>]*content="([^"]+)"',
                    r'<meta\s+name="description"[^>]*content="([^"]+)"',
                    r'<meta\s+name="DC\.Description"[^>]*content="([^"]+)"',
                ]:
                    mm = _re.search(tag_re, html)
                    if mm and len(mm.group(1)) >= 50:
                        text = mm.group(1)
                        text = text.replace("&#x27;", "'").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                        _clear_worker_job()
                        return text, None, None, "meta"

                # Page body: <section class="item abstract"><h2>Abstract</h2>{text}</section>
                m = _re.search(r'<section\s+class="item abstract">\s*<h2[^>]*>Abstract</h2>\s*(.*?)</section>', html, _re.DOTALL)
                if m:
                    text = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    if len(text) >= 50:
                        _clear_worker_job()
                        return text, None, None, "meta"

                # ACL Anthology: <div class="card-body acl-abstract"><h5>Abstract</h5><span>{text}</span>
                m = _re.search(r'class="card-body acl-abstract">\s*<h5[^>]*>Abstract</h5>\s*<span[^>]*>(.*?)</span>', html, _re.DOTALL)
                if m:
                    text = _re.sub(r'<[^>]+>', '', m.group(1)).strip()
                    if len(text) >= 50:
                        _clear_worker_job()
                        return text, None, None, "meta"
            except Exception:
                pass

    elif source_name == "playwright":
        # Real headless browser for JS-only pages (NeurIPS papers.nips.cc, etc.)
        from .strategies.playwright_generic import fetch_playwright_generic
        target_url = url or (f"https://doi.org/{doi}" if doi else "")
        text = fetch_playwright_generic(target_url, "", timeout=20)
        if text and _valid(text):
            _clear_worker_job()
            return text, None, None, "playwright"

    _clear_worker_job()
    return None, None, None, None


# Backward compat — old concurrent racing version
def _try_sources(
    http: httpx.Client,
    api_key: str,
    row: dict,
    cache_db_path: str = "",
) -> tuple[str | None, str | None, str | None, str | None]:
    """Return (abstract, arxiv_id, pdf_url, source) or all Nones.

    Checks abstract_cache first (by venue+title), then launches
    venue-optimized queries concurrently.
    """
    title = _html.unescape(row.get("title") or "")
    venue = row.get("venue")
    url = row.get("url")
    _set_worker_job(row, "querying")

    # ── Cache hit? ───────────────────────────────────────────────
    if cache_db_path:
        from ...services.abstract_cache import lookup

        cached = lookup(cache_db_path, venue, title)
        if cached and len(cached.strip()) >= 30:
            _clear_worker_job()
            return cached, None, None, "cache"

    result_event = threading.Event()
    result_box: dict = {}
    result_lock = threading.Lock()

    def _query_one(name: str, fn):
        if result_event.is_set():
            return
        try:
            res = fn()
            if res:
                with result_lock:
                    if not result_event.is_set():
                        result_box["result"] = res
                        result_box["source"] = name
                        result_event.set()
        except Exception:
            pass

    def _valid_abstract(text: str | None) -> bool:
        return bool(text) and len(text.strip()) >= 30

    def _s2_fn():
        s2 = _get_s2(api_key)
        data = s2.search_by_title(title)
        if data and _valid_abstract(data.get("abstract")):
            ext = data.get("externalIds") or {}
            oa = data.get("openAccessPdf") or {}
            return data["abstract"], ext.get("ArXiv"), oa.get("url")
        return None

    def _arxiv_fn():
        ax = arxiv_src.search_title(http, title)
        if ax and _valid_abstract(ax.get("abstract")):
            return ax["abstract"], ax.get("arxiv_id"), ax.get("pdf_url")
        return None

    def _or_fn():
        or_data = or_search_title(http, title)
        if or_data and _valid_abstract(or_data.get("abstract")):
            return or_data["abstract"], None, or_data.get("url")
        return None

    def _crossref_fn():
        doi = (url or "").replace("https://doi.org/", "").replace("http://doi.org/", "")
        if not doi:
            return None
        from .strategies.crossref import fetch_crossref_abstract

        text = fetch_crossref_abstract(http, doi)
        if text:
            return text, None, None
        return None

    # ── build thread list based on venue-optimized strategy ────────
    strategies = get_venue_strategies()
    general_sources = strategies.get(venue, _DEFAULT_SOURCES)

    threads: list[threading.Thread] = []
    if "s2" in general_sources:
        threads.append(threading.Thread(target=_query_one, args=("s2", _s2_fn), daemon=True))
    if "arxiv" in general_sources:
        threads.append(threading.Thread(target=_query_one, args=("arxiv", _arxiv_fn), daemon=True))
    if "openreview" in general_sources:
        threads.append(threading.Thread(target=_query_one, args=("openreview", _or_fn), daemon=True))

    # OpenReview forum ID direct lookup (ICLR papers have forum URLs)
    if "openreview_forum" in general_sources:
        def _or_forum_fn():
            fid = None
            if url and "openreview.net/forum?id=" in url:
                import re
                m = re.search(r'forum\?id=([\w_-]+)', url)
                fid = m.group(1) if m else None
            if not fid:
                return None
            try:
                r = http.get(f"https://api.openreview.net/notes?forum={fid}", timeout=15)
                notes = r.json().get("notes", [])
                for note in notes:
                    content = note.get("content", {})
                    abst = content.get("abstract", "")
                    if isinstance(abst, dict):
                        abst = abst.get("value", "")
                    if isinstance(abst, str) and len(abst.strip()) >= 50:
                        return abst.strip(), None, None
            except Exception:
                pass
            return None

        threads.append(threading.Thread(
            target=_query_one, args=("openreview_forum", _or_forum_fn), daemon=True))

    # ACL Anthology scraper (EMNLP, NAACL, ACL)
    if "aclanthology" in general_sources:
        def _aclanthology_fn():
            from .strategies.aclanthology import fetch_aclanthology_abstract
            # Try URL first, then DOI
            text = fetch_aclanthology_abstract(http, url or "")
            if not text:
                doi = row.get("doi") or ""
                if doi:
                    text = fetch_aclanthology_abstract(http, doi)
            if text:
                return text, None, None
            return None

        threads.append(threading.Thread(
            target=_query_one, args=("aclanthology", _aclanthology_fn), daemon=True))

    # Crossref: any paper with a DOI (especially ACM journal papers like TOSEM)
    if url and ("doi.org" in url or url.startswith("10.")):
        threads.append(
            threading.Thread(
                target=_query_one,
                args=("crossref", _crossref_fn),
                daemon=True,
            )
        )

    # Venue-specific direct fetch (USS, NDSS)
    from .strategies import VENUE_FETCHERS  # lazy import to avoid cycles

    if venue in VENUE_FETCHERS and url:
        fetcher = VENUE_FETCHERS[venue]

        def _venue_fn():
            text = fetcher(url)
            if _valid_abstract(text):
                return text, None, None
            return None

        threads.append(
            threading.Thread(
                target=_query_one,
                args=(f"venue_{venue.lower()}", _venue_fn),
                daemon=True,
            )
        )

    for t in threads:
        t.start()

    # Wait up to 5 s for the first hit
    # (was 30s → 10s → 5s: for S2-only venues, if S2 misses,
    #  no other thread will signal; don't waste time)
    result_event.wait(timeout=5)

    _clear_worker_job()
    if result_box:
        r = result_box["result"]
        return r[0], r[1], r[2], result_box["source"]
    return None, None, None, None
