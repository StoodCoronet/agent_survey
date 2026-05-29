"""Stage 8: build citation graph from PDF references.

Scope: core papers only. Extracts references from each PDF,
fuzzy-matches against known core paper titles,
and generates an interactive D3.js graph in docs/citation_graph.html.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from rich.progress import Progress

# Suppress noisy pdfminer font warnings
logging.getLogger("pdfminer").setLevel(logging.ERROR)

from ..core.config import Config
from ..core.console import console
from ..core.db import DB
from ..services.citation_extract import (
    build_citation_graph,
    build_title_signatures,
    extract_references,
    match_citations,
)
from ..services.pdf_extract import extract_text
from ..analysis.stats import write_stage_stats


def _get_references_page_via_bookmarks(pdf_path: Path) -> int | None:
    """Try to find the References page number via PDF bookmarks/outline.

    Returns 0-based page index or None if not found.
    """
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(str(pdf_path))
        outline = reader.outline
        if not outline:
            return None

        def _walk(items, depth=0):
            for item in items:
                if isinstance(item, list):
                    yield from _walk(item, depth + 1)
                else:
                    title = getattr(item, "title", "")
                    if title:
                        yield title, item

        for title, item in _walk(outline):
            lowered = title.lower()
            if "references" in lowered or "bibliography" in lowered:
                try:
                    page_num = reader.get_destination_page_number(item)
                    return page_num
                except Exception:
                    pass
        return None
    except Exception:
        return None


def _extract_references_section(pdf_path: Path) -> str:
    """Extract text from the references section only.

    First tries PDF bookmarks to jump directly to the References page.
    Falls back to front-to-back scan stopping at the first 'References' heading.
    """
    import re
    try:
        import pdfplumber

        # Strategy 1: bookmarks
        ref_page = _get_references_page_via_bookmarks(pdf_path)

        with pdfplumber.open(str(pdf_path)) as pdf:
            total = len(pdf.pages)
            if ref_page is not None and 0 <= ref_page < total:
                parts = []
                for p in range(ref_page, total):
                    try:
                        pt = pdf.pages[p].extract_text() or ""
                    except Exception:
                        pt = ""
                    parts.append(pt)
                return "\n".join(parts)

            # Strategy 2: front-to-back scan
            for page_idx in range(total):
                page = pdf.pages[page_idx]
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if re.search(r"\bReferences?\b|\bREFERENCES?\b|\bBibliography\b", text):
                    parts = []
                    for p in range(page_idx, total):
                        try:
                            pt = pdf.pages[p].extract_text() or ""
                        except Exception:
                            pt = ""
                        parts.append(pt)
                    return "\n".join(parts)

            # Fallback: last 5 pages
            parts = []
            for p in range(max(0, total - 5), total):
                try:
                    pt = pdf.pages[p].extract_text() or ""
                except Exception:
                    pt = ""
                parts.append(pt)
            return "\n".join(parts)
    except Exception:
        return ""


def _generate_html(graph: dict, output_path: Path) -> Path:
    """Generate an interactive D3.js force-directed graph HTML."""
    nodes_json = json.dumps(graph["nodes"], ensure_ascii=False)
    edges_json = json.dumps(graph["edges"], ensure_ascii=False)

    # Color palette for venue areas
    venue_colors = {
        "SE": "#5470c6",
        "Security": "#ee6666",
        "AI": "#91cc75",
        "NLP": "#fac858",
        "HCI": "#73c0de",
    }

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Core Papers Citation Graph</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; }}
  #header {{ padding: 16px 24px; background: #fff; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; }}
  #header h1 {{ margin: 0; font-size: 18px; }}
  #stats {{ color: #666; font-size: 14px; }}
  #graph {{ width: 100vw; height: calc(100vh - 60px); }}
  .tooltip {{
    position: absolute; padding: 10px 14px; background: rgba(0,0,0,0.85);
    color: #fff; border-radius: 6px; font-size: 12px; pointer-events: none;
    max-width: 300px; line-height: 1.5; opacity: 0; transition: opacity 0.15s;
  }}
  .legend {{ display: flex; gap: 16px; font-size: 13px; }}
  .legend-item {{ display: flex; align-items: center; gap: 6px; }}
  .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; }}
  #controls {{ position: absolute; top: 70px; left: 16px; background: #fff; padding: 12px; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); font-size: 13px; }}
  #controls label {{ display: block; margin-bottom: 6px; }}
</style>
</head>
<body>
<div id="header">
  <h1>Core Papers Citation Graph</h1>
  <div id="stats"></div>
  <div class="legend">
    <div class="legend-item"><div class="legend-dot" style="background:#5470c6"></div>SE</div>
    <div class="legend-item"><div class="legend-dot" style="background:#ee6666"></div>Security</div>
    <div class="legend-item"><div class="legend-dot" style="background:#91cc75"></div>AI</div>
    <div class="legend-item"><div class="legend-dot" style="background:#fac858"></div>NLP</div>
    <div class="legend-item"><div class="legend-dot" style="background:#73c0de"></div>HCI</div>
  </div>
</div>
<div id="controls">
  <label><input type="checkbox" id="showLabels" checked> Show labels</label>
  <label><input type="checkbox" id="highlightHighDegree"> Highlight top cited</label>
  <label>Min edges: <input type="range" id="minEdges" min="0" max="10" value="0" style="width:80px"></label>
</div>
<div id="graph"></div>
<div class="tooltip" id="tooltip"></div>

<script>
const nodes = {nodes_json};
const edges = {edges_json};

const venueColors = {json.dumps(venue_colors, ensure_ascii=False)};
const defaultColor = "#999";

const statsEl = document.getElementById("stats");
const maxIn = Math.max(...nodes.map(d => d.in_degree));
const maxOut = Math.max(...nodes.map(d => d.out_degree));
statsEl.textContent = `Nodes: ${{nodes.length}} | Edges: ${{edges.length}} | Max cited: ${{maxIn}} | Max citing: ${{maxOut}}`;

const width = window.innerWidth;
const height = window.innerHeight - 60;

const svg = d3.select("#graph").append("svg")
  .attr("width", width).attr("height", height)
  .call(d3.zoom().on("zoom", (e) => g.attr("transform", e.transform)));

const g = svg.append("g");

// Size scale: sqrt for area-proportional
const sizeScale = d3.scaleSqrt()
  .domain([0, maxIn || 1])
  .range([5, 30]);

const simulation = d3.forceSimulation(nodes)
  .force("link", d3.forceLink(edges).id(d => d.id).distance(120))
  .force("charge", d3.forceManyBody().strength(-200))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collision", d3.forceCollide().radius(d => sizeScale(d.in_degree) + 4));

const link = g.append("g").attr("stroke", "#bbb").attr("stroke-opacity", 0.5)
  .selectAll("line").data(edges).join("line").attr("stroke-width", 1);

const node = g.append("g")
  .selectAll("circle").data(nodes).join("circle")
  .attr("r", d => sizeScale(d.in_degree))
  .attr("fill", d => venueColors[d.venue_area] || defaultColor)
  .attr("stroke", "#fff").attr("stroke-width", 1.5)
  .call(drag(simulation));

const label = g.append("g")
  .selectAll("text").data(nodes).join("text")
  .text(d => d.title.length > 30 ? d.title.slice(0, 28) + "..." : d.title)
  .attr("font-size", 10).attr("fill", "#333")
  .attr("dx", d => sizeScale(d.in_degree) + 3)
  .attr("dy", 3);

const tooltip = d3.select("#tooltip");

node.on("mouseover", (event, d) => {{
  tooltip.style("opacity", 1)
    .html(`<strong>${{d.title}}</strong><br/>Venue: ${{d.venue || "?"}} ${{d.year || ""}}<br/>Cited by: ${{d.in_degree}} | Cites: ${{d.out_degree}}`)
    .style("left", (event.pageX + 12) + "px")
    .style("top", (event.pageY - 12) + "px");
  // highlight neighbors
  const neighbors = new Set(edges.filter(e => e.source.id === d.id || e.target.id === d.id).flatMap(e => [e.source.id, e.target.id]));
  node.attr("opacity", n => neighbors.has(n.id) ? 1 : 0.15);
  link.attr("stroke-opacity", l => (l.source.id === d.id || l.target.id === d.id) ? 1 : 0.05);
  label.attr("opacity", n => neighbors.has(n.id) ? 1 : 0.1);
}})
.on("mouseout", () => {{
  tooltip.style("opacity", 0);
  node.attr("opacity", 1);
  link.attr("stroke-opacity", 0.5);
  label.attr("opacity", 1);
}});

simulation.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("cx", d => d.x).attr("cy", d => d.y);
  label.attr("x", d => d.x).attr("y", d => d.y);
}});

function drag(sim) {{
  return d3.drag()
    .on("start", (event, d) => {{ if (!event.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on("drag", (event, d) => {{ d.fx = event.x; d.fy = event.y; }})
    .on("end", (event, d) => {{ if (!event.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }});
}}

// Controls
document.getElementById("showLabels").addEventListener("change", (e) => {{
  label.attr("display", e.target.checked ? null : "none");
}});

let highlightOn = false;
document.getElementById("highlightHighDegree").addEventListener("change", (e) => {{
  highlightOn = e.target.checked;
  const threshold = maxIn > 0 ? Math.ceil(maxIn * 0.3) : 0;
  node.attr("stroke", d => highlightOn && d.in_degree >= threshold ? "#ff5722" : "#fff")
      .attr("stroke-width", d => highlightOn && d.in_degree >= threshold ? 3 : 1.5);
}});

document.getElementById("minEdges").addEventListener("input", (e) => {{
  const min = +e.target.value;
  node.attr("display", d => (d.in_degree + d.out_degree) >= min ? null : "none");
  label.attr("display", d => (d.in_degree + d.out_degree) >= min ? null : "none");
  link.attr("display", d => (d.source.in_degree + d.source.out_degree) >= min && (d.target.in_degree + d.target.out_degree) >= min ? null : "none");
}});
</script>
</body>
</html>
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path


def run(
    cfg: Config,
    *,
    force: bool = False,
    scope: str = "core",
) -> dict:
    db = DB(cfg.abs_path("db"))
    try:
        # Reset papers that were previously saved with zero refs (likely parse failures)
        # so they get another chance on the next run.
        reset_sql = """
            UPDATE papers
            SET citation_json = NULL
            WHERE relevance = ?
              AND citation_json IS NOT NULL
              AND citation_json LIKE '%"extracted_refs_count": 0%'
        """
        db._conn.execute(reset_sql, (scope,))
        db._conn.commit()

        where = f"relevance = '{scope}' AND pdf_path IS NOT NULL AND pdf_path != ''"
        if not force:
            where += " AND (citation_json IS NULL OR citation_json = '' OR citation_json = '{}')"

        rows = [r for r in db.iter_papers(where)]
        if not rows:
            console.print(f"[yellow]no core papers with PDF left to process[/yellow]")
            return {"processed": 0}

        console.print(f"[bold]Building citation graph for {len(rows)} {scope} papers...[/bold]")

        # Build signatures from ALL core papers (for matching)
        all_core = [r for r in db.iter_papers(f"relevance = '{scope}'")]
        signatures = build_title_signatures(all_core)

        processed = 0
        skipped = 0
        failed = 0

        with Progress(console=console) as prog:
            task = prog.add_task("extracting citations", total=len(rows))
            for idx, r in enumerate(rows, 1):
                pid = r["paper_id"]
                title_short = r.get("title", "")[:40]
                pdf_path = r.get("pdf_path")
                prog.update(task, description=f"[{idx}/{len(rows)}] {title_short}")
                if not pdf_path or not Path(pdf_path).exists():
                    failed += 1
                    prog.advance(task)
                    continue

                text = _extract_references_section(Path(pdf_path))
                refs = extract_references(text)

                # If we got no text at all, treat as parse failure and leave for retry.
                if not text.strip() or (len(refs) == 0 and len(text.strip()) < 200):
                    failed += 1
                    prog.advance(task)
                    continue

                cited_ids = match_citations(refs, signatures)
                cited_ids = list(dict.fromkeys(cited_ids))
                # Only keep citations to other core papers
                cited_ids = [cid for cid in cited_ids if cid != pid]

                citation_data = {
                    "cited_paper_ids": cited_ids,
                    "extracted_refs_count": len(refs),
                    "matched_count": len(cited_ids),
                }
                db.update_paper(pid, {"citation_json": citation_data})
                db.mark_stage(pid, "citation", "done")
                processed += 1
                prog.advance(task)

        # Build graph from all processed papers
        all_processed = [
            r for r in db.iter_papers(f"relevance = '{scope}' AND citation_json IS NOT NULL AND citation_json != ''")
        ]
        graph = build_citation_graph(all_processed, signatures)

        # Write HTML
        html_path = cfg.project_root / "docs" / "citation_graph.html"
        _generate_html(graph, html_path)
        console.print(f"[green]wrote citation graph to {html_path}[/green]")

        # Stats
        in_degrees = [n["in_degree"] for n in graph["nodes"]]
        out_degrees = [n["out_degree"] for n in graph["nodes"]]
        console.print(
            f"[bold]Graph stats:[/bold] nodes={len(graph['nodes'])}, edges={len(graph['edges'])}, "
            f"max_in={max(in_degrees) if in_degrees else 0}, max_out={max(out_degrees) if out_degrees else 0}"
        )

        stats = {
            "scope": scope,
            "processed": processed,
            "skipped": skipped,
            "failed": failed,
            "nodes": len(graph["nodes"]),
            "edges": len(graph["edges"]),
        }
        out = write_stage_stats(cfg, "citation_graph", stats)
        console.print(f"[green]wrote stats to {out}[/green]")
        return stats
    finally:
        db.close()
