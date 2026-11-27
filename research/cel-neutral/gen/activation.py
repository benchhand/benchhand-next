# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Write the typed demo's activation: real records taken from the published schemas' examples and fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CONTRACTS = HERE.parents[2] / "packages/benchhand-contracts/src/benchhand_contracts"


def record(source: dict) -> dict:
    if "schema" in source:
        document = json.loads((CONTRACTS / "schemas" / source["schema"]).read_text())
        return document["examples"][source["example"]]
    fixture = json.loads((CONTRACTS / "examples" / source["fixture"]).read_text())
    return fixture["cases"][0]["valid"][source["valid"]]


def main(demo: Path, out: Path) -> int:
    spec = yaml.safe_load(demo.read_text())
    activation = {name: record(source) for name, source in spec["activation"].items()}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(activation, indent=2) + "\n")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
