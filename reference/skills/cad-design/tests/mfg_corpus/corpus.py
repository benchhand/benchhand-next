# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Mutation corpus core: pairs, families, the registry and the rate arithmetic.

A Pair is one defect with its clean twin. `run(mutant)` builds the case, runs one manufacturability or
constructability check and returns an outcome. The same function builds both variants, so the twin differs
from the mutant only by the defect. Families live in `families/*.py` and register by exposing `FAMILY`.
Pure standard library. Each `run` imports the check and its fixtures lazily.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

Outcome = Literal["fail", "pass", "unknown"]
OUTCOMES: tuple[str, ...] = ("fail", "pass", "unknown")
HERE = Path(__file__).resolve().parent
FAMILIES_DIR = HERE / "families"
FIXTURES_DIR = HERE / "fixtures"
BASELINE_DIR = HERE / "baseline"

# The families that judge the `cad_model check` report because the `cad.readback` packet has no obligation for
# glb_step_agreement or declared_dimensions yet. Remove this line with issue #174, which moves them to the packet.
# The corpus guard (tests/test_mfg_corpus.py) lets exactly these families import the runner `_oracles`, and the rates
# command labels them and leaves them out of the packet-level total.
ORACLES_EXEMPTION_174 = frozenset({"semantic_changed_only_scope", "semantic_equal_volume_substitution",
                                   "semantic_misplaced_feature", "semantic_step_glb_disagreement",
                                   "semantic_wrong_placement"})
NOT_AT_THE_PACKET = "not at the packet (#174)"


class Skip(Exception):
    """Raised by `run` when the case needs a tool this machine lacks. The rates leave the pair out."""


class Rejected(Exception):
    """Raised by `run` when the packet check or the evidence assessment refuses the case's packet. Neither a detection
    nor an abstention. The pair counts as a miss and the run records the reason."""


@dataclass(frozen=True)
class Pair:
    id: str  # unique within the family
    defect: str  # the one thing the mutant gets wrong, in a phrase
    run: Callable[[bool], Outcome]  # run(True) is the must-FAIL mutant, run(False) its must-PASS twin
    known_gap: str | None = None  # why the mutant's verdict is not trusted (e.g. it FAILs for a wrong reason): a miss whatever it returns


@dataclass(frozen=True)
class Family:
    id: str  # unique, snake_case: <check>_<defect class>
    check: str  # the check under test, as a module path or script name
    pairs: tuple[Pair, ...]
    owner: str = ""  # the package or area that maintains it
    notes: str = field(default="", compare=False)


@dataclass
class PairResult:
    id: str
    defect: str
    mutant: str | None = None
    twin: str | None = None
    skipped: str | None = None
    error: str | None = None
    rejected: str | None = None
    known_gap: str | None = None


def load_families(directory: Path = FAMILIES_DIR) -> list[Family]:
    """Import every `families/*.py` (not starting with `_`) and collect its `FAMILY` (or `FAMILIES`)."""
    found: list[Family] = []
    for path in sorted(directory.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = f"mfg_corpus_family_{path.stem}"
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        found.extend(getattr(module, "FAMILIES", None) or [module.FAMILY])
    validate(found)
    return found


def validate(families: Iterable[Family]) -> None:
    seen: set[str] = set()
    for family in families:
        if family.id in seen:
            raise ValueError(f"duplicate family id {family.id}")
        seen.add(family.id)
        ids = [pair.id for pair in family.pairs]
        if not ids or len(ids) != len(set(ids)):
            raise ValueError(f"family {family.id} needs unique, non-empty pair ids")


def run_pair(pair: Pair) -> PairResult:
    result = PairResult(pair.id, pair.defect, known_gap=pair.known_gap)
    try:
        result.mutant = pair.run(True)
        result.twin = pair.run(False)
    except Skip as skip:
        result.mutant = result.twin = None
        result.skipped = str(skip) or "skipped"
        return result
    except Rejected as refusal:
        result.mutant = result.twin = None
        result.rejected = str(refusal) or "rejected"
        return result
    except Exception as exc:  # record the crash, never hide it as a pass
        return _errored(result, f"{type(exc).__name__}: {exc}")
    for variant in (result.mutant, result.twin):
        if variant not in OUTCOMES:
            return _errored(result, f"outcome {variant!r} is not one of {OUTCOMES}")
    return result


def _errored(result: PairResult, message: str) -> PairResult:
    """A failure on either side voids both verdicts, so the pair is a miss and never a detection."""
    result.mutant = result.twin = None
    result.error = message
    return result


def rate(count: int, total: int) -> float | None:
    return round(count / total, 4) if total else None


def summarise(family: Family, results: list[PairResult]) -> dict[str, Any]:
    """Rates over the pairs that ran: detection = FAIL on mutant, abstention = UNKNOWN on mutant,
    false positive = FAIL on twin. A pair that errored, or whose packet evidence rejected on either side, has no verdicts
    and counts as a miss. A pair with a known gap counts as a miss whatever its mutant returned. Its twin still counts."""
    ran = [r for r in results if not r.skipped]
    n = len(ran)
    trusted = [r for r in ran if not r.known_gap]
    detected = sum(r.mutant == "fail" for r in trusted)
    abstained = sum(r.mutant == "unknown" for r in trusted)
    missed = n - detected - abstained  # a pass on the mutant, or a pair that errored or got rejected
    false_pos = sum(r.twin == "fail" for r in ran)
    return {
        "family": family.id, "check": family.check, "owner": family.owner,
        "pairs": len(results), "ran": n, "skipped": len(results) - n, "errors": sum(bool(r.error) for r in ran),
        "rejected": sum(bool(r.rejected) for r in ran), "known_gaps": sum(bool(r.known_gap) for r in ran),
        "detected": detected, "abstained": abstained, "missed": missed, "false_positives": false_pos,
        "detection_rate": rate(detected, n), "abstention_rate": rate(abstained, n),
        "false_positive_rate": rate(false_pos, n),
        "results": [vars(r) for r in results],
    }


def evaluate(families: Iterable[Family]) -> list[dict[str, Any]]:
    return [summarise(f, [run_pair(p) for p in f.pairs]) for f in families]


def table(rows: list[dict[str, Any]]) -> str:
    def pct(value: float | None) -> str:
        return "n/a" if value is None else f"{value * 100:.0f}%"

    head = ("family", "ran/pairs", "detect", "abstain", "false+", "note")
    body = [(r["family"], f"{r['ran']}/{r['pairs']}", pct(r["detection_rate"]), pct(r["abstention_rate"]),
             pct(r["false_positive_rate"]), NOT_AT_THE_PACKET if r["family"] in ORACLES_EXEMPTION_174 else "")
            for r in rows]
    widths = [max(len(str(x[i])) for x in (head, *body)) for i in range(len(head))]
    lines = ["  ".join(str(x[i]).ljust(widths[i]) for i in range(len(head))).rstrip() for x in (head, *body)]
    return "\n".join(lines)


def packet_level_total(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Mutants detected and twins judged FAIL over the packet-level families. The total skips the families in
    ORACLES_EXEMPTION_174: their rates measure whether the oracle tells the mutant from its twin, not whether a release
    blocks it."""
    counted = [r for r in rows if r["family"] not in ORACLES_EXEMPTION_174]
    return {"families": len(counted), "ran": sum(r["ran"] for r in counted),
            "detected": sum(r["detected"] for r in counted), "false_positives": sum(r["false_positives"] for r in counted)}


def check_baseline(rows: list[dict[str, Any]], baseline_dir: Path, *, whole_registry: bool = True) -> list[str]:
    """Problems against `baseline_dir/<family>.json`. Every evaluated family needs a baseline file. On a whole-registry
    run each baseline file also needs a family. A family may not run fewer pairs than recorded, lose detection or gain
    false positives."""
    problems: list[str] = []
    files = {path.stem: path for path in sorted(baseline_dir.glob("*.json"))}
    ids = {row["family"] for row in rows}
    for family in sorted(ids - files.keys()):
        problems.append(f"{family}: no baseline file baseline/{family}.json")
    for family in sorted(files.keys() - ids) if whole_registry else ():
        problems.append(f"{family}: baseline file without a registered family")
    for row in rows:
        path = files.get(row["family"])
        if path is None:
            continue
        base = json.loads(path.read_text(encoding="utf-8"))
        name = row["family"]
        if row["ran"] < base["ran"]:
            problems.append(f"{name}: ran {row['ran']} pairs, baseline {base['ran']} ({row['skipped']} skipped)")
        if row["detection_rate"] is None or row["detection_rate"] < base["detection_rate"]:
            problems.append(f"{name}: detection {row['detection_rate']} below baseline {base['detection_rate']}")
        if row["false_positive_rate"] is None or row["false_positive_rate"] > base["false_positive_rate"]:
            problems.append(f"{name}: false positives {row['false_positive_rate']} above baseline {base['false_positive_rate']}")
    return problems
