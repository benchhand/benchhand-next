# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Compile contracts/*.tsp to the JSON Schema bundle, and split it into the published schemas (ADR-0017)."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .normalise import Source, normalise

TSP = Path("node_modules") / ".bin" / "tsp"
DECLARATIONS = Path("scripts") / "declarations.mjs"
BUNDLE = "contracts.schema.json"
"""The file name tspconfig.yaml's ``bundleId`` gives the emitted bundle."""


class TypeSpecError(Exception):
    """The TypeSpec compiler is missing, or it reported an error or a warning."""


def compile_bundle(contracts_dir: Path, output_dir: Path) -> dict[str, Any]:
    """Run ``tsp compile`` on ``contracts_dir`` with warnings as errors; the bundle it writes."""
    tsp = contracts_dir / TSP
    if not tsp.is_file():
        raise TypeSpecError(f"{tsp} not found: run `pnpm install` in {contracts_dir}")
    command = [str(tsp), "compile", ".", "--warn-as-error", "--output-dir", str(output_dir)]
    result = subprocess.run(command, cwd=contracts_dir, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise TypeSpecError(f"tsp compile failed:\n{result.stdout}{result.stderr}")
    return json.loads((output_dir / BUNDLE).read_text(encoding="utf-8"))


def read_source(contracts_dir: Path) -> Source:
    """The declarations of ``contracts_dir``, as the TypeSpec compiler reads them."""
    node = shutil.which("node")
    if node is None:
        raise TypeSpecError("node not found: the TypeSpec compiler needs Node.js")
    command = [node, str(DECLARATIONS), "main.tsp"]
    result = subprocess.run(command, cwd=contracts_dir, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise TypeSpecError(f"{DECLARATIONS} failed:\n{result.stdout}{result.stderr}")
    return Source.from_json(json.loads(result.stdout))


def write_published_schemas(contracts_dir: Path, out_dir: Path) -> None:
    """Write each contract's published schema, ``<dir>/<contract>.schema.json``, into ``out_dir``."""
    with tempfile.TemporaryDirectory(prefix="contracts-tsp-") as scratch:
        bundle = compile_bundle(contracts_dir, Path(scratch))
    for rel_path, schema in normalise(bundle, read_source(contracts_dir)).items():
        target = out_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
