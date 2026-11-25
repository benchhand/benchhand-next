"""Pydantic v2 models in benchhand_contracts, generated from the published schemas."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .sources import GENERATED_NOTICE, Contract

# Fixed options keep the output identical on every machine; datamodel-code-generator is pinned in
# pyproject.toml, and the preset name pins its defaults.
DATAMODEL_CODEGEN_OPTIONS = (
    "--input-file-type",
    "jsonschema",
    "--preset",
    "standard-py312-20261123",
    "--formatters",
    "ruff-format",
    "--disable-timestamp",
    "--use-schema-description",
    "--use-field-description",
    # A schema object without additionalProperties is open; pydantic's default (ignore) would drop its
    # extra keys, so every model extends a base that keeps them. Closed objects still forbid them.
    "--base-class",
    "benchhand_contracts.base.ContractModel",
)
SOURCE_MARKER = "@@contracts-gen-source@@"
RUFF_CONFIG = 'line-length = 110\ntarget-version = "py312"\n'


class PythonGenerationError(Exception):
    """datamodel-code-generator failed."""


def write_python(contracts: list[Contract], schemas_dir: Path, out_dir: Path) -> None:
    """Write models for every contract into ``out_dir`` (the ``benchhand_contracts.models`` package)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    _run_datamodel_codegen(contracts, schemas_dir, out_dir)
    _stamp_sources(contracts, out_dir)
    (out_dir / "__init__.py").write_text(
        f'"""Models generated from contracts/. {GENERATED_NOTICE}"""\n', encoding="utf-8"
    )


def _run_datamodel_codegen(contracts: list[Contract], schemas_dir: Path, out_dir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="contracts-gen-") as scratch:
        # Only the schema files go in, so no other file there ever becomes a model.
        inputs = Path(scratch, "inputs")
        for contract in contracts:
            target = inputs / contract.rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(schemas_dir / contract.rel_path, target)
        # Ruff takes its settings from the config nearest the output file, so the output goes to a
        # directory with its own config: the result can't depend on where it is written.
        staged = Path(scratch, "out")
        staged.mkdir()
        Path(scratch, "ruff.toml").write_text(RUFF_CONFIG, encoding="utf-8")
        header = f"# {GENERATED_NOTICE}\n# Source: {SOURCE_MARKER}"
        command = [sys.executable, "-m", "datamodel_code_generator", "--input", str(inputs), "--output"]
        command += [str(staged), *DATAMODEL_CODEGEN_OPTIONS, "--custom-file-header", header]
        result = subprocess.run(command, cwd=scratch, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise PythonGenerationError(f"datamodel-codegen failed:\n{result.stderr}")
        shutil.copytree(staged, out_dir, dirs_exist_ok=True)


def _module_sources(contracts: list[Contract]) -> dict[str, str]:
    """Generated module path -> source path, following datamodel-codegen's file naming."""
    sources = {}
    for contract in contracts:
        sources[_module_name(contract.rel_path.removesuffix(".json")) + ".py"] = contract.source
        package = Path(contract.rel_path).parent
        while package != Path("."):
            module = _module_name(package.as_posix())
            sources.setdefault(f"{module}/__init__.py", f"contracts/{package.as_posix()}/")
            package = package.parent
    return sources


def _module_name(rel_path: str) -> str:
    """``record/bom-row.schema`` -> ``record/bom_row_schema``, as datamodel-codegen names modules."""
    return rel_path.replace(".", "_").replace("-", "_")


def _stamp_sources(contracts: list[Contract], out_dir: Path) -> None:
    sources = _module_sources(contracts)
    for path in sorted(out_dir.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if SOURCE_MARKER in text:
            source = sources.get(path.relative_to(out_dir).as_posix(), "contracts/")
            path.write_text(text.replace(SOURCE_MARKER, source), encoding="utf-8")
