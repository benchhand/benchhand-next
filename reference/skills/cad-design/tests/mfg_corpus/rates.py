#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["pyyaml>=6.0", "jsonschema>=4.0", "cadquery-ocp-novtk==8.0.1.1.0"]
# ///
"""Print the per-family detection, abstention and false-positive rates of the mutation corpus.

Run:  uv run --script skills/cad-design/tests/mfg_corpus/rates.py [--family ID ...] [--out PATH]
Writes the JSON report (default: <tempdir>/mfg-corpus-rates.json) and prints its path after the table.
Exit 0 when the corpus ran, whatever the rates. With --check-baseline it exits 1 and lists the problems when a
family has no baseline file (or a baseline has no family), runs fewer pairs than recorded, detects less, or raises
false positives; a skipped pair then fails the check instead of passing quietly.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or '').splitlines()[0])
    parser.add_argument("--family", action="append", help="only this family id (repeatable)")
    parser.add_argument("--check-baseline", action="store_true", help="fail when a family regresses from baseline/")
    parser.add_argument("--families-dir", type=Path, default=corpus.FAMILIES_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--baseline-dir", type=Path, default=corpus.BASELINE_DIR, help=argparse.SUPPRESS)
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "mfg-corpus-rates.json")
    args = parser.parse_args(argv)
    families = corpus.load_families(args.families_dir)
    if args.family:
        unknown = set(args.family) - {f.id for f in families}
        if unknown:
            parser.error(f"unknown family: {', '.join(sorted(unknown))}")
        families = [f for f in families if f.id in args.family]
    rows = corpus.evaluate(families)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"format": 1, "families": rows}, indent=2) + "\n", encoding="utf-8")
    print(corpus.table(rows))
    print(f"report: {args.out}")
    if args.check_baseline:
        problems = corpus.check_baseline(rows, args.baseline_dir, whole_registry=not args.family)
        for problem in problems:
            print(f"baseline: {problem}")
        return 1 if problems else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
