"""API-only paper resolver with polite 429 backoff. No browser, no pressure."""
from __future__ import annotations

import json
import logging
import re
import sys
import time
import traceback
from pathlib import Path

import httpx

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
log_path = Path("/tmp/api_backoff_debug.log")
log_path.unlink(missing_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(str(log_path), mode="w", encoding="utf-8"),
    ],
)
logger = logging.getLogger("api_backoff")

PROXY = "socks5://10.20.197.128:7890"
S2_API_KEY = ""  # fill if available

TITLES = [
    "AutoSurvey: Large Language Models Can Automatically Write Surveys",
    "PaSa: An LLM Agent for Comprehensive Academic Paper Search",
    "CycleResearcher: Improving Automated Research via Automated Reviewing",
]


def polite_request(
    client: httpx.Client,
    method: str,
    url: str,
    max_retries: int = 3,
    base_backoff: float = 60.0,
    **kwargs,
) -> httpx.Response | None:
    """Make request with 429 exponential backoff."""
    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"  [{method}] {url[:80]}... (attempt {attempt}/{max_retries})")
            r = client.request(method, url, **kwargs)

            if r.status_code == 429:
                wait = base_backoff * (2 ** (attempt - 1))
                logger.warning(f"  → 429 received, backing off {wait:.0f}s...")
                time.sleep(wait)
                continue

            # Any other error on last attempt
            if r.status_code >= 400 and attempt == max_retries:
                logger.warning(f"  → {r.status_code} on final attempt")
                return r

            if r.status_code < 400:
                return r

        except httpx.ConnectError as e:
            logger.error(f"  → ConnectError: {e}")
            if attempt == max_retries:
                return None
            time.sleep(base_backoff)
        except Exception as e:
            logger.error(f"  → {type(e).__name__}: {e}")
            if attempt == max_retries:
                return None
            time.sleep(base_backoff)

    return None


def search_arxiv(client: httpx.Client, title: str) -> dict | None:
    logger.info("  [arXiv API] searching...")
    q = title.replace('"', "").strip()
    r = polite_request(
        client,
        "GET",
        "https://export.arxiv.org/api/query",
        params={"search_query": f'ti:"{q}"', "max_results": 3, "sortBy": "relevance"},
    )
    if not r:
        return None
    if r.status_code != 200:
        logger.warning(f"  → arXiv status={r.status_code}")
        return None

    text = r.text
    if "<entry>" not in text:
        logger.info("  → no entries")
        return None

    entries = text.split("<entry>")[1:]
    def _title_dist(e):
        t = re.search(r"<title>([^<]+)</title>", e)
        return levenshtein(title.lower(), (t.group(1) if t else "").lower())

    best = min(entries, key=_title_dist)
    arxiv_id = re.search(r"<id>([^<]+)</id>", best)
    arxiv_id = (arxiv_id.group(1).split("/")[-1] if arxiv_id else "")
    summary = re.search(r"<summary>([^<]+)</summary>", best)
    published = re.search(r"<published>([^<]+)</published>", best)
    authors = re.findall(r"<name>([^<]+)</name>", best)

    return {
        "source": "arxiv_api",
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": authors,
        "year": (published.group(1)[:4] if published else None),
        "abstract": (summary.group(1).strip() if summary else ""),
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None,
    }


def download_pdf(client: httpx.Client, pdf_url: str) -> bool:
    logger.info(f"  [PDF DL] {pdf_url} ...")
    r = polite_request(client, "GET", pdf_url, timeout=60)
    if not r:
        return False
    ok = r.status_code == 200 and len(r.content) > 1024
    logger.info(f"  → status={r.status_code}, size={len(r.content) if r.content else 0}, ok={ok}")
    return ok


def search_s2(client: httpx.Client, title: str) -> dict | None:
    logger.info("  [S2 API] searching...")
    headers = {"x-api-key": S2_API_KEY} if S2_API_KEY else {}
    r = polite_request(
        client,
        "GET",
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={
            "query": title,
            "fields": "title,authors,year,venue,abstract,openAccessPdf,externalIds",
            "limit": 3,
        },
        headers=headers,
    )
    if not r:
        return None
    if r.status_code != 200:
        logger.warning(f"  → S2 status={r.status_code}, body={r.text[:200]}")
        return None

    papers = r.json().get("data", [])
    if not papers:
        return None

    best = min(papers, key=lambda p: levenshtein(title.lower(), (p.get("title") or "").lower()))
    return {
        "source": "s2_api",
        "title": best.get("title"),
        "authors": [a.get("name") for a in best.get("authors", [])],
        "year": best.get("year"),
        "venue": best.get("venue"),
        "abstract": best.get("abstract"),
        "pdf_url": best.get("openAccessPdf", {}).get("url"),
        "doi": best.get("externalIds", {}).get("DOI"),
        "s2_id": best.get("paperId"),
    }


def levenshtein(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return levenshtein(s2, s1)
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            curr.append(min(prev[j + 1] + 1, curr[j] + 1, prev[j] + (c1 != c2)))
        prev = curr
    return prev[-1]


def resolve_one(client: httpx.Client, title: str) -> dict:
    logger.info(f"\n{'='*50}\nResolving: {title[:60]}...\n{'='*50}")

    # Try arXiv API first
    result = search_arxiv(client, title)
    if result and result.get("pdf_url"):
        logger.info("  → arXiv API found match")
        if download_pdf(client, result["pdf_url"]):
            result["download_ok"] = True
            return result
        else:
            result["download_ok"] = False
            # Continue to S2 as fallback for PDF
    elif result:
        logger.info("  → arXiv API found entry but no PDF URL")
    else:
        logger.info("  → arXiv API no match")

    # Fallback to S2
    logger.info("  → trying S2 API...")
    time.sleep(2)
    result = search_s2(client, title)
    if result and result.get("pdf_url"):
        logger.info("  → S2 API found PDF")
        if download_pdf(client, result["pdf_url"]):
            result["download_ok"] = True
            return result
        else:
            result["download_ok"] = False
            return result
    elif result:
        logger.info("  → S2 API found entry but no PDF URL")
        return result
    else:
        logger.info("  → S2 API no match")

    return {"title": title, "source": None, "error": "All sources exhausted"}


def main():
    logger.info("=" * 60)
    logger.info("API-only Resolver with 429 Backoff")
    logger.info(f"Proxy: {PROXY}")
    logger.info("=" * 60)

    client = httpx.Client(
        proxy=PROXY,
        timeout=30,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0 (compatible; agent-survey/0.1)"},
    )

    try:
        results = []
        for i, title in enumerate(TITLES, 1):
            res = resolve_one(client, title)
            results.append(res)
            logger.info(f"  => FINAL: source={res.get('source')}, pdf_url={'YES' if res.get('pdf_url') else 'NO'}, download={'YES' if res.get('download_ok') else 'NO/NA'}")
            if i < len(TITLES):
                logger.info("  [breathing 5s...]")
                time.sleep(5)

        out = Path("/tmp/api_backoff_results.json")
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"\nResults saved to {out}")
        logger.info(f"Debug log saved to {log_path}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
