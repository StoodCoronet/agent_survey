"""Test enrich pipeline on 10 papers per venue+year combo.

Outputs a JSON report showing per-combo abstract fetch success rates,
which sources worked, and which combos need new venue-specific strategies.

Runs serially to avoid thread-deadlock issues with long HTTP timeouts.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from agent_survey.core.config import load_config
from agent_survey.core.db import DB
from agent_survey.services.s2 import S2Client
from agent_survey.services import arxiv as arxiv_src
from agent_survey.services.openreview import search_title as or_search_title
from agent_survey.stages.s01_enrich.strategies import VENUE_FETCHERS


def _valid(text: str | None) -> bool:
    return bool(text) and len(text.strip()) >= 30


def _is_proceedings(paper_id: str) -> bool:
    """Heuristic: paper IDs like dblp:conf/aaai/2023 or dblp:conf/aaai/2023bridge
    are proceedings/workshop volumes, not actual papers."""
    pid = paper_id.split("/")[-1] if "/" in paper_id else paper_id
    import re
    if re.fullmatch(r"\d{4}", pid):
        return True
    if re.fullmatch(r"\d{4}[a-z]+", pid):
        return True
    return False


def test_paper(http: httpx.Client, s2: S2Client, row: dict) -> dict:
    """Test all sources for a single paper serially. Returns result dict."""
    title = row.get("title") or ""
    venue = row.get("venue") or ""
    url = row.get("url")
    results = {
        "paper_id": row["paper_id"],
        "title": title[:80],
        "venue": venue,
        "year": row.get("year"),
        "url": url,
        "sources": {},
        "is_proceedings": _is_proceedings(row["paper_id"]),
    }

    if results["is_proceedings"]:
        results["any_ok"] = False
        results["sources"]["skip"] = {"ok": False, "reason": "proceedings_volume"}
        return results

    # Try S2 first
    try:
        data = s2.search_by_title(title)
        if data and _valid(data.get("abstract")):
            results["sources"]["s2"] = {"ok": True, "abstract_len": len(data["abstract"])}
            results["any_ok"] = True
            return results
        else:
            results["sources"]["s2"] = {"ok": False, "reason": "no_result"}
    except Exception as e:
        results["sources"]["s2"] = {"ok": False, "reason": f"error: {e}"}

    # Try arXiv
    try:
        ax = arxiv_src.search_title(http, title)
        if ax and _valid(ax.get("abstract")):
            results["sources"]["arxiv"] = {"ok": True, "abstract_len": len(ax["abstract"])}
            results["any_ok"] = True
            return results
        else:
            results["sources"]["arxiv"] = {"ok": False, "reason": "no_result"}
    except Exception as e:
        results["sources"]["arxiv"] = {"ok": False, "reason": f"error: {e}"}

    # Try OpenReview
    try:
        or_data = or_search_title(http, title)
        if or_data and _valid(or_data.get("abstract")):
            results["sources"]["openreview"] = {"ok": True, "abstract_len": len(or_data["abstract"])}
            results["any_ok"] = True
            return results
        else:
            results["sources"]["openreview"] = {"ok": False, "reason": "no_result"}
    except Exception as e:
        results["sources"]["openreview"] = {"ok": False, "reason": f"error: {e}"}

    # Try venue-specific fetcher
    if venue in VENUE_FETCHERS and url:
        try:
            text = VENUE_FETCHERS[venue](url)
            if _valid(text):
                results["sources"][f"venue_{venue.lower()}"] = {"ok": True, "abstract_len": len(text)}
                results["any_ok"] = True
                return results
            else:
                results["sources"][f"venue_{venue.lower()}"] = {"ok": False, "reason": "no_result"}
        except Exception as e:
            results["sources"][f"venue_{venue.lower()}"] = {"ok": False, "reason": f"error: {e}"}

    results["any_ok"] = False
    return results


def main() -> None:
    cfg = load_config()
    db = DB(cfg.abs_path("db"))
    http = httpx.Client(
        timeout=cfg.network.request_timeout,
        headers={"User-Agent": cfg.network.user_agent},
    )
    s2 = S2Client(api_key=cfg.semantic_scholar_api_key)

    try:
        rows = db._conn.execute("""
            SELECT venue, year, paper_id, title, url
            FROM papers
            WHERE (abstract IS NULL OR abstract = '')
              AND venue IS NOT NULL AND venue != ''
            ORDER BY venue, year, paper_id
        """).fetchall()

        combo_papers_all: dict[tuple[str, int], list[dict]] = defaultdict(list)
        for r in rows:
            venue, year, pid, title, url = r
            key = (venue, year)
            if len(combo_papers_all[key]) < 10:
                combo_papers_all[key].append({"paper_id": pid, "title": title, "venue": venue, "year": year, "url": url})

        combo_order = sorted(combo_papers_all.keys(), key=lambda k: len(combo_papers_all[k]), reverse=True)[:20]
        combo_papers = {k: combo_papers_all[k] for k in combo_order}

        print(f"Testing {len(combo_papers)} venue+year combos ({sum(len(v) for v in combo_papers.values())} papers total)", flush=True)

        combo_results = []
        out_path = cfg.project_root / "output" / "enrich_venue_test.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        for idx, ((venue, year), papers) in enumerate(sorted(combo_papers.items()), 1):
            print(f"\n[{idx}/{len(combo_papers)}] Testing {venue} {year} ({len(papers)} papers)...", flush=True)
            paper_results = []
            for p in papers:
                res = test_paper(http, s2, p)
                paper_results.append(res)
                ok_sources = [k for k, v in res["sources"].items() if v["ok"]]
                skip = " (proceedings)" if res.get("is_proceedings") else ""
                print(f"    {res['paper_id']}: {'OK' if res['any_ok'] else 'FAIL'}{skip} ({', '.join(ok_sources) if ok_sources else 'none'})", flush=True)

            real_papers = [r for r in paper_results if not r.get("is_proceedings")]
            ok_count = sum(1 for r in real_papers if r["any_ok"])
            source_counts = defaultdict(int)
            for r in paper_results:
                for src, info in r["sources"].items():
                    if info["ok"]:
                        source_counts[src] += 1

            combo_results.append({
                "venue": venue,
                "year": year,
                "tested": len(papers),
                "real_papers": len(real_papers),
                "ok": ok_count,
                "rate_pct": round(ok_count / len(real_papers) * 100, 1) if real_papers else 0,
                "by_source": dict(source_counts),
                "papers": paper_results,
            })

            if idx % 5 == 0 or idx == len(combo_papers):
                report = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "total_combos": len(combo_results),
                    "summary": {
                        "total_tested": sum(c["tested"] for c in combo_results),
                        "total_ok": sum(c["ok"] for c in combo_results),
                        "zero_coverage_combos": [f"{c['venue']} {c['year']}" for c in combo_results if c["ok"] == 0],
                        "low_coverage_combos": [f"{c['venue']} {c['year']} ({c['rate_pct']}%)" for c in combo_results if 0 < c["rate_pct"] < 50],
                    },
                    "combos": combo_results,
                }
                out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"  -> incremental report saved ({idx}/{len(combo_papers)} combos)", flush=True)

        print(f"\n\nReport written to {out_path}", flush=True)

        print("\n=== Venue+Year Coverage Summary ===", flush=True)
        print(f"{'Venue':<20} {'Year':<6} {'Tested':<8} {'Real':<8} {'OK':<8} {'Rate':<8} {'Best Source':<15}", flush=True)
        print("-" * 70, flush=True)
        for c in combo_results:
            best_src = max(c["by_source"], key=c["by_source"].get) if c["by_source"] else "-"
            print(f"{c['venue']:<20} {c['year']:<6} {c['tested']:<8} {c['real_papers']:<8} {c['ok']:<8} {c['rate_pct']:<8.1f} {best_src:<15}", flush=True)

    finally:
        http.close()
        s2.close()
        db.close()


if __name__ == "__main__":
    main()
