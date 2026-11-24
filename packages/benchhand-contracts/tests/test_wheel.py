"""The built benchhand-contracts wheel validates by $id when installed outside this checkout, and the
benchhand-core wheel beside it saves and loads a record against the packaged record contracts."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parents[1]
WORKSPACE_PACKAGES = [PACKAGE_DIR.parent / name for name in ("benchhand-provider", "benchhand-core")]
UV = shutil.which("uv")

# Runs in the fresh venv, from a directory outside the checkout.
SMOKE_SCRIPT = """
import json
import sys
from importlib.resources import files

import benchhand_contracts
from benchhand_contracts import ContractViolation, Finding, validate
from benchhand_contracts.models.provider import protocol_schema

assert not benchhand_contracts.__file__.startswith(sys.argv[1]), benchhand_contracts.__file__
contracts = "https://benchhand.github.io/benchhand/contracts"
schemas = files("benchhand_contracts") / "schemas"

finding = json.loads((schemas / "common" / "finding.schema.json").read_text())["examples"][0]
validate(f"{contracts}/common/finding.schema.json", finding)
Finding.model_validate(finding)
try:
    validate(f"{contracts}/common/finding.schema.json", {**finding, "severity": "fatal"})
except ContractViolation as violation:
    assert violation.pointer == "/severity", violation.pointer
else:
    raise AssertionError("an invalid finding passed")

# The manifest refers to the protocol schema, so this resolves a $ref across packaged files.
manifest = json.loads((schemas / "provider" / "manifest.schema.json").read_text())["examples"][0]
validate(f"{contracts}/provider/manifest.schema.json", manifest)
protocol_schema.HookDecl.model_validate({"kind": "kernel", "id": "build123d"})

# A record made of the packaged examples saves and loads through the record contracts in the wheel.
import tempfile
from pathlib import Path

from benchhand_core.record import store
from benchhand_core.record.model import (
    Assembly, BomRow, Interfaces, Product, Record, Requirements, VerificationRow
)


def example(name):
    path = files("benchhand_contracts") / "examples" / "record" / f"{name}.examples.json"
    cases = json.loads(path.read_text())
    return cases["cases"][0]["valid"][0]


record = Record(
    product=Product.model_validate(example("product")),
    requirements=Requirements.model_validate(example("requirements")),
    interfaces=Interfaces.model_validate(example("interfaces")),
    assembly=Assembly.model_validate(example("assembly")),
    bom=[BomRow.model_validate(example("bom-row"))],
    verification=[VerificationRow.model_validate(example("verification-row"))],
)
root = Path(tempfile.mkdtemp())
store.save_record(root, record)
assert store.load_record(root) == record
"""


@pytest.mark.skipif(UV is None, reason="needs uv")
def test_the_installed_wheel_validates_without_a_checkout(tmp_path: Path) -> None:
    assert UV is not None
    dist, venv = tmp_path / "dist", tmp_path / "venv"
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "VIRTUAL_ENV")}

    def run(*command: str | Path) -> None:
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"{command}:\n{result.stdout}{result.stderr}"

    for package in [PACKAGE_DIR, *WORKSPACE_PACKAGES]:
        run(UV, "build", "--wheel", "--quiet", "--out-dir", dist, package)
    run(UV, "venv", "--quiet", "--python", sys.executable, venv)
    python = venv / "bin" / "python"
    run(UV, "pip", "install", "--quiet", "--python", python, *dist.glob("*.whl"))
    run(python, "-c", SMOKE_SCRIPT, PACKAGE_DIR.parents[1])
