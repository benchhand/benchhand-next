"""TypeScript types and Ajv standalone validators, written by ui/shared/scripts/gen-contracts.mjs."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from .sources import REPO_ROOT, Contract

NODE_SCRIPT = "ui/shared/scripts/gen-contracts.mjs"
NODE_PACKAGES = ("ajv", "json-schema-to-typescript")


class TypeScriptGenerationError(Exception):
    """Node is missing, the ui/ packages aren't installed, or the Node generator failed."""


def write_typescript(contracts: list[Contract], contracts_dir: Path, out_dir: Path) -> None:
    node = shutil.which("node")
    if node is None:
        raise TypeScriptGenerationError("node is not on PATH; the TypeScript contracts need Node (see ui/)")
    modules = REPO_ROOT / "ui" / "shared" / "node_modules"
    missing = [name for name in NODE_PACKAGES if not (modules / name).is_dir()]
    if missing:
        raise TypeScriptGenerationError(f"{', '.join(missing)} not installed: run `pnpm install` in ui/")
    out_dir.mkdir(parents=True, exist_ok=True)
    command = [node, str(REPO_ROOT / NODE_SCRIPT), str(contracts_dir), str(out_dir)]
    command += [contract.rel_path for contract in contracts]
    result = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise TypeScriptGenerationError(f"{NODE_SCRIPT} failed:\n{result.stderr}")
