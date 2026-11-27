"""The status of one obligation from all its evidence, and the evidence levels as independent facets.

Each rule cites its source in the prototype, skills/cad-record/scripts/evidence.py at release.toml
reference_commit 412b5d9, so a later prototype change is one reviewed step (ADR-0015).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

# Evidence levels, independent facets and never an ordinal (manufacturing_intent.py:73).
LEVELS = (
    "cad_valid",
    "geometrically_manufacturable",
    "process_planned",
    "simulation_supported",
    "physically_validated",
)
PHYSICAL = "physically_validated"
_WORST_FIRST = ("fail", "stale", "unknown", "planned", "not_assessed", "waived", "pass", "not_applicable")
NOT_REQUIRED = "not_required"


def worst(results: Iterable[str]) -> str | None:
    """The worst of `results` in the order fail, stale, unknown, planned, not_assessed, waived, pass,
    not_applicable; None for none (evidence.py:257)."""
    found = set(results)
    return next((result for result in _WORST_FIRST if result in found), None)


def best(results: Sequence[str], waived: bool) -> str:
    """The status of one obligation from all its evidence (evidence.py:262). A current fail stands unless a
    valid waiver covers it (then waived, never pass); a pass outranks waivers, stale, planned and unknown.
    not_assessed ranks below pass, waived and not_applicable, above stale and planned; an explicit unknown
    beside it keeps the obligation unknown. No evidence at all is unknown."""
    found = set(results)
    if "fail" in found:
        return "waived" if waived else "fail"
    for result in ("pass", "waived", "not_applicable"):
        if result in found or (result == "waived" and waived):
            return result
    if "not_assessed" in found:
        return "unknown" if "unknown" in found else "not_assessed"
    for result in ("stale", "planned"):
        if result in found:
            return result
    return "unknown"


def facets(
    collected: Mapping[str, Mapping[str, Sequence[str]]], keys: Iterable[str]
) -> dict[str, dict[str, str]]:
    """Per subject key, each evidence level's worst status, or not_required where no obligation applies
    (evidence.py:1047 `_facets`). `collected` maps a key to level to the statuses found there."""
    return {
        key: {level: worst(collected.get(key, {}).get(level, ())) or NOT_REQUIRED for level in LEVELS}
        for key in sorted(set(keys) | set(collected))
    }
