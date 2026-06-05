"""Harvest core utilities and per-venue fetch worker."""
from __future__ import annotations

import traceback
from typing import Any

import httpx
from tenacity import RetryError

from ...core.config import Config, VenueCfg
from ...core.console import console
from ...core.db import DB
from ...services import dblp as dblp


def unwrap_error(exc: BaseException) -> BaseException:
    if isinstance(exc, RetryError) and exc.last_attempt is not None:
        try:
            return exc.last_attempt.exception() or exc
        except Exception:
            return exc
    return exc


def format_error(err: BaseException) -> tuple[str, str]:
    inner = unwrap_error(err)
    short = f"{type(err).__name__} → {type(inner).__name__}: {inner}"

    lines: list[str] = [f"outer: {type(err).__name__}: {err!r}"]
    if inner is not err:
        lines.append(f"inner: {type(inner).__name__}: {inner!r}")

    # httpx exceptions use properties that raise RuntimeError if unset;
    # getattr() does not catch that, so we use try/except.
    req = None
    try:
        req = inner.request
    except Exception:
        pass
    if req is not None:
        try:
            lines.append(f"url   : {req.method} {req.url}")
        except Exception:
            pass
    resp = None
    try:
        resp = inner.response
    except Exception:
        pass
    if resp is not None:
        try:
            body = resp.text[:300].replace("\n", " ")
            lines.append(f"status: {resp.status_code}")
            lines.append(f"body  : {body}")
        except Exception:
            pass

    tb = "".join(
        traceback.format_exception(type(inner), inner, inner.__traceback__)
    ).rstrip()
    if tb and tb != f"{type(inner).__name__}: {inner}":
        lines.append("traceback:")
        lines.append(tb)

    return short, "\n".join(lines)


# ── TOC stream derivation ─────────────────────────────────────────

def _get_strategy(vc: VenueCfg) -> tuple[str, int] | None:
    """Look up harvest strategy (toc_stream, volumes) for a venue."""
    from ...services.harvest_strategies import get_strategy as _get_strat

    return _get_strat(vc.name, vc.key_prefixes)


# ── XML TOC (primary harvest method) ──────────────────────────────


_VENUE_TIMEOUT = 20  # seconds per (venue, year) combo (informational only)


def _fetch_one(args: tuple[str, Any, int], cfg: Config) -> tuple[Any, int, list[dict], BaseException | None]:
    """Inner fetch without timeout wrapping."""
    vtype, vc, year = args
    client = httpx.Client(
        timeout=cfg.network.request_timeout,
        headers={"User-Agent": cfg.network.user_agent, "Accept": "application/json"},
        proxy=cfg.http_proxy or None,
    )
    try:
        if year in vc.skip_years:
            papers: list[dict] = []
        elif vc.json_source_url:
            url = vc.json_source_url.format(year=year)
            from agent_survey.services import external

            papers = list(
                external.fetch_json_papers(
                    url, year,
                    venue_name=vc.name, venue_area=vc.area,
                    venue_type=vtype, client=client,
                )
            )
        elif vc.journal_stream:
            vols = vc.journal_volumes.get(year, [])
            papers = list(
                dblp.fetch_journal_volumes(
                    vc.journal_stream, vols, year,
                    venue_name=vc.name, venue_area=vc.area,
                    venue_type=vtype, client=client,
                )
            )
        elif vc.toc_stream:
            papers = list(
                dblp.fetch_toc_xml(
                    vc.toc_stream, year,
                    venue_name=vc.name, venue_area=vc.area,
                    venue_type=vtype, client=client,
                )
            )
        else:
            # ── Adaptive fetch: Search API → XML TOC ───────────────
            papers = _fetch_adaptive(vc, year, vtype, client, cfg)

        return vc, year, papers, None
    except Exception as e:
        return vc, year, [], e
    finally:
        client.close()


def fetch_venue_year(
    args: tuple[str, Any, int], cfg: Config
) -> tuple[Any, int, list[dict], BaseException | None]:
    """Fetch papers for one (venue_type, venue_cfg, year) combination.

    Single-threaded: runs directly on the calling thread.
    Per-request timeouts (curl --max-time 5s, retry 3×) keep each
    venue-year under ~20 s without spawning background threads.

    Returns (vc, year, papers, error).
    """
    import time as _t
    vtype, vc, year = args
    t0 = _t.time()
    result = _fetch_one(args, cfg)
    elapsed = _t.time() - t0
    if elapsed > _VENUE_TIMEOUT:
        console.log(f"[yellow]{vc.name} {year}: slow ({elapsed:.1f}s > {_VENUE_TIMEOUT}s) but finished[/yellow]")
    return result


def _fetch_adaptive(
    vc: VenueCfg, year: int, vtype: str, client: httpx.Client, cfg: Config,
) -> list[dict]:
    """Fetch papers via per-venue harvest strategy.

    Priority: Playwright (last resort venues) > XML TOC (normal flow).
    """
    import time as _t
    t0 = _t.time()

    # ── Step 1: Direct Playwright for venues DBLP hasn't indexed ──
    from .strategies import VENUE_PLAYWRIGHT_URLS
    from .strategies.playwright_fetcher import fetch_papers

    pw_urls = VENUE_PLAYWRIGHT_URLS.get(vc.name, {})
    pw_url = pw_urls.get(year)
    if pw_url:
        console.log(f"[cyan]{vc.name} {year}: direct Playwright ({pw_url})[/cyan]")
        try:
            pw_papers = list(fetch_papers(
                pw_url,
                proxy=cfg.http_proxy or "",
                venue_name=vc.name, venue_area=vc.area, venue_type=vtype, year=year,
                timeout=60,
            ))
            if pw_papers:
                console.log(
                    f"[dim]{vc.name} {year}: {len(pw_papers)} papers via Playwright in {_t.time()-t0:.1f}s[/dim]"
                )
                return pw_papers
            console.log(f"[yellow]{vc.name} {year}: Playwright found no papers[/yellow]")
        except Exception as e:
            console.log(f"[red]{vc.name} {year}: Playwright failed: {e}[/red]")

    # ── Step 2: XML TOC (primary method for indexed venues) ─────
    strat = _get_strategy(vc)
    if not strat:
        console.log(f"[yellow]{vc.name} {year}: no harvest strategy, returning empty[/yellow]")
        return []

    toc_stream, volumes = strat

    papers: list[dict] = []
    papers.extend(dblp.fetch_toc_xml(
        toc_stream, year, year_suffix="",
        venue_name=vc.name, venue_area=vc.area, venue_type=vtype,
        client=client,
    ))
    for v in range(1, volumes + 1):
        if papers:
            break
        papers.extend(dblp.fetch_toc_xml(
            toc_stream, year, year_suffix=f"-{v}",
            venue_name=vc.name, venue_area=vc.area, venue_type=vtype,
            client=client,
        ))

    if papers:
        console.log(f"[dim]{vc.name} {year}: {len(papers)} papers via TOC in {_t.time()-t0:.1f}s[/dim]")
    else:
        console.log(f"[yellow]{vc.name} {year}: TOC empty (no papers)[/yellow]")
    return papers
