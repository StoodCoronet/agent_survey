"""Generate docs/ static site from DB data."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_survey.core.config import load_config
from agent_survey.core.db import DB


def _build_tree_hierarchy(tree_papers_flat: dict[str, list[str]]) -> list[dict]:
    """Convert flat {path: [pids]} dict to hierarchical tree."""
    root: dict[str, dict] = {}

    for path, pids in tree_papers_flat.items():
        parts = path.split("/")
        node = root
        for part in parts:
            if part not in node:
                node[part] = {"children": {}, "papers": set()}
            node[part]["papers"].update(pids)
            node = node[part]["children"]

    def _to_list(d: dict) -> list[dict]:
        result = []
        for name, data in d.items():
            children = _to_list(data["children"])
            result.append({
                "name": name,
                "count": len(data["papers"]),
                "papers": list(data["papers"]) if not children else [],
                "children": children,
            })
        return sorted(result, key=lambda x: -x["count"])

    return _to_list(root)


def main():
    cfg = load_config()
    db = DB(cfg.abs_path("db"))
    docs_dir = cfg.project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    papers = []
    for r in db.iter_papers("relevance = 'core'"):
        tax = {}
        if r.get("taxonomy_json"):
            try:
                tax = json.loads(r["taxonomy_json"])
            except Exception:
                pass
        cit = {}
        if r.get("citation_json"):
            try:
                cit = json.loads(r["citation_json"])
            except Exception:
                pass
        short = r.get("short_title") or ""
        if not short:
            t = r["title"]
            short = t if len(t) <= 40 else t[:38] + "..."
        pdf_url = ""
        if r.get("pdf_url"):
            pdf_url = r["pdf_url"]
        elif r.get("pdf_path"):
            pdf_url = "./pdfs/" + Path(r["pdf_path"]).name
        papers.append({
            "id": r["paper_id"],
            "title": r["title"],
            "short_title": short,
            "venue": r.get("venue", ""),
            "year": r.get("year"),
            "venue_area": r.get("venue_area", ""),
            "abstract": r.get("abstract", "") or "",
            "summary_en": r.get("summary_en", "") or "",
            "summary_zh": r.get("summary_zh", "") or "",
            "taxonomy": tax,
            "citation": cit,
            "has_pdf": bool(r.get("pdf_path")),
            "pdf_url": pdf_url,
        })

    # Build tree structures (flat for index, hierarchy for taxonomy page)
    tree_papers_flat = defaultdict(lambda: defaultdict(list))
    cross_counts = Counter()
    for p in papers:
        for tree, paths in p["taxonomy"].items():
            if isinstance(paths, list):
                for path in paths:
                    tree_papers_flat[tree][path].append(p["id"])
        for tag in p["taxonomy"].get("cross_cutting", []):
            cross_counts[tag] += 1

    tree_hierarchy = {}
    for tree_name, paths in tree_papers_flat.items():
        tree_hierarchy[tree_name] = _build_tree_hierarchy(paths)

    # Assign 1-based paper numbers
    for i, p in enumerate(papers, 1):
        p["num"] = i

    # Build citation edges from citation_json
    edges = []
    node_ids = {p["id"] for p in papers}
    for p in papers:
        cited = p["citation"].get("cited_paper_ids", [])
        for cid in cited:
            if cid in node_ids and cid != p["id"]:
                edges.append({"source": p["id"], "target": cid})

    in_degree = Counter(e["target"] for e in edges)
    out_degree = Counter(e["source"] for e in edges)

    nodes = []
    for p in papers:
        nodes.append({
            "id": p["id"],
            "title": p["title"],
            "short_title": p["short_title"],
            "venue": p["venue"],
            "year": p["year"],
            "venue_area": p["venue_area"] or _infer_area(p["venue"]),
            "in_degree": in_degree.get(p["id"], 0),
            "out_degree": out_degree.get(p["id"], 0),
        })

    # taxonomy descriptions
    taxonomy_descs = {}
    for row in db.iter_taxonomy_descs():
        key = f"{row['tree_name']}:{row['path']}"
        meta = {}
        if row.get("metadata_json"):
            try:
                meta = json.loads(row["metadata_json"])
            except Exception:
                pass
        taxonomy_descs[key] = {
            "en": row.get("desc_en", ""),
            "zh": row.get("desc_zh", ""),
            "metadata": meta,
        }

    data = {
        "papers": papers,
        "tree_papers": {t: {p: pids for p, pids in paths.items()} for t, paths in tree_papers_flat.items()},
        "tree_hierarchy": tree_hierarchy,
        "cross_counts": dict(cross_counts),
        "taxonomy_desc": taxonomy_descs,
        "graph": {"nodes": nodes, "edges": edges},
        "stats": {
            "total": len(papers),
            "with_taxonomy": sum(1 for p in papers if p["taxonomy"]),
            "with_citation": sum(1 for p in papers if p["citation"]),
            "with_pdf": sum(1 for p in papers if p["has_pdf"]),
        },
    }

    (docs_dir / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"[green]wrote data.json ({len(papers)} papers)[/green]")

    _sync_pdfs(docs_dir, cfg, db)
    _write_index(docs_dir)
    _write_taxonomy(docs_dir)
    _write_mindmap(docs_dir)
    _write_papers(docs_dir)
    _write_citation(docs_dir)

    db.close()
    print(f"[green]docs generated in {docs_dir}[/green]")


def _sync_pdfs(docs_dir: Path, cfg, db) -> None:
    """Copy local PDFs from output/pdfs/ to docs/pdfs/ so they are served with the static site."""
    import shutil
    src_dir = cfg.abs_path("pdfs")
    dst_dir = docs_dir / "pdfs"
    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for r in db.iter_papers("relevance = 'core'"):
        pdf_path = r.get("pdf_path")
        if not pdf_path:
            continue
        src = Path(pdf_path)
        if not src.exists():
            # fallback to src_dir / filename if absolute path is stale
            src = src_dir / src.name
            if not src.exists():
                continue
        dst = dst_dir / src.name
        if not dst.exists():
            shutil.copy2(str(src), str(dst))
            copied += 1
    if copied:
        print(f"[green]synced {copied} PDFs to {dst_dir}[/green]")


def _infer_area(venue: str) -> str:
    v = venue.upper()
    if v in {"ICSE", "ASE", "FSE", "TSE", "TOSEM", "ISSTA"}:
        return "SE"
    if v in {"SP", "CCS", "USS", "NDSS"}:
        return "Security"
    if v in {"ICLR", "NeurIPS", "ICML", "AAAI"}:
        return "AI"
    if v in {"ACL", "EMNLP", "NAACL", "COLM"}:
        return "NLP"
    if v in {"CHI", "UIST"}:
        return "HCI"
    return "Other"


def _write_index(docs_dir: Path) -> None:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Agent Survey Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; }
  .header { background: #fff; padding: 20px 24px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 20px; }
  .nav { display: flex; gap: 8px; }
  .nav a { padding: 6px 14px; border-radius: 6px; text-decoration: none; color: #333; font-size: 14px; background: #f0f0f0; }
  .nav a:hover { background: #e0e0e0; }
  .nav a.active { background: #333; color: #fff; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .stat-card { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .stat-card .num { font-size: 32px; font-weight: 700; color: #1a1a1a; }
  .stat-card .label { font-size: 13px; color: #666; margin-top: 4px; }
  .section { background: #fff; padding: 20px; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); margin-bottom: 16px; }
  .section h2 { font-size: 16px; margin-bottom: 12px; }
  .bar { display: flex; align-items: center; margin-bottom: 8px; }
  .bar-name { width: 300px; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bar-track { flex: 1; height: 20px; background: #f0f0f0; border-radius: 4px; overflow: hidden; position: relative; }
  .bar-fill { height: 100%; border-radius: 4px; }
  .bar-val { margin-left: 8px; font-size: 12px; color: #666; min-width: 30px; }
  .color-se { background: #5470c6; }
  .color-security { background: #ee6666; }
  .color-ai { background: #91cc75; }
  .color-nlp { background: #fac858; }
  .color-hci { background: #73c0de; }
  .color-default { background: #999; }
</style>
</head>
<body>
<div class="header">
  <h1>Agent Survey Dashboard</h1>
  <div class="nav">
    <a href="index.html" class="active">Overview</a>
    <a href="taxonomy.html">Taxonomy</a>
    <a href="mindmap.html">Mindmap</a>
    <a href="papers.html">Papers</a>
    <a href="citation_graph.html">Citation Graph</a>
  </div>
</div>
<div class="container">
  <div class="stats-grid" id="stats"></div>
  <div class="section">
    <h2>Application Domain</h2>
    <div id="app-domain"></div>
  </div>
  <div class="section">
    <h2>Technical Approach</h2>
    <div id="tech-approach"></div>
  </div>
  <div class="section">
    <h2>Research Goal</h2>
    <div id="research-goal"></div>
  </div>
  <div class="section">
    <h2>Cross-cutting Tags</h2>
    <div id="cross-tags"></div>
  </div>
</div>
<script>
async function load() {
  const res = await fetch('data.json?v=' + Date.now());
  const data = await res.json();
  const stats = data.stats;
  document.getElementById('stats').innerHTML = `
    <div class="stat-card"><div class="num">${stats.total}</div><div class="label">Core Papers</div></div>
    <div class="stat-card"><div class="num">${stats.with_taxonomy}</div><div class="label">With Taxonomy</div></div>
    <div class="stat-card"><div class="num">${stats.with_citation}</div><div class="label">With Citation</div></div>
    <div class="stat-card"><div class="num">${stats.with_pdf}</div><div class="label">With PDF</div></div>
    <div class="stat-card"><div class="num">${data.graph.edges.length}</div><div class="label">Citation Edges</div></div>
  `;

  function renderBars(containerId, items, max) {
    const el = document.getElementById(containerId);
    el.innerHTML = items.map(([name, count]) => `
      <div class="bar">
        <div class="bar-name" title="${name}">${name}</div>
        <div class="bar-track"><div class="bar-fill color-default" style="width:${(count/max*100).toFixed(1)}%"></div></div>
        <div class="bar-val">${count}</div>
      </div>
    `).join('');
  }

  const tp = data.tree_papers;
  const maxApp = Math.max(...Object.values(tp['application_domain'] || {}).map(x => x.length), 1);
  const maxTech = Math.max(...Object.values(tp['technical_approach'] || {}).map(x => x.length), 1);
  const maxGoal = Math.max(...Object.values(tp['research_goal'] || {}).map(x => x.length), 1);
  const maxCross = Math.max(...Object.values(data.cross_counts || {}), 1);

  renderBars('app-domain', Object.entries(tp['application_domain'] || {}).map(([k,v])=>[k,v.length]).sort((a,b)=>b[1]-a[1]).slice(0,20), maxApp);
  renderBars('tech-approach', Object.entries(tp['technical_approach'] || {}).map(([k,v])=>[k,v.length]).sort((a,b)=>b[1]-a[1]).slice(0,20), maxTech);
  renderBars('research-goal', Object.entries(tp['research_goal'] || {}).map(([k,v])=>[k,v.length]).sort((a,b)=>b[1]-a[1]).slice(0,20), maxGoal);
  renderBars('cross-tags', Object.entries(data.cross_counts || {}).sort((a,b)=>b[1]-a[1]), maxCross);
}
load();
</script>
</body>
</html>"""
    (docs_dir / "index.html").write_text(html, encoding="utf-8")


def _write_taxonomy(docs_dir: Path) -> None:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Taxonomy Mind Map - Agent Survey</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
  .header { background: #fff; padding: 14px 24px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; }
  .header h1 { font-size: 18px; }
  .nav { display: flex; gap: 8px; }
  .nav a { padding: 6px 14px; border-radius: 6px; text-decoration: none; color: #333; font-size: 14px; background: #f0f0f0; }
  .nav a:hover { background: #e0e0e0; }
  .nav a.active { background: #333; color: #fff; }
  .tree-tabs { display: flex; gap: 8px; padding: 10px 24px; background: #fff; border-bottom: 1px solid #e8e8e8; flex-shrink: 0; }
  .tree-tab { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; background: #e8e8e8; font-size: 14px; }
  .tree-tab.active { background: #333; color: #fff; }

  .main-layout { display: flex; flex: 1; overflow: hidden; }

  /* Resize handles */
  .resize-handle { width: 4px; background: transparent; cursor: col-resize; flex-shrink: 0; position: relative; z-index: 10; }
  .resize-handle::after { content: ''; position: absolute; left: 1px; top: 0; bottom: 0; width: 1px; background: #e0e0e0; }
  .resize-handle:hover::after { background: #bbb; }

  /* Left sidebar: tree navigation */
  .left-sidebar { width: 280px; background: #fff; border-right: 1px solid #e0e0e0; overflow-y: auto; padding: 12px 0; flex-shrink: 0; }
  .tree-nav ul { list-style: none; padding-left: 0; }
  .tree-nav li { position: relative; }
  .tree-nav .node-line { display: flex; align-items: center; padding: 5px 16px 5px 12px; cursor: pointer; font-size: 13px; gap: 6px; border-left: 3px solid transparent; }
  .tree-nav .node-line:hover { background: #f5f5f5; }
  .tree-nav .node-line.active { background: #f0f0f0; border-left-color: #333; font-weight: 600; }
  .tree-nav .node-line .count { margin-left: auto; background: #eee; padding: 1px 6px; border-radius: 10px; font-size: 11px; color: #666; }
  .tree-nav .node-line .expand-btn { width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; font-size: 10px; color: #999; cursor: pointer; border-radius: 3px; }
  .tree-nav .node-line .expand-btn:hover { background: #e0e0e0; }
  .tree-nav .children { display: none; }
  .tree-nav .children.open { display: block; }
  .tree-nav .children ul { padding-left: 16px; }

  /* Center: mind map cards */
  .center-panel { flex: 1; overflow-y: auto; background: #fafafa; padding: 24px; position: relative; }
  .breadcrumb { font-size: 13px; color: #666; margin-bottom: 16px; }
  .breadcrumb span { cursor: pointer; }
  .breadcrumb span:hover { text-decoration: underline; }
  .breadcrumb .sep { margin: 0 6px; color: #ccc; }
  .current-node-card { background: #fff; border-radius: 10px; padding: 16px 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); margin-bottom: 20px; border-left: 4px solid #333; }
  .current-node-card h2 { font-size: 18px; margin-bottom: 4px; }
  .current-node-card .meta { color: #999; font-size: 13px; }
  .sub-nodes { display: flex; flex-wrap: wrap; gap: 12px; }
  .sub-card { background: #fff; border-radius: 8px; padding: 12px 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); cursor: pointer; min-width: 140px; max-width: 220px; border-top: 3px solid #5470c6; transition: transform 0.15s, box-shadow 0.15s; }
  .sub-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
  .sub-card .name { font-size: 14px; font-weight: 600; margin-bottom: 4px; }
  .sub-card .count { font-size: 12px; color: #999; }
  .sub-card .mini-papers { margin-top: 8px; padding-top: 8px; border-top: 1px solid #f0f0f0; font-size: 11px; color: #666; line-height: 1.6; }

  .paper-card { background: #fff; border-radius: 8px; padding: 10px 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); cursor: default; min-width: 180px; max-width: 260px; border-left: 3px solid #888; transition: transform 0.15s, box-shadow 0.15s; }
  .paper-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
  .paper-card .p-num { font-weight: 700; color: #333; font-size: 12px; margin-bottom: 4px; }
  .paper-card .p-title { font-size: 13px; font-weight: 500; color: #333; line-height: 1.4; margin-bottom: 4px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .paper-card .p-meta { font-size: 11px; color: #999; }

  /* Right sidebar: paper list */
  .right-panel { width: 340px; background: #fff; display: flex; flex-direction: column; flex-shrink: 0; }
  .right-header { padding: 12px 16px; border-bottom: 1px solid #f0f0f0; font-size: 14px; font-weight: 600; display: flex; justify-content: space-between; align-items: center; }
  .right-list { flex: 1; overflow-y: auto; padding: 8px 16px; }
  .right-item { background: #fff; border-radius: 6px; padding: 8px 10px; margin-bottom: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); display: flex; gap: 8px; align-items: baseline; border-left: 2px solid #ccc; }
  .right-num { font-weight: 700; color: #333; min-width: 32px; font-size: 12px; }
  .right-title { color: #333; line-height: 1.4; }
  .right-venue { color: #aaa; font-size: 11px; white-space: nowrap; margin-left: auto; padding-left: 8px; }
  .right-empty { color: #999; font-size: 13px; padding: 16px 0; }

  .color-domain { border-top-color: #1565c0 !important; }
  .color-tech { border-top-color: #2e7d32 !important; }
  .color-goal { border-top-color: #ef6c00 !important; }
  .color-cross { border-top-color: #c2185b !important; }

  .right-detail { flex: 1; overflow-y: auto; padding: 12px 16px; }
  .detail-num { color: #666; font-size: 13px; margin-bottom: 4px; }
  .detail-title { font-size: 15px; font-weight: 600; color: #333; line-height: 1.4; margin-bottom: 8px; }
  .detail-meta { font-size: 12px; color: #999; margin-bottom: 16px; }
  .detail-abstract { font-size: 13px; line-height: 1.7; color: #333; max-height: 300px; overflow-y: auto; padding-right: 4px; margin-bottom: 16px; }
  .detail-cn { background: #f5f5f5; border-radius: 6px; padding: 10px 12px; font-size: 12px; color: #888; margin-bottom: 16px; }
  .detail-pdf a { font-size: 13px; color: #1565c0; text-decoration: none; }
  .detail-pdf a:hover { text-decoration: underline; }
  .close-btn { width: 24px; height: 24px; border: none; background: #f0f0f0; border-radius: 4px; cursor: pointer; font-size: 16px; line-height: 1; color: #666; flex-shrink: 0; }
  .close-btn:hover { background: #e0e0e0; }
</style>
</head>
<body>
<div class="header">
  <h1>Taxonomy Mind Map</h1>
  <div class="nav">
    <a href="index.html">Overview</a>
    <a href="taxonomy.html" class="active">Taxonomy</a>
    <a href="mindmap.html">Mindmap</a>
    <a href="papers.html">Papers</a>
    <a href="citation_graph.html">Citation Graph</a>
  </div>
</div>
<div class="tree-tabs">
  <button class="tree-tab active" data-tree="application_domain">Application Domain</button>
  <button class="tree-tab" data-tree="technical_approach">Technical Approach</button>
  <button class="tree-tab" data-tree="research_goal">Research Goal</button>
  <button class="tree-tab" data-tree="cross_cutting">Cross-cutting</button>
</div>
<div class="main-layout">
  <div class="left-sidebar tree-nav" id="tree-nav"></div>
  <div class="resize-handle" id="handle-left"></div>
  <div class="center-panel" id="center-panel">
    <div class="breadcrumb" id="breadcrumb"></div>
    <div class="current-node-card" id="current-card"></div>
    <div class="sub-nodes" id="sub-nodes"></div>
  </div>
  <div class="resize-handle" id="handle-right"></div>
  <div class="right-panel">
    <div class="right-header">
      <span id="right-title">References</span>
      <span id="right-count" style="color:#999;font-weight:400;font-size:13px;"></span>
    </div>
    <div class="right-list" id="right-list"></div>
  </div>
</div>

<script>
let data = {};
let paperMap = {};
let currentTree = 'application_domain';
let selectedNodePath = [];
let selectedPaperId = null;

async function load() {
  const res = await fetch('data.json?v=' + Date.now());
  data = await res.json();
  paperMap = Object.fromEntries(data.papers.map(p => [p.id, p]));
  renderApp('application_domain');
}

function collectPapers(node) {
  let pids = new Set();
  if (node.papers) node.papers.forEach(pid => pids.add(pid));
  if (node.children) node.children.forEach(c => collectPapers(c).forEach(pid => pids.add(pid)));
  return pids;
}

function getPapersSorted(node) {
  const pids = collectPapers(node);
  return Array.from(pids).map(pid => paperMap[pid]).filter(Boolean).sort((a,b) => a.num - b.num);
}

function findNodeByPath(treeData, path) {
  let nodes = treeData;
  let target = null;
  for (const name of path) {
    target = nodes.find(n => n.name === name);
    if (!target) return null;
    nodes = target.children || [];
  }
  return target;
}

/* ---- Left sidebar tree ---- */
function renderLeftTree() {
  const container = document.getElementById('tree-nav');
  const treeData = data.tree_hierarchy[currentTree] || [];
  const dummyRoot = { name: currentTree.replace(/_/g, ' '), children: treeData, count: treeData.reduce((s,c)=>s+c.count,0) };

  function buildUL(node, path) {
    const hasChildren = node.children && node.children.length > 0;
    const isActive = JSON.stringify(path) === JSON.stringify(selectedNodePath);
    const isOpen = selectedNodePath.slice(0, path.length).join('/') === path.join('/');
    const li = document.createElement('li');
    const line = document.createElement('div');
    line.className = 'node-line' + (isActive ? ' active' : '');
    line.style.paddingLeft = (12 + (path.length - 1) * 14) + 'px';

    const expand = hasChildren ? `<span class="expand-btn">${isOpen ? '▼' : '▶'}</span>` : '<span style="width:16px;display:inline-block"></span>';
    line.innerHTML = `${expand}<span style="flex:1">${node.name}</span><span class="count">${node.count || 0}</span>`;

    line.addEventListener('click', (e) => {
      if (e.target.classList.contains('expand-btn')) {
        e.stopPropagation();
        const ul = li.querySelector('.children');
        if (ul) { ul.classList.toggle('open'); e.target.textContent = ul.classList.contains('open') ? '▼' : '▶'; }
      } else {
        selectedNodePath = [...path];
        renderApp(currentTree);
      }
    });
    li.appendChild(line);

    if (hasChildren) {
      const childrenDiv = document.createElement('div');
      childrenDiv.className = 'children' + (isOpen ? ' open' : '');
      const ul = document.createElement('ul');
      node.children.forEach(child => ul.appendChild(buildUL(child, [...path, child.name])));
      childrenDiv.appendChild(ul);
      li.appendChild(childrenDiv);
    }
    return li;
  }

  container.innerHTML = '';
  const rootUL = document.createElement('ul');
  rootUL.appendChild(buildUL(dummyRoot, [dummyRoot.name]));
  container.appendChild(rootUL);
}

/* ---- Center panel ---- */
function renderCenter() {
  const treeData = data.tree_hierarchy[currentTree] || [];
  const dummyRoot = { name: currentTree.replace(/_/g, ' '), children: treeData, count: treeData.reduce((s,c)=>s+c.count,0) };
  const node = selectedNodePath.length > 0 ? findNodeByPath(treeData, selectedNodePath.slice(1)) : null;
  const current = node || dummyRoot;
  const path = selectedNodePath.length > 0 ? selectedNodePath : [dummyRoot.name];

  // Breadcrumb
  const bc = document.getElementById('breadcrumb');
  bc.innerHTML = path.map((name, i) => {
    if (i === path.length - 1) return `<span style="font-weight:600;color:#333">${name}</span>`;
    return `<span onclick="jumpToPath(${i})">${name}</span><span class="sep">/</span>`;
  }).join('');

  // Current card
  const card = document.getElementById('current-card');
  const papers = getPapersSorted(current);
  const currentPathParts = path.slice(1).map(n => n.toLowerCase().replace(/ /g, '-'));
  const currentPath = currentPathParts.join('/');
  const descKey = `${currentTree}:${currentPath}`;
  const desc = data.taxonomy_desc && data.taxonomy_desc[descKey];
  let descHtml = '';
  if (desc) {
    const text = desc.zh || desc.en || '';
    descHtml = `<div style="margin-top:10px;font-size:13px;line-height:1.6;color:#555;">${text}</div>`;
    const meta = desc.metadata || {};
    const methods = meta.methods || [];
    const datasets = meta.datasets || [];
    const trends = meta.trends || '';
    let metaParts = [];
    if (methods.length) metaParts.push(`<b>Methods:</b> ${methods.join(', ')}`);
    if (datasets.length) metaParts.push(`<b>Datasets:</b> ${datasets.join(', ')}`);
    if (trends) metaParts.push(`<b>Trends:</b> ${trends}`);
    if (metaParts.length) {
      descHtml += `<div style="margin-top:10px;padding:8px 10px;background:#f8f9fa;border-radius:6px;font-size:12px;line-height:1.5;color:#444;">${metaParts.join('<br>')}</div>`;
    }
  } else {
    descHtml = `<div style="margin-top:10px;font-size:13px;line-height:1.6;color:#999;font-style:italic;">Not available</div>`;
  }
  card.innerHTML = `<h2>${current.name}</h2><div class="meta">${papers.length} papers | ${current.children ? current.children.length + ' sub-categories' : 'leaf node'}</div>${descHtml}`;

  // Sub-nodes cards
  const subContainer = document.getElementById('sub-nodes');
  if (current.children && current.children.length > 0) {
    const colorClass = currentTree.includes('domain') ? 'color-domain' : currentTree.includes('approach') ? 'color-tech' : currentTree.includes('goal') ? 'color-goal' : 'color-cross';
    subContainer.innerHTML = current.children.map(child => {
      const childPapers = getPapersSorted(child);
      const childPath = [...currentPathParts, child.name.toLowerCase().replace(/ /g, '-')].join('/');
      const childDescKey = `${currentTree}:${childPath}`;
      const childDesc = data.taxonomy_desc && data.taxonomy_desc[childDescKey];
      const childDescHtml = childDesc ? `<div style="margin-top:6px;font-size:12px;line-height:1.5;color:#666;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">${childDesc.zh || childDesc.en || ''}</div>` : '';
      const preview = childPapers.slice(0, 4).map(p => `[${p.num}] ${p.short_title || p.title}`).join('<br>');
      return `<div class="sub-card ${colorClass}" onclick="selectChild('${child.name}')">
        <div class="name">${child.name}</div>
        <div class="count">${childPapers.length} papers</div>
        ${childDescHtml}
        ${preview ? `<div class="mini-papers">${preview}${childPapers.length > 4 ? '<br>...' : ''}</div>` : ''}
      </div>`;
    }).join('');
  } else {
    subContainer.innerHTML = papers.map(p => `
      <div class="paper-card" onclick="selectPaper('${p.id}')">
        <div class="p-num">[${p.num}]</div>
        <div class="p-title">${p.short_title || p.title}</div>
        <div class="p-meta">${p.venue || '?'} ${p.year || ''}</div>
      </div>
    `).join('');
  }
}

/* ---- Right panel ---- */
function renderRight() {
  const treeData = data.tree_hierarchy[currentTree] || [];
  const node = selectedNodePath.length > 0 ? findNodeByPath(treeData, selectedNodePath.slice(1)) : null;
  const dummyRoot = { name: currentTree.replace(/_/g, ' '), children: treeData, count: treeData.reduce((s,c)=>s+c.count,0) };
  const current = node || dummyRoot;
  const papers = getPapersSorted(current);

  if (selectedPaperId) {
    const p = paperMap[selectedPaperId];
    if (p) {
      document.getElementById('right-title').textContent = p.short_title || p.title;
      document.getElementById('right-count').innerHTML = '<button class="close-btn" onclick="closeDetail()">×</button>';
      const list = document.getElementById('right-list');
      list.innerHTML = renderPaperDetail(p);
      return;
    }
    selectedPaperId = null;
  }

  document.getElementById('right-title').textContent = current.name;
  document.getElementById('right-count').textContent = papers.length + ' papers';
  const list = document.getElementById('right-list');
  if (papers.length === 0) {
    list.innerHTML = '<div class="right-empty">No papers in this category.</div>';
    return;
  }
  list.innerHTML = papers.map(p => `
    <div class="right-item" onclick="selectPaper('${p.id}')">
      <span class="right-num">[${p.num}]</span>
      <span class="right-title">${p.short_title || p.title}</span>
      <span class="right-venue">${p.venue || '?'} ${p.year || ''}</span>
    </div>
  `).join('');
}

function selectPaper(id) {
  selectedPaperId = id;
  renderRight();
}

function closeDetail() {
  selectedPaperId = null;
  renderRight();
}

function renderPaperDetail(p) {
  const en = p.summary_en || p.abstract || '(abstract not available)';
  const zh = p.summary_zh || '（中文描述待补充）';
  const pdfLink = p.pdf_url ? `<a href="${p.pdf_url}" target="_blank">查看 PDF 原文 →</a>` : '<span style="color:#999;font-size:12px;">PDF 不可用</span>';
  return `
    <div class="right-detail">
      <div class="detail-num">[${p.num}]</div>
      <div class="detail-title">${p.short_title || p.title}</div>
      <div class="detail-meta">${p.venue || '?'} ${p.year || ''} | ${p.venue_area || '?'}</div>
      <div class="detail-abstract">${en.split('\\n').join('<br>')}</div>
      <div class="detail-cn">${zh.split('\\n').join('<br>')}</div>
      <div class="detail-pdf">${pdfLink}</div>
    </div>
  `;
}

function renderApp(treeName) {
  currentTree = treeName;
  renderLeftTree();
  renderCenter();
  renderRight();
}

function selectChild(name) {
  selectedNodePath = [...selectedNodePath, name];
  renderApp(currentTree);
}

function jumpToPath(index) {
  selectedNodePath = selectedNodePath.slice(0, index + 1);
  renderApp(currentTree);
}

// Initialize with first root selected
function initSelection() {
  const treeData = data.tree_hierarchy[currentTree] || [];
  const dummyRoot = { name: currentTree.replace(/_/g, ' '), children: treeData };
  selectedNodePath = [dummyRoot.name];
  if (treeData.length > 0) selectedNodePath.push(treeData[0].name);
}

document.querySelectorAll('.tree-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tree-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    currentTree = tab.dataset.tree;
    initSelection();
    renderApp(currentTree);
  });
});

load().then(() => { initSelection(); renderApp(currentTree); });

/* ---- Resize handles ---- */
(function setupResize() {
  let activeHandle = null;
  let startX = 0;
  let startWidth = 0;
  let targetEl = null;

  function onMove(e) {
    if (!activeHandle || !targetEl) return;
    const dx = e.clientX - startX;
    if (activeHandle.id === 'handle-left') {
      targetEl.style.width = Math.max(180, startWidth + dx) + 'px';
    } else if (activeHandle.id === 'handle-right') {
      targetEl.style.width = Math.max(200, startWidth - dx) + 'px';
    }
  }

  function onUp() {
    activeHandle = null;
    targetEl = null;
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  }

  ['handle-left', 'handle-right'].forEach(id => {
    const h = document.getElementById(id);
    if (!h) return;
    h.addEventListener('mousedown', (e) => {
      e.preventDefault();
      activeHandle = h;
      startX = e.clientX;
      if (id === 'handle-left') {
        targetEl = document.getElementById('tree-nav');
      } else {
        targetEl = document.querySelector('.right-panel');
      }
      startWidth = targetEl.getBoundingClientRect().width;
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  });
})();
</script>
</body>
</html>"""
    (docs_dir / "taxonomy.html").write_text(html, encoding="utf-8")


def _write_papers(docs_dir: Path) -> None:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Papers - Agent Survey</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; }
  .header { background: #fff; padding: 20px 24px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 20px; }
  .nav { display: flex; gap: 8px; }
  .nav a { padding: 6px 14px; border-radius: 6px; text-decoration: none; color: #333; font-size: 14px; background: #f0f0f0; }
  .nav a:hover { background: #e0e0e0; }
  .nav a.active { background: #333; color: #fff; }
  .container { max-width: 1200px; margin: 0 auto; padding: 24px; }
  .search-bar { width: 100%; padding: 10px 14px; border: 1px solid #ddd; border-radius: 8px; font-size: 14px; margin-bottom: 16px; }
  .paper-card { background: #fff; padding: 14px 18px; border-radius: 8px; margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
  .paper-title { font-weight: 500; font-size: 14px; }
  .paper-meta { color: #666; font-size: 12px; margin-top: 4px; }
  .paper-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
  .tag { font-size: 11px; padding: 3px 8px; border-radius: 12px; background: #f0f0f0; color: #555; }
  .tag-domain { background: #e3f2fd; color: #1565c0; }
  .tag-tech { background: #e8f5e9; color: #2e7d32; }
  .tag-goal { background: #fff3e0; color: #ef6c00; }
  .tag-cross { background: #fce4ec; color: #c2185b; }
  .paper-summary { font-size: 12px; color: #555; line-height: 1.5; margin-top: 8px; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; cursor: pointer; }
  .paper-summary.expanded { -webkit-line-clamp: unset; display: block; }
  .paper-summary .zh { margin-top: 6px; padding-top: 6px; border-top: 1px solid #f0f0f0; color: #444; }
</style>
</head>
<body>
<div class="header">
  <h1>Papers</h1>
  <div class="nav">
    <a href="index.html">Overview</a>
    <a href="taxonomy.html">Taxonomy</a>
    <a href="mindmap.html">Mindmap</a>
    <a href="papers.html" class="active">Papers</a>
    <a href="citation_graph.html">Citation Graph</a>
  </div>
</div>
<div class="container">
  <input class="search-bar" id="search" placeholder="Search by title, venue, or tag...">
  <div id="paper-list"></div>
</div>
<script>
let papers = [];

async function load() {
  const res = await fetch('data.json?v=' + Date.now());
  const data = await res.json();
  papers = data.papers;
  doRender();
}

let expandedId = null;

function render(list) {
  const el = document.getElementById('paper-list');
  el.innerHTML = list.map(p => {
    const tags = [];
    (p.taxonomy.application_domain || []).forEach(t => tags.push(`<span class="tag tag-domain">${t}</span>`));
    (p.taxonomy.technical_approach || []).forEach(t => tags.push(`<span class="tag tag-tech">${t}</span>`));
    (p.taxonomy.research_goal || []).forEach(t => tags.push(`<span class="tag tag-goal">${t}</span>`));
    (p.taxonomy.cross_cutting || []).forEach(t => tags.push(`<span class="tag tag-cross">${t}</span>`));
    const isExpanded = expandedId === p.id;
    const summaryEn = p.summary_en || '';
    const summaryZh = p.summary_zh || '';
    let summaryHtml = '';
    if (summaryEn || summaryZh) {
      const enHtml = summaryEn ? `<div>${summaryEn}</div>` : '';
      const zhHtml = summaryZh && isExpanded ? `<div class="zh">${summaryZh}</div>` : '';
      summaryHtml = `<div class="paper-summary ${isExpanded ? 'expanded' : ''}" onclick="event.stopPropagation();toggleExpand('${p.id}')">${enHtml}${zhHtml}</div>`;
    }
    return `<div class="paper-card" onclick="toggleExpand('${p.id}')">
      <div class="paper-title">${p.short_title || p.title}</div>
      <div class="paper-meta">${p.venue || '?'} ${p.year || ''} | cited: ${p.citation.matched_count || 0}</div>
      <div class="paper-tags">${tags.join('')}</div>
      ${summaryHtml}
    </div>`;
  }).join('');
}

let currentQuery = '';

function doRender() {
  let list = papers;
  if (currentQuery) {
    const q = currentQuery;
    list = papers.filter(p =>
      (p.short_title || p.title).toLowerCase().includes(q) ||
      p.title.toLowerCase().includes(q) ||
      (p.venue || '').toLowerCase().includes(q) ||
      Object.values(p.taxonomy).flat().some(t => t.toLowerCase().includes(q)) ||
      (p.summary_en || '').toLowerCase().includes(q) ||
      (p.summary_zh || '').toLowerCase().includes(q)
    );
  }
  render(list);
}

function toggleExpand(id) {
  expandedId = expandedId === id ? null : id;
  doRender();
}

document.getElementById('search').addEventListener('input', (e) => {
  currentQuery = e.target.value.toLowerCase();
  doRender();
});

load();
</script>
</body>
</html>"""
    (docs_dir / "papers.html").write_text(html, encoding="utf-8")


def _write_citation(docs_dir: Path) -> None:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Citation Graph - Agent Survey</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; }
  .header { background: #fff; padding: 20px 24px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; }
  .header h1 { font-size: 20px; }
  .nav { display: flex; gap: 8px; }
  .nav a { padding: 6px 14px; border-radius: 6px; text-decoration: none; color: #333; font-size: 14px; background: #f0f0f0; }
  .nav a:hover { background: #e0e0e0; }
  .nav a.active { background: #333; color: #fff; }
  #graph { width: 100vw; height: calc(100vh - 60px); }
  .tooltip { position: absolute; padding: 10px 14px; background: rgba(0,0,0,0.85); color: #fff; border-radius: 6px; font-size: 12px; pointer-events: none; max-width: 300px; line-height: 1.5; opacity: 0; transition: opacity 0.15s; }
</style>
<script src="https://d3js.org/d3.v7.min.js"></script>
</head>
<body>
<div class="header">
  <h1>Citation Graph</h1>
  <div class="nav">
    <a href="index.html">Overview</a>
    <a href="taxonomy.html">Taxonomy</a>
    <a href="mindmap.html">Mindmap</a>
    <a href="papers.html">Papers</a>
    <a href="citation_graph.html" class="active">Citation Graph</a>
  </div>
</div>
<div id="graph"></div>
<div class="tooltip" id="tooltip"></div>
<script>
async function load() {
  const res = await fetch('data.json?v=' + Date.now());
  const data = await res.json();
  const nodes = data.graph.nodes;
  const edges = data.graph.edges;

  const venueColors = { "SE": "#5470c6", "Security": "#ee6666", "AI": "#91cc75", "NLP": "#fac858", "HCI": "#73c0de" };
  const defaultColor = "#999";

  const width = window.innerWidth;
  const height = window.innerHeight - 60;

  const svg = d3.select("#graph").append("svg")
    .attr("width", width).attr("height", height)
    .call(d3.zoom().on("zoom", (e) => g.attr("transform", e.transform)));
  const g = svg.append("g");

  const sizeScale = d3.scaleSqrt().domain([0, Math.max(...nodes.map(d => d.in_degree)) || 1]).range([5, 30]);

  const simulation = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(edges).id(d => d.id).distance(120))
    .force("charge", d3.forceManyBody().strength(-200))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide().radius(d => sizeScale(d.in_degree) + 4));

  const link = g.append("g").attr("stroke", "#bbb").attr("stroke-opacity", 0.5)
    .selectAll("line").data(edges).join("line").attr("stroke-width", 1);

  const node = g.append("g").selectAll("circle").data(nodes).join("circle")
    .attr("r", d => sizeScale(d.in_degree))
    .attr("fill", d => venueColors[d.venue_area] || defaultColor)
    .attr("stroke", "#fff").attr("stroke-width", 1.5)
    .call(d3.drag().on("start", (e,d) => { if(!e.active) simulation.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
                   .on("drag", (e,d) => { d.fx=e.x; d.fy=e.y; })
                   .on("end", (e,d) => { if(!e.active) simulation.alphaTarget(0); d.fx=null; d.fy=null; }));

  const label = g.append("g").selectAll("text").data(nodes).join("text")
    .text(d => d.short_title || (d.title.length > 28 ? d.title.slice(0,26)+"..." : d.title))
    .attr("font-size", 10).attr("fill", "#333")
    .attr("dx", d => sizeScale(d.in_degree)+3).attr("dy", 3);

  const tooltip = d3.select("#tooltip");
  node.on("mouseover", (event, d) => {
    tooltip.style("opacity", 1)
      .html(`<strong>${d.title}</strong><br/>Venue: ${d.venue || "?"} ${d.year || ""}<br/>Cited by: ${d.in_degree} | Cites: ${d.out_degree}`)
      .style("left", (event.pageX+12)+"px").style("top", (event.pageY-12)+"px");
    const nbr = new Set(edges.filter(e => e.source.id===d.id||e.target.id===d.id).flatMap(e=>[e.source.id,e.target.id]));
    node.attr("opacity", n => nbr.has(n.id)?1:0.15);
    link.attr("stroke-opacity", l => (l.source.id===d.id||l.target.id===d.id)?1:0.05);
    label.attr("opacity", n => nbr.has(n.id)?1:0.1);
  }).on("mouseout", () => {
    tooltip.style("opacity", 0);
    node.attr("opacity", 1); link.attr("stroke-opacity", 0.5); label.attr("opacity", 1);
  });

  simulation.on("tick", () => {
    link.attr("x1",d=>d.source.x).attr("y1",d=>d.source.y).attr("x2",d=>d.target.x).attr("y2",d=>d.target.y);
    node.attr("cx",d=>d.x).attr("cy",d=>d.y);
    label.attr("x",d=>d.x).attr("y",d=>d.y);
  });
}
load();
</script>
</body>
</html>"""
    (docs_dir / "citation_graph.html").write_text(html, encoding="utf-8")


def _write_mindmap(docs_dir: Path) -> None:
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mind Map - Agent Survey</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
  .header { background: #fff; padding: 14px 24px; border-bottom: 1px solid #e0e0e0; display: flex; justify-content: space-between; align-items: center; flex-shrink: 0; }
  .header h1 { font-size: 18px; }
  .nav { display: flex; gap: 8px; }
  .nav a { padding: 6px 14px; border-radius: 6px; text-decoration: none; color: #333; font-size: 14px; background: #f0f0f0; }
  .nav a:hover { background: #e0e0e0; }
  .nav a.active { background: #333; color: #fff; }
  .tree-tabs { display: flex; gap: 8px; padding: 10px 24px; background: #fff; border-bottom: 1px solid #e8e8e8; flex-shrink: 0; }
  .tree-tab { padding: 8px 16px; border: none; border-radius: 6px; cursor: pointer; background: #e8e8e8; font-size: 14px; }
  .tree-tab.active { background: #333; color: #fff; }
  #mindmap-wrap { flex: 1; position: relative; overflow: hidden; background: #fafafa; }
  #mindmap-wrap svg { width: 100%; height: 100%; }
  .node-group { cursor: pointer; }
  .node-card { transition: filter 0.15s; }
  .node-group:hover .node-card { filter: brightness(1.12); }
  .node-text { font-family: inherit; pointer-events: none; }
  .link { fill: none; stroke: #bbb; stroke-width: 1.5px; opacity: 0.6; }
  .leaf-dot { fill: #ccc; }
  .resize-handle { height: 6px; background: #e8e8e8; cursor: ns-resize; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
  .resize-handle::after { content: ''; width: 40px; height: 3px; background: #ccc; border-radius: 2px; }
  .tooltip-mind { position: absolute; padding: 10px 14px; background: rgba(0,0,0,0.85); color: #fff; border-radius: 6px; font-size: 12px; pointer-events: none; max-width: 380px; line-height: 1.5; opacity: 0; transition: opacity 0.15s; z-index: 10; }
  .ref-panel { flex-shrink: 0; height: 240px; background: #fff; border-top: 1px solid #e0e0e0; display: flex; flex-direction: column; }
  .ref-header { padding: 10px 24px; border-bottom: 1px solid #f0f0f0; font-size: 14px; font-weight: 600; display: flex; justify-content: space-between; align-items: center; }
  .ref-list { flex: 1; overflow-y: auto; padding: 8px 24px; }
  .ref-item { font-size: 13px; padding: 5px 0; border-bottom: 1px solid #f5f5f5; display: flex; gap: 8px; align-items: baseline; cursor: pointer; }
  .ref-item:hover { background: #fafafa; }
  .ref-item:last-child { border-bottom: none; }
  .ref-num { font-weight: 700; color: #333; min-width: 32px; font-size: 12px; }
  .ref-title { color: #333; line-height: 1.4; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ref-venue { color: #999; font-size: 11px; white-space: nowrap; margin-left: auto; padding-left: 8px; }
  .ref-empty { color: #999; font-size: 13px; padding: 16px 24px; }
  .abstract-box { font-size: 13px; line-height: 1.7; color: #333; padding: 4px 0; }
  .abstract-box h3 { font-size: 14px; margin-bottom: 8px; }
  .abstract-box .meta { color: #999; font-size: 12px; margin-bottom: 8px; }
  .back-btn { padding: 4px 12px; font-size: 12px; border: 1px solid #ddd; border-radius: 4px; background: #fff; cursor: pointer; margin-top: 8px; }
  .back-btn:hover { background: #f5f5f5; }

  /* Paper detail modal */
  .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); display: none; align-items: center; justify-content: center; z-index: 100; }
  .modal-overlay.open { display: flex; }
  .modal-card { background: #fff; border-radius: 10px; box-shadow: 0 8px 32px rgba(0,0,0,0.2); width: 720px; max-width: 90vw; max-height: 80vh; display: flex; flex-direction: column; }
  .modal-header { padding: 16px 20px; border-bottom: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
  .modal-header h3 { font-size: 15px; line-height: 1.5; margin: 0; flex: 1; }
  .modal-header .meta { font-size: 12px; color: #999; margin-top: 4px; }
  .modal-close { width: 28px; height: 28px; border: none; background: #f5f5f5; border-radius: 6px; cursor: pointer; font-size: 16px; line-height: 1; flex-shrink: 0; }
  .modal-close:hover { background: #eee; }
  .modal-body { flex: 1; overflow-y: auto; padding: 16px 20px; font-size: 13px; line-height: 1.8; color: #333; }
</style>
</head>
<body>
<div class="header">
  <h1>Taxonomy Mind Map</h1>
  <div class="nav">
    <a href="index.html">Overview</a>
    <a href="taxonomy.html">Taxonomy</a>
    <a href="mindmap.html" class="active">Mindmap</a>
    <a href="papers.html">Papers</a>
    <a href="citation_graph.html">Citation Graph</a>
  </div>
</div>
<div class="tree-tabs">
  <button class="tree-tab active" data-tree="application_domain">Application Domain</button>
  <button class="tree-tab" data-tree="technical_approach">Technical Approach</button>
  <button class="tree-tab" data-tree="research_goal">Research Goal</button>
  <button class="tree-tab" data-tree="cross_cutting">Cross-cutting</button>
</div>
<div id="mindmap-wrap"><svg id="mindmap"></svg></div>
<div class="ref-panel" id="ref-panel">
  <div class="resize-handle" id="resize-handle"></div>
  <div class="ref-header">
    <span id="ref-title">References — click a node to view papers</span>
    <span id="ref-count" style="color:#999;font-weight:400;font-size:13px;"></span>
  </div>
  <div class="ref-list" id="ref-list"></div>
</div>
<div class="tooltip-mind" id="tooltip"></div>

<div class="modal-overlay" id="modal-overlay" onclick="closeModal()">
  <div class="modal-card" id="modal-card" onclick="event.stopPropagation()">
    <div class="modal-header">
      <div>
        <h3 id="modal-title"></h3>
        <div class="meta" id="modal-meta"></div>
      </div>
      <button class="modal-close" onclick="closeModal()">×</button>
    </div>
    <div class="modal-body" id="modal-body"></div>
  </div>
</div>

<script>
let data = {};
let paperMap = {};
let currentTree = 'application_domain';
let lastSelectedCategory = null;

async function load() {
  const res = await fetch('data.json?v=' + Date.now());
  data = await res.json();
  paperMap = Object.fromEntries(data.papers.map(p => [p.id, p]));
  renderTree('application_domain');
}

function collectPapers(node) {
  let pids = new Set();
  if (node.papers) node.papers.forEach(pid => pids.add(pid));
  if (node.children) node.children.forEach(c => collectPapers(c).forEach(pid => pids.add(pid)));
  return pids;
}

function showPapersFor(d) {
  lastSelectedCategory = d;
  const pids = collectPapers(d.data);
  const list = Array.from(pids).map(pid => paperMap[pid]).filter(Boolean).sort((a, b) => a.num - b.num);
  const path = d.ancestors().reverse().map(n => n.data.name).join(' / ');
  document.getElementById('ref-title').textContent = path;
  document.getElementById('ref-count').textContent = list.length + ' papers';
  const listEl = document.getElementById('ref-list');
  if (list.length === 0) {
    listEl.innerHTML = '<div class="ref-empty">No papers in this category.</div>';
    return;
  }
  listEl.innerHTML = list.map(p => `
    <div class="ref-item" onclick="showPaperDetail('${p.id}')">
      <span class="ref-num">[${p.num}]</span>
      <span class="ref-title">${p.short_title || p.title}</span>
      <span class="ref-venue">${p.venue || '?'} ${p.year || ''}</span>
    </div>
  `).join('');
}

function showPaperDetail(paperId) {
  const p = paperMap[paperId];
  if (!p) return;
  document.getElementById('ref-title').innerHTML = `<span style="cursor:pointer;color:#666;margin-right:8px;" onclick="backToList()">←</span>[${p.num}] ${p.short_title || p.title}`;
  document.getElementById('ref-count').textContent = `${p.venue || '?'} ${p.year || ''} | ${p.venue_area || '?'}`;
  const en = p.summary_en || p.abstract || '(abstract not available)';
  const zh = p.summary_zh || '';
  let html = `<div class="abstract-box"><div class="meta">${p.venue || '?'} ${p.year || ''} | ${p.venue_area || '?'}</div>${en.split('\\n').join('<br>')}</div>`;
  if (zh) {
    html += `<div class="abstract-box" style="margin-top:8px;border-top:1px solid #eee;padding-top:8px;"><div class="meta">中文摘要</div>${zh.split('\\n').join('<br>')}</div>`;
  }
  document.getElementById('ref-list').innerHTML = html;
}

function backToList() {
  if (lastSelectedCategory) showPapersFor(lastSelectedCategory);
}

let activeLeafCard = null;

function closeLeafCard() {
  if (activeLeafCard) {
    activeLeafCard.transition().duration(150).attr('opacity', 0).remove();
    activeLeafCard = null;
  }
}

function showLeafCard(d, zoomG, offsetX, offsetY) {
  closeLeafCard();
  const pids = collectPapers(d.data);
  const list = Array.from(pids).map(pid => paperMap[pid]).filter(Boolean).sort((a, b) => a.num - b.num);
  if (list.length === 0) return;

  const cardW = 420;
  const cardH = 300;
  const headerH = 32;
  const footerH = 32;
  const pageSize = 12;

  const isLeft = d.data._side === 'left';
  const nx = d.y + offsetX + (isLeft ? -cardW/2 - 20 : cardW/2 + 20);
  const ny = d.x + offsetY;

  const g = zoomG.append('g').attr('class', 'leaf-card').attr('opacity', 0);
  activeLeafCard = g;
  g.attr('transform', `translate(${nx},${ny})`);

  // Background
  g.append('rect')
    .attr('width', cardW).attr('height', cardH)
    .attr('x', 0).attr('y', -cardH/2)
    .attr('rx', 8).attr('fill', '#fff')
    .attr('stroke', '#ddd').attr('stroke-width', 1);

  // Header
  g.append('text')
    .attr('x', 10).attr('y', -cardH/2 + 20)
    .attr('fill', '#333').style('font-size', '12px').style('font-weight', '600')
    .text(`${d.data.name} (${list.length})`);

  // Close button
  g.append('text')
    .attr('x', cardW - 10).attr('y', -cardH/2 + 18)
    .attr('text-anchor', 'end').attr('fill', '#999').style('font-size', '14px').style('cursor', 'pointer')
    .text('×')
    .on('click', (e) => { e.stopPropagation(); closeLeafCard(); });

  // Drag handle (transparent header bar)
  g.append('rect')
    .attr('class', 'drag-handle')
    .attr('width', cardW - 30).attr('height', headerH)
    .attr('x', 0).attr('y', -cardH/2)
    .attr('fill', 'transparent').style('cursor', 'move');

  let dragging = false;
  let dragStart = null;
  let dragOrigin = [nx, ny];

  g.select('.drag-handle').on('mousedown', (event) => {
    event.stopPropagation();
    dragging = true;
    dragStart = d3.pointer(event, zoomG.node());
    d3.select(window)
      .on('mousemove.leafdrag', (event) => {
        if (!dragging) return;
        const pt = d3.pointer(event, zoomG.node());
        const dx = pt[0] - dragStart[0];
        const dy = pt[1] - dragStart[1];
        g.attr('transform', `translate(${dragOrigin[0] + dx},${dragOrigin[1] + dy})`);
      })
      .on('mouseup.leafdrag', (event) => {
        if (!dragging) return;
        dragging = false;
        const pt = d3.pointer(event, zoomG.node());
        const dx = pt[0] - dragStart[0];
        const dy = pt[1] - dragStart[1];
        dragOrigin = [dragOrigin[0] + dx, dragOrigin[1] + dy];
        d3.select(window).on('mousemove.leafdrag', null).on('mouseup.leafdrag', null);
      });
  });

  const contentH = cardH - headerH - footerH;
  const fo = g.append('foreignObject')
    .attr('x', 8).attr('y', -cardH/2 + headerH)
    .attr('width', cardW - 16).attr('height', contentH);

  let currentPage = 0;
  const totalPages = Math.ceil(list.length / pageSize);

  function renderPage(page) {
    const start = page * pageSize;
    const pageItems = list.slice(start, start + pageSize);
    const prevStyle = page === 0 ? 'opacity:0.3;pointer-events:none;' : 'cursor:pointer;';
    const nextStyle = page >= totalPages - 1 ? 'opacity:0.3;pointer-events:none;' : 'cursor:pointer;';

    const gridHtml = pageItems.map(p => `
      <div onclick="showPaperDetail('${p.id}')" style="cursor:pointer;padding:5px 6px;background:#f8f8f8;border-radius:4px;font-size:11px;line-height:1.3;border:1px solid #eee;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;transition:background 0.15s;" onmouseover="this.style.background='#f0f0f0'" onmouseout="this.style.background='#f8f8f8'">
        <span style="font-weight:700;color:#333;">[${p.num}]</span> ${p.short_title || p.title}
      </div>
    `).join('');

    const footerHtml = totalPages > 1 ? `
      <div style="display:flex;justify-content:center;align-items:center;gap:10px;padding:4px 0;font-size:12px;color:#666;border-top:1px solid #f0f0f0;">
        <span onclick="window._leafPrevPage()" style="${prevStyle}padding:2px 10px;background:#f5f5f5;border-radius:4px;font-size:13px;">←</span>
        <span>${page + 1} / ${totalPages}</span>
        <span onclick="window._leafNextPage()" style="${nextStyle}padding:2px 10px;background:#f5f5f5;border-radius:4px;font-size:13px;">→</span>
      </div>
    ` : '';

    fo.html(`<div style="width:100%;height:100%;display:flex;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;">
      <div style="flex:1;display:grid;grid-template-columns:repeat(2, 1fr);gap:6px;align-content:start;padding:4px 0;">${gridHtml}</div>
      ${footerHtml}
    </div>`);
  }

  window._leafPrevPage = () => {
    if (currentPage > 0) { currentPage--; renderPage(currentPage); }
  };
  window._leafNextPage = () => {
    if (currentPage < totalPages - 1) { currentPage++; renderPage(currentPage); }
  };

  renderPage(currentPage);
  g.transition().duration(200).attr('opacity', 1);
}

function renderTree(treeName) {
  currentTree = treeName;
  const wrap = document.getElementById('mindmap-wrap');
  const width = wrap.clientWidth;
  const height = wrap.clientHeight;

  closeLeafCard();
  d3.select('#mindmap').selectAll('*').remove();
  const svg = d3.select('#mindmap').attr('width', width).attr('height', height);
  const zoomG = svg.append('g');
  const zoom = d3.zoom()
    .scaleExtent([0.2, 3])
    .on('zoom', (e) => zoomG.attr('transform', e.transform))
    .filter((event) => {
      if (event.type === 'wheel') return event.ctrlKey;
      return !event.button;
    });
  svg.call(zoom);

  svg.on('wheel.pan', (event) => {
    if (event.ctrlKey) return;
    event.preventDefault();
    const t = d3.zoomTransform(svg.node());
    svg.call(zoom.translateBy, -event.deltaX / t.k, -event.deltaY / t.k);
  });

  const treeData = data.tree_hierarchy[treeName];
  if (!treeData || treeData.length === 0) {
    zoomG.append('text').attr('text-anchor','middle').attr('x', width/2).attr('y', height/2).text('No data');
    return;
  }

  const rootNode = { name: treeName.replace(/_/g, ' '), children: treeData, count: 0 };
  const root = d3.hierarchy(rootNode).sum(d => d.count).sort((a, b) => b.value - a.value);

  // Split level-1 children into left / right halves for a butterfly layout
  if (root.children && root.children.length > 0) {
    const mid = Math.ceil(root.children.length / 2);
    root.children.forEach((c, i) => { c.data._side = i < mid ? 'left' : 'right'; });
    root.descendants().forEach(d => {
      if (d.depth > 1 && d.parent) d.data._side = d.parent.data._side;
    });
  }

  // Layout constants
  const cardW = 200;
  const cardH = 32;
  const levelGap = 280;
  const nodeGap = 46;

  // Custom layout — only counts *visible* children so collapsed subtrees shrink
  // Butterfly: left/right halves are mirrored and vertically centered
  function layout(node, depth) {
    const side = node.data._side || 'right';
    const dir = side === 'left' ? -1 : 1;
    node.y = depth * levelGap * dir;

    if (node.data.__paper_card) {
      node.y += (side === 'left' ? -1 : 1) * 60;
      node._layoutH = 280;
      return 280;
    }

    const children = node.children;
    if (!children || children.length === 0) {
      node._layoutH = nodeGap;
      return nodeGap;
    }

    // Group children by side so left/right halves are independently centered
    const leftChildren = children.filter(c => c.data._side === 'left');
    const rightChildren = children.filter(c => c.data._side !== 'left');

    let leftH = 0, rightH = 0;
    leftChildren.forEach(c => {
      const ch = layout(c, depth + 1);
      c._offsetY = leftH;
      leftH += ch;
    });
    rightChildren.forEach(c => {
      const ch = layout(c, depth + 1);
      c._offsetY = rightH;
      rightH += ch;
    });

    const maxH = Math.max(leftH, rightH, nodeGap);
    if (leftChildren.length) {
      const shift = (maxH - leftH) / 2;
      leftChildren.forEach(c => c._offsetY += shift);
    }
    if (rightChildren.length) {
      const shift = (maxH - rightH) / 2;
      rightChildren.forEach(c => c._offsetY += shift);
    }

    node._layoutH = maxH;
    return maxH;
  }

  layout(root, 0);

  // Assign x positions — only walk visible children
  function assignX(node, baseX) {
    node.x = baseX + (node._layoutH || nodeGap) / 2;
    const children = node.children;
    if (children) {
      children.forEach(c => assignX(c, baseX + (c._offsetY || 0)));
    }
  }
  assignX(root, 0);

  // Collapse depth >= 2 initially
  root.descendants().forEach(d => {
    if (d.depth >= 2 && d.children) { d._children = d.children; d.children = null; }
  });

  const tooltip = d3.select('#tooltip');

  function update(source) {
    layout(root, 0);
    assignX(root, 0);
    const nodes = root.descendants();
    const links = root.links();

    const offsetX = 30;
    const offsetY = Math.max(20, (height - (root._layoutH || height)) / 2);

    // Links — source/target edge depends on branch side
    const link = zoomG.selectAll('.link').data(links, d => {
      if (d.target.data.__paper_card) return 'link-card-' + (d.source.data.name || '') + '-' + d.target.depth;
      return d.target.data.name + d.target.depth;
    });
    link.exit().transition().duration(250).attr('opacity', 0).remove();
    const linkEnter = link.enter().append('path').attr('class', 'link')
      .attr('d', d => {
        const isLeft = d.target.data._side === 'left';
        const isCard = d.target.data.__paper_card;
        const tEdge = isCard ? 420/2 : cardW/2;
        const sx = d.source.y + offsetX + (isLeft ? -cardW/2 : cardW/2);
        const sy = d.source.x + offsetY;
        return `M${sx},${sy} L${sx},${sy}`;
      });
    linkEnter.merge(link).transition().duration(400)
      .attr('d', d => {
        const isLeft = d.target.data._side === 'left';
        const isCard = d.target.data.__paper_card;
        const tEdge = isCard ? 420/2 : cardW/2;
        const sx = d.source.y + offsetX + (isLeft ? -cardW/2 : cardW/2);
        const sy = d.source.x + offsetY;
        const tx = d.target.y + offsetX + (isLeft ? tEdge : -tEdge);
        const ty = d.target.x + offsetY;
        const mx = (sx + tx) / 2;
        return `M${sx},${sy} C${mx},${sy} ${mx},${ty} ${tx},${ty}`;
      });

    // Nodes
    const node = zoomG.selectAll('.node-group').data(nodes, d => {
      if (d.data.__paper_card) return 'card-' + (d.parent ? d.parent.data.name : '') + '-' + d.depth;
      return d.data.name + d.depth;
    });
    node.exit().transition().duration(250).attr('opacity', 0).remove();

    const nodeEnter = node.enter().append('g').attr('class', 'node-group')
      .attr('transform', d => `translate(${source.y + offsetX},${source.x + offsetY})`)
      .on('click', (e, d) => {
        e.stopPropagation();
        if (d.data.__paper_card) return;
        if (d.data.is_paper) {
          showPaperDetail(d.data.paper_id);
          return;
        }
        const isLeaf = !d.children && !d._children && d.data.papers && d.data.papers.length > 0;
        if (isLeaf) {
          // Toggle paper-card expansion
          if (d.children && d.children.some(c => c.data.__paper_card)) {
            d.children = d.children.filter(c => !c.data.__paper_card);
            if (d.children.length === 0) d.children = null;
          } else {
            const pids = collectPapers(d.data);
            const list = Array.from(pids).map(pid => paperMap[pid]).filter(Boolean).sort((a, b) => a.num - b.num);
            const cardNode = {
              data: { __paper_card: true, papers: list, page: 0, pageSize: 12, name: '', _side: d.data._side },
              depth: d.depth + 1,
              parent: d,
              height: 0,
              children: null,
              _children: null
            };
            if (!d.children) d.children = [];
            d.children.push(cardNode);
          }
          update(d);
        } else {
          showPapersFor(d);
          if (d.children) { d._children = d.children; d.children = null; }
          else { d.children = d._children; d._children = null; }
          update(d);
        }
      })
      .on('mouseover', (e, d) => {
        if (d.data.__paper_card) return;
        if (d.data.is_paper) {
          const p = paperMap[d.data.paper_id];
          if (!p) return;
          tooltip.style('opacity', 1)
            .html(`<strong>[${p.num}] ${p.short_title || p.title}</strong><br>${p.venue || '?'} ${p.year || ''}<br><em>Click to view abstract</em>`)
            .style('left', (e.pageX+12)+'px').style('top', (e.pageY-12)+'px');
          return;
        }
        const pids = collectPapers(d.data);
        const list = Array.from(pids).map(pid => paperMap[pid]).filter(Boolean).sort((a,b)=>a.num-b.num);
        const preview = list.slice(0,5).map(p => `[${p.num}] ${p.short_title || p.title}`).join('<br>');
        tooltip.style('opacity', 1)
          .html(`<strong>${d.data.name}</strong> (${list.length})<br>${preview}${list.length>5 ? '<br>...' : ''}`)
          .style('left', (e.pageX+12)+'px').style('top', (e.pageY-12)+'px');
      })
      .on('mouseout', () => tooltip.style('opacity', 0));

    // Paper card nodes (expanded leaf containers)
    const pcW = 420, pcH = 280;
    const paperCardEnter = nodeEnter.filter(d => d.data.__paper_card);
    paperCardEnter.append('rect')
      .attr('width', pcW).attr('height', pcH)
      .attr('x', -pcW/2).attr('y', -pcH/2)
      .attr('rx', 8).attr('fill', '#fff')
      .attr('stroke', '#ddd').attr('stroke-width', 1);
    paperCardEnter.each(function(d) {
      const gSel = d3.select(this);
      const fo = gSel.append('foreignObject')
        .attr('x', -pcW/2 + 8).attr('y', -pcH/2 + 4)
        .attr('width', pcW - 16).attr('height', pcH - 8);
      const div = document.createElement('div');
      div.style.cssText = 'width:100%;height:100%;display:flex;flex-direction:column;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;';
      const gridDiv = document.createElement('div');
      gridDiv.style.cssText = 'flex:1;display:grid;grid-template-columns:repeat(2, 1fr);gap:6px;align-content:start;padding:4px 0;';
      const footerDiv = document.createElement('div');
      footerDiv.style.cssText = 'display:flex;justify-content:center;align-items:center;gap:10px;padding:4px 0;font-size:12px;color:#666;border-top:1px solid #f0f0f0;';
      div.appendChild(gridDiv);
      div.appendChild(footerDiv);
      fo.node().appendChild(div);

      function renderPage(page) {
        const pageSize = d.data.pageSize || 12;
        const totalPages = Math.ceil(d.data.papers.length / pageSize);
        const start = page * pageSize;
        const pageItems = d.data.papers.slice(start, start + pageSize);
        gridDiv.innerHTML = pageItems.map(p => `
          <div style="cursor:pointer;padding:5px 6px;background:#f8f8f8;border-radius:4px;font-size:11px;line-height:1.3;border:1px solid #eee;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;transition:background 0.15s;" onmouseover="this.style.background='#f0f0f0'" onmouseout="this.style.background='#f8f8f8'" onclick="showPaperDetail('${p.id}')">
            <span style="font-weight:700;color:#333;">[${p.num}]</span> ${p.short_title || p.title}
          </div>
        `).join('');
        if (totalPages > 1) {
          footerDiv.innerHTML = `
            <span style="padding:2px 10px;background:#f5f5f5;border-radius:4px;font-size:13px;">←</span>
            <span>${page + 1} / ${totalPages}</span>
            <span style="padding:2px 10px;background:#f5f5f5;border-radius:4px;font-size:13px;">→</span>
          `;
          const [prevBtn, _, nextBtn] = footerDiv.children;
          if (page > 0) {
            prevBtn.style.cursor = 'pointer';
            prevBtn.addEventListener('click', (e) => { e.stopPropagation(); d.data.page--; renderPage(d.data.page); });
          } else {
            prevBtn.style.opacity = '0.3';
            prevBtn.style.pointerEvents = 'none';
          }
          if (page < totalPages - 1) {
            nextBtn.style.cursor = 'pointer';
            nextBtn.addEventListener('click', (e) => { e.stopPropagation(); d.data.page++; renderPage(d.data.page); });
          } else {
            nextBtn.style.opacity = '0.3';
            nextBtn.style.pointerEvents = 'none';
          }
        } else {
          footerDiv.innerHTML = '';
        }
      }
      renderPage(d.data.page);
    });

    // Card bg (normal nodes only)
    nodeEnter.filter(d => !d.data.__paper_card).append('rect').attr('class', 'node-card')
      .attr('width', cardW).attr('height', cardH)
      .attr('x', -cardW/2).attr('y', -cardH/2)
      .attr('rx', 5).attr('ry', 5)
      .attr('fill', d => {
        if (d.depth === 0) return '#2c3e50';
        if (d.data.is_paper) return '#f5f5f5';
        const colors = ['#5470c6','#91cc75','#fac858','#ee6666','#73c0de','#9a60b4'];
        return colors[(d.depth - 1) % colors.length];
      })
      .attr('stroke', d => d.data.is_paper ? '#ccc' : '#fff')
      .attr('stroke-width', d => d.data.is_paper ? 1 : 2);

    // Expand/collapse indicator — on the side facing the children
    const indicatorX = d => (d.data._side === 'left' ? -1 : 1) * cardW/2;
    nodeEnter.filter(d => !d.data.__paper_card && (d._children || (d.children && d.children.length > 0)))
      .append('circle')
      .attr('cx', indicatorX).attr('cy', 0).attr('r', 5)
      .attr('fill', '#fff').attr('stroke', '#999').attr('stroke-width', 1);
    nodeEnter.filter(d => !d.data.__paper_card && d._children)
      .append('text').attr('x', indicatorX).attr('dy', '0.32em')
      .attr('text-anchor', 'middle').attr('fill', '#666').style('font-size', '9px').text('+');
    nodeEnter.filter(d => !d.data.__paper_card && d.children && d.children.length > 0)
      .append('text').attr('x', indicatorX).attr('dy', '0.32em')
      .attr('text-anchor', 'middle').attr('fill', '#666').style('font-size', '9px').text('-');

    // Text label (normal nodes only)
    nodeEnter.filter(d => !d.data.__paper_card).append('text').attr('class', 'node-text')
      .attr('dy', d => d.data.is_paper ? '0.32em' : '-0.1em')
      .attr('x', 0).attr('text-anchor', 'middle')
      .attr('fill', d => d.data.is_paper ? '#333' : '#fff')
      .text(d => {
        if (d.data.is_paper) {
          return d.data.name.length > 14 ? d.data.name.slice(0,12)+'..' : d.data.name;
        }
        return d.depth === 0 ? d.data.name : (d.data.name.length > 24 ? d.data.name.slice(0,22)+'..' : d.data.name);
      })
      .style('font-size', d => d.data.is_paper ? '9px' : '11px')
      .style('font-weight', '600');

    // Count label (only for categories)
    nodeEnter.filter(d => !d.data.__paper_card && !d.data.is_paper)
      .append('text').attr('class', 'node-text')
      .attr('dy', '1.0em')
      .attr('x', 0).attr('text-anchor', 'middle')
      .attr('fill', 'rgba(255,255,255,0.8)')
      .text(d => (d.data.count || 0) + ' papers')
      .style('font-size', '9px');

    // Leaf category indicator dot
    const leafDotX = d => (d.data._side === 'left' ? -1 : 1) * (cardW/2 + 6);
    nodeEnter.filter(d => !d.data.__paper_card && !d.data.is_paper && !d.children && !d._children && d.data.papers && d.data.papers.length > 0)
      .append('circle').attr('class', 'leaf-dot')
      .attr('cx', leafDotX).attr('cy', 0).attr('r', 3)
      .attr('fill', '#ccc');

    node.merge(nodeEnter).transition().duration(400)
      .attr('transform', d => `translate(${d.y + offsetX},${d.x + offsetY})`);

    nodes.forEach(d => { d.x0 = d.x; d.y0 = d.y; });

    // Auto-fit
    if (!source._autoFitDone) {
      source._autoFitDone = true;
      setTimeout(() => {
        const bounds = zoomG.node().getBBox();
        const pad = 40;
        const fullW = bounds.width + pad * 2;
        const fullH = bounds.height + pad * 2;
        const s = Math.min(width / fullW, height / fullH, 1);
        const tx = (width - fullW * s) / 2 - bounds.x * s + pad * s;
        const ty = (height - fullH * s) / 2 - bounds.y * s + pad * s;
        svg.transition().duration(600).call(zoom.transform, d3.zoomIdentity.translate(tx, ty).scale(s));
      }, 50);
    }
  }

  update(root);
  showPapersFor(root);
}

document.querySelectorAll('.tree-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tree-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    renderTree(tab.dataset.tree);
  });
});

window.addEventListener('resize', () => renderTree(currentTree));

// Resize ref-panel height
(function() {
  const handle = document.getElementById('resize-handle');
  const panel = document.getElementById('ref-panel');
  let startY, startH;
  handle.addEventListener('mousedown', (e) => {
    startY = e.clientY;
    startH = panel.offsetHeight;
    document.body.style.cursor = 'ns-resize';
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
    e.preventDefault();
  });
  function onMove(e) {
    const dy = startY - e.clientY;
    panel.style.height = Math.max(120, Math.min(window.innerHeight * 0.7, startH + dy)) + 'px';
  }
  function onUp() {
    document.body.style.cursor = '';
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  }
})();

load();
</script>
</body>
</html>"""
    (docs_dir / "mindmap.html").write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
