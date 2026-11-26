"""Compare every runner's results/<engine>.jsonl with the expected results in suite.json.

Matching follows cel-spec's simple.proto: a value must equal the expected value (maps ignore order, any NaN
matches NaN), an eval_error matches any evaluation error, and an unset result means `true`. Writes
results/summary.md (pass counts per file and engine) and results/failures-<engine>.txt.
"""

from __future__ import annotations

import base64
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TRUE = {"boolValue": True}


def number(x: object) -> float:
    if isinstance(x, str):
        return {"NaN": math.nan, "Infinity": math.inf, "-Infinity": -math.inf}.get(x, float(x))
    assert isinstance(x, int | float)
    return float(x)


def equal(want: dict, got: dict) -> bool:
    (wkind, wval), (gkind, gval) = next(iter(want.items())), next(iter(got.items()))
    if wkind != gkind:
        return False
    if wkind in ("int64Value", "uint64Value"):
        return int(wval) == int(gval)
    if wkind == "doubleValue":
        w, g = number(wval), number(gval)
        return (math.isnan(w) and math.isnan(g)) or w == g
    if wkind == "bytesValue":
        return base64.b64decode(wval or "") == base64.b64decode(gval or "")
    if wkind == "listValue":
        ws, gs = (wval or {}).get("values", []), (gval or {}).get("values", [])
        return len(ws) == len(gs) and all(equal(w, g) for w, g in zip(ws, gs, strict=True))
    if wkind == "mapValue":
        return maps_equal((wval or {}).get("entries", []), (gval or {}).get("entries", []))
    return wval == gval


def maps_equal(want: list[dict], got: list[dict]) -> bool:
    if len(want) != len(got):
        return False
    for w in want:
        match = [g for g in got if equal(w["key"], g["key"])]
        if len(match) != 1 or not equal(w["value"], match[0]["value"]):
            return False
    return True


def verdict(test: dict, row: dict) -> str | None:
    """None when the row passes, otherwise a one-line reason."""
    outcome = row.get("outcome")
    if "evalError" in test:
        return (
            None if outcome == "eval_error" else f"want an eval error, got {outcome} {row.get('value', '')}"
        )
    want = test.get("value", TRUE)
    if outcome == "value" and equal(want, row["value"]):
        return None
    got = row.get("value") if outcome == "value" else row.get("message", "")
    return f"want {json.dumps(want)}, got {outcome}: {json.dumps(got)[:160]}"


def score(engine: str, tests: dict) -> tuple[dict[str, int], list[str], int]:
    """Passes per file, the failure lines, and how many failures are disableCheck tests the engine checked."""
    rows = {
        (r["file"], r["section"], r["name"]): r for r in map(json.loads, (RESULTS / f"{engine}.jsonl").open())
    }
    passed: dict[str, int] = {}
    lines = []
    checked_anyway = 0
    for key, test in tests.items():
        row = rows.get(key, {"outcome": "missing"})
        why = verdict(test, row)
        if why is None:
            passed[key[0]] = passed.get(key[0], 0) + 1
            continue
        lines.append(f"{'/'.join(key)}: {why}")
        checked_anyway += bool(test.get("disableCheck")) and row["outcome"] == "check_error"
    return passed, lines, checked_anyway


def main() -> int:
    suite = json.loads((ROOT / "suite.json").read_text())
    tests = {(f["name"], s["name"], t["name"]): t for f in suite for s in f["sections"] for t in s["tests"]}
    files = [f["name"] for f in suite]
    engines = sorted(p.stem for p in RESULTS.glob("*.jsonl"))
    totals = {f["name"]: sum(len(s["tests"]) for s in f["sections"]) for f in suite}
    scores = {}
    for engine in engines:
        scores[engine] = score(engine, tests)
        (RESULTS / f"failures-{engine}.txt").write_text("\n".join(scores[engine][1]) + "\n")
    header = "| file | tests | " + " | ".join(engines) + " |"
    out = [header, "|---|---:|" + "---:|" * len(engines)]
    for name in files:
        out.append(
            f"| {name} | {totals[name]} | "
            + " | ".join(str(scores[e][0].get(name, 0)) for e in engines)
            + " |"
        )
    total = sum(totals.values())
    sums = [sum(scores[e][0].values()) for e in engines]
    out.append(
        f"| **all** | {total} | " + " | ".join(f"**{s}** ({100 * s / total:.1f}%)" for s in sums) + " |"
    )
    out.append(
        "| of the failures: disableCheck tests rejected by the checker | | "
        + " | ".join(str(scores[e][2]) for e in engines)
        + " |"
    )
    (RESULTS / "summary.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
