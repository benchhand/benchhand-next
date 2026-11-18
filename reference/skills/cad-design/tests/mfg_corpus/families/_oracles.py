# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Runner shared by the semantic-output-oracle families. `_oracle_driver.py` builds and checks one case under
`uv run --script`. Its own environment holds cad-model's runtime, so the corpus process needs nothing beyond
what rates.py declares.

`case(model=..., fault=...)` returns the `run` function of a Pair: run(True) builds the project with the
model overrides and the one exporter fault, run(False) the unmodified project. The runner caches verdicts per
process, so pairs that share a clean twin build it once."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from typing import Any

from corpus import FAMILIES_DIR, Outcome, Skip

DRIVER = FAMILIES_DIR / "_oracle_driver.py"
_CACHE: dict[str, Outcome] = {}


def verdict(model: dict[str, Any] | None, fault: dict[str, Any] | None, changed_only: bool = False) -> Outcome:
    key = json.dumps({"model": model, "fault": fault, "changed_only": changed_only}, sort_keys=True)
    if key not in _CACHE:
        uv = shutil.which("uv")
        if uv is None:
            raise Skip("uv is not on PATH: the cad-model runtime cannot be created")
        with tempfile.TemporaryDirectory(prefix="mfg-oracle-") as work:
            case_file = f"{work}/case.json"
            with open(case_file, "w", encoding="utf-8") as handle:
                handle.write(key)
            proc = subprocess.run([uv, "run", "--quiet", "--script", str(DRIVER), case_file, work],
                                  capture_output=True, text=True, check=False)  # no timeout: cold imports take minutes
        if proc.returncode != 0:
            raise RuntimeError(f"driver exited {proc.returncode}: {proc.stderr[-800:]}")
        _CACHE[key] = json.loads(proc.stdout.strip().splitlines()[-1])["outcome"]
    return _CACHE[key]


def case(model: dict[str, Any] | None = None, fault: dict[str, Any] | None = None, *,
         changed_only: bool = False) -> Callable[[bool], Outcome]:
    """With `changed_only`, `model` is the change under test (v2 against a clean v1), so the twin keeps it and
    differs from the mutant by the fault alone. Otherwise the twin is the unmodified project."""
    def run(mutant: bool) -> Outcome:
        if mutant:
            return verdict(model, fault, changed_only)
        return verdict(model, None, True) if changed_only else verdict(None, None)
    return run
