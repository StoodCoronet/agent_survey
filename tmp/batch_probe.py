"""Batch probe all untested venue+year combos.

Tests 10 papers per combo using priority:
  S2 API → arXiv API → OpenReview API → venue fetcher (curl)

Rate limit: 2s between papers.
Outputs JSON report to tmp/probe_report.json
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from agent_survey.core.config import load_config
from agent_survey.core.db import DB
from agent_survey.services.s2 import S2Client
from agent_survey.services import arxiv as arxiv_src
from agent_survey.services.openreview import search_title as or_search_title
from agent_survey.stages.s01_enrich.strategies import VENUE_FETCHERS

# Combos to test (from md checklist)
COMBOS = [
    ("CHI", 2023), ("CHI", 2024), ("CHI", 2025), ("CHI", 2026),
    ("ICML", 2023), ("ICML", 2024), ("ICML", 2025),
    ("NeurIPS", 2023), ("NeurIPS", 2024),
    ("EMNLP", 2023), ("EMNLP", 2024), ("EMNLP", 2025),
    ("COLM", 2024),
    ("NAACL", 2024), ("NAACL", 2025),
    ("FSE", 2023), ("FSE", 2024), ("FSE", 2025),
    ("TOSEM", 2023), ("TOSEM", 2024), ("TOSEM", 2025), ("TOSEM", 2026),
    ("UIST", 2023), ("UIST", 2024), ("UIST", 2025),
    ("ISSTA", 2024), ("ISSTA", 2025),
    ("CCS", 2025),
    ("NDSS", 2025), ("NDSS", 2026),
    ("USS", 2025),
]


def _valid(text: str | None) -> bool:
    return bool(text) and len(text.strip()) >= 30


def test_paper(s2: S2Client, http: httpx.Client, row: dict) -> dict:
    title = row.get("title") or ""
    venue = row.get("venue") or ""
    url = row.get("url")
    result = {
        "paper_id": row["paper_id"],
        "title": title[:80],
        "results": {},
    }

    # Layer 1a: S2 API
    try:
        data = s2.search_by_title(title)
        if data and _valid(data.get("abstract")):
            result["results"]["s2"] = True
            result["best_source"] = "s2"
            return result
        else:
            result["results"]["s2"] = False
    except Exception as e:
        result["results"]["s2"] = f"error: {e}"

    time.sleep(0.5)

    # Layer 1b: arXiv API
    try:
        ax = arxiv_src.search_title(http, title)
        if ax and _valid(ax.get("abstract")):
            result["results"]["arxiv"] = True
            result["best_source"] = "arxiv"
            return result
        else:
            result["results"]["arxiv"] = False
    except Exception as e:
        result["results"]["arxiv"] = f"error: {e}"

    time.sleep(0.5)

    # Layer 1c: OpenReview API
    try:
        or_data = or_search_title(http, title)
        if or_data and _valid(or_data.get("abstract")):
            result["results"]["openreview"] = True
            result["best_source"] = "openreview"
            return result
        else:
            result["results"]["openreview"] = False
    except Exception as e:
        result["results"]["openreview"] = f"error: {e}"

    time.sleep(0.5)

    # Layer 3: venue fetcher (curl)
    if venue in VENUE_FETCHERS and url:
        try:
            text = VENUE_FETCHERS[venue](url)
            if _valid(text):
                result["results"][f"venue_{venue.lower()}"] = True
                result["best_source"] = f"venue_{venue.lower()}"
                return result
            else:
                result["results"][f"venue_{venue.lower()}"] = False
        except Exception as e:
            result["results"][f"venue_{venue.lower()}"] = f"error: {e}"
    else:
        result["results"]["venue"] = "no_fetcher"

    result["best_source"] = None
    return result


def main() -> None:
    cfg = load_config()
    db = DB(cfg.abs_path("db"))
    http = httpx.Client(timeout=10, headers={"User-Agent": cfg.network.user_agent})
    s2 = S2Client(api_key=cfg.semantic_scholar_api_key)

    out_dir = Path(__file__).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "probe_report.json"

    combo_results = []
    total_combos = len(COMBOS)

    try:
        for combo_idx, (venue, year) in enumerate(COMBOS, 1):
            print(f"\n[{combo_idx}/{total_combos}] Probing {venue} {year}...", flush=True)

            rows = db._conn.execute("""
                SELECT paper_id, title, url, venue, year
                FROM papers
                WHERE venue = ? AND year = ?
                  AND (abstract IS NULL OR abstract = '' OR LENGTH(abstract) < 30)
                LIMIT 10
            """, (venue, year)).fetchall()

            if not rows:
                print(f"  No papers need abstracts", flush=True)
                continue

            paper_results = []
            for r in rows:
                row = {"paper_id": r[0], "title": r[1], "url": r[2], "venue": r[3], "year": r[4]}
                res = test_paper(s2, http, row)
                paper_results.append(res)
                status = "OK" if res["best_source"] else "FAIL"
                src = res.get("best_source") or "none"
                print(f"  {status}: {res['paper_id'].split('/')[-1]} [{src}]", flush=True)
                time.sleep(2.0)  # rate limit

            ok_count = sum(1 for r in paper_results if r["best_source"])
            source_counts = defaultdict(int)
            for r in paper_results:
                if r["best_source"]:
                    source_counts[r["best_source"]] += 1

            combo_results.append({
                "venue": venue,
                "year": year,
                "tested": len(paper_results),
                "ok": ok_count,
                "rate_pct": round(ok_count / len(paper_results) * 100, 1) if paper_results else 0,
                "by_source": dict(source_counts),
                "papers": paper_results,
            })

            # Incremental save every combo
            report = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "completed_combos": combo_idx,
                "total_combos": total_combos,
                "combos": combo_results,
            }
            out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  -> saved ({combo_idx}/{total_combos})", flush=True)

        print(f"\n\nDone. Report: {out_path}", flush=True)

    finally:
        http.close()
        s2.close()
        db.close()


if __name__ == "__main__":
    main()
