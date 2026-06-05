"""
Skill: consistency_check
========================
Cross-validate harvest and enrich data quality.

When to use
-----------
- After harvest: verify paper counts match known acceptance numbers
- After enrich: verify abstract coverage per venue
- Before report generation: ensure data is clean
- When merging data from multiple sources

Procedure
---------
1. **Harvest consistency**
   - Compare ``harvest_runs.paper_count`` with actual ``papers`` table count
   - Flag mismatches → possible batch writer data loss
   - Check for "empty" venues where year ≤ current_year-1 (should have data)
   - Check for 0-paper venues (likely TOC path wrong or DBLP not indexed)

2. **Enrich consistency**
   - Per-venue abstract coverage %
   - Flag venues with coverage < 80% for strategy review
   - Count papers by ``enrich_source`` per venue
   - Detect if a source suddenly fails for a previously-covered venue

3. **Paper quality checks**
   - Titles that are proceedings volumes / frontmatter
   - Titles < 20 characters (likely not real papers)
   - Duplicate titles within same venue-year
   - Papers with empty author lists

4. **Cross-reference**
   - Compare against known acceptance numbers (from deepseek / official sites)
   - Flag venues with counts deviating > 20% from expectation

5. **Output**
   - Generate a ``consistency_report.json``
   - Actionable issue list with venue, year, severity, suggested fix

Healing actions (can be automated)
-----------------------------------
- ``harvest_runs mismatch`` → delete harvest_runs record, re-run harvest for that venue-year
- ``abstract coverage < 80%`` → run enrich_strategy skill for that venue
- ``empty venue for past year`` → run harvest_strategy skill
- ``proceedings titles`` → mark as ``non_tech`` in DB

Example report
--------------
    {
      "harvest": {
        "mismatches": [
          {"venue": "FSE", "year": 2024, "expected": 121, "actual": 0, "action": "reset_and_reharvest"}
        ]
      },
      "enrich": {
        "low_coverage": [
          {"venue": "ICLR", "coverage": "44%", "action": "run_enrich_strategy"}
        ]
      },
      "quality": {
        "proceedings_titles": 24,
        "short_titles": 3,
        "duplicates": 0
      }
    }
"""

SKILL = {
    "name": "consistency_check",
    "version": "1.0",
    "category": "validate",
    "description": "Cross-validate harvest and enrich data quality",
    "trigger": "Before report generation or after any pipeline stage",
    "inputs": {
        "db_path": "Path — SQLite database path",
        "config": "Config — venue configuration with expected counts",
        "check_abstracts": "bool — also validate abstract coverage",
    },
    "outputs": {
        "harvest_issues": "list[dict] — venue, year, expected, actual, action",
        "enrich_issues": "list[dict] — venue, coverage_pct, missing_count",
        "quality_issues": "list[dict] — paper_id, issue_type, suggestion",
    },
    "checks": [
        "harvest_runs_vs_papers_table",
        "empty_venues_for_past_years",
        "abstract_coverage_per_venue",
        "enrich_source_distribution",
        "proceedings_titles",
        "short_or_empty_titles",
        "duplicate_papers",
        "missing_authors",
    ],
    "auto_heal": [
        "reset_harvest_runs_for_mismatches",
        "trigger_harvest_strategy_for_empty_venues",
        "trigger_enrich_strategy_for_low_coverage",
    ],
}
