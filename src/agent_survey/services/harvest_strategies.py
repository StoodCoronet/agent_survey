"""Per-venue harvest strategies — same pattern as enrich _VENUE_SOURCES.

Default: single-volume XML TOC from conf/<lower>/<lower>{year}.xml
Override only the outliers.
"""
from __future__ import annotations

# (toc_stream, volumes)
#   toc_stream: DBLP TOC prefix, e.g. "conf/icse/icse"
#   volumes: how many -N extra suffixes to try (0 = single-volume)

# ── Venues that deviate from the default conf/<name>/<name> pattern ──
_VENUE_OVERRIDES: dict[str, tuple[str, int]] = {
    # Different TOC key
    "FSE":     ("conf/sigsoft/fse", 0),
    "ASE":     ("conf/kbse/ase", 0),
    "NeurIPS": ("conf/nips/neurips", 0),
    # Multi-volume
    "AAAI":    ("conf/aaai/aaai", 2),
    "ACL":     ("conf/acl/acl", 2),
    "EMNLP":   ("conf/emnlp/emnlp", 2),
    "NAACL":   ("conf/naacl/naacl", 2),
    # No TOC
    "COLM":    ("", 0),
}


def get_strategy(venue_name: str, key_prefixes: list[str] | None = None) -> tuple[str, int] | None:
    """Return (toc_stream, volumes) for a venue.

    Checks overrides first, then derives from key_prefixes,
    then falls back to conf/<lower>/<lower>.
    """
    if venue_name in _VENUE_OVERRIDES:
        val = _VENUE_OVERRIDES[venue_name]
        return val if val[0] else None

    # Derive from key_prefixes (e.g. ["conf/icse/"] → "conf/icse/icse")
    for pfx in (key_prefixes or []):
        parts = pfx.strip("/").split("/")
        if len(parts) >= 2 and parts[0] in ("conf", "journals"):
            abbrev = parts[-1]
            return (f"{parts[0]}/{abbrev}/{abbrev}", 0)

    # Fallback: conf/<lower>/<lower>
    abbrev = venue_name.lower().replace(" ", "")
    return (f"conf/{abbrev}/{abbrev}", 0)
