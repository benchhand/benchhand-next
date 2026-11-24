"""The contract generator in tools/gen (ADR-0017): discovery, outputs, fixtures, docs and drift."""

from __future__ import annotations

import importlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from benchhand_contracts import ContractViolation, validate
from benchhand_contracts.validation import ContractValidator
from contracts_gen.docs import write_docs
from contracts_gen.examples import ExampleError, contract_registry, write_examples
from contracts_gen.generate import drift, generate
from contracts_gen.python_models import write_python, write_schemas
from contracts_gen.sources import (
    CONTRACTS_DIR,
    DOCS_OUT,
    EXAMPLES_OUT,
    MODELS_OUT,
    REPO_ROOT,
    TYPESCRIPT_OUT,
    ContractSourceError,
    load_contracts,
)
from contracts_gen.typescript import write_typescript

NODE_READY = shutil.which("node") is not None and all(
    (REPO_ROOT / "ui" / "shared" / "node_modules" / name).is_dir()
    for name in ("ajv", "json-schema-to-typescript")
)
needs_node = pytest.mark.skipif(not NODE_READY, reason="needs node and `pnpm install` in ui/")

# A directory no real contract uses, so the copied contracts tree can never already have it.
SYNTHETIC_DIR = "generator-test"
SYNTHETIC_PACKAGE = "generator_test"  # datamodel-codegen's module name for SYNTHETIC_DIR
NEW_ID = f"https://benchhand.github.io/benchhand/contracts/{SYNTHETIC_DIR}/widget.schema.json"
NEW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": NEW_ID,
    "title": "widget",
    "x-version": "1.0.0",
    "type": "object",
    "properties": {
        "part": {"$ref": "#/$defs/PartNumber"},
        "kind": {"$ref": "../provider/protocol.schema.json#/$defs/HookKind"},
    },
    "required": ["part"],
    "additionalProperties": False,
    "$defs": {
        "PartNumber": {"type": "string", "pattern": "^[A-Z]{3}-[0-9]{4}$", "examples": ["LMP-0003"]},
        "PartAlias": {"$ref": "#/$defs/PartNumber"},
        "semantic_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "route_kind": {"$ref": "#/$defs/semantic_id"},
        "Unused": {"type": "integer"},
    },
    "examples": [{"part": "LMP-0003", "kind": "kernel"}],
}


@pytest.fixture
def contracts_dir(tmp_path: Path) -> Path:
    """The repository's contracts plus a new schema in a new directory."""
    target = tmp_path / CONTRACTS_DIR
    shutil.copytree(REPO_ROOT / CONTRACTS_DIR, target)
    (target / SYNTHETIC_DIR).mkdir()
    (target / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(NEW_SCHEMA, indent=2))
    return target


def test_load_contracts_discovers_every_schema_file(contracts_dir: Path) -> None:
    rel_paths = [contract.rel_path for contract in load_contracts(contracts_dir)]
    assert rel_paths == sorted(rel_paths)
    assert {
        "provider/protocol.schema.json",
        "provider/manifest.schema.json",
        f"{SYNTHETIC_DIR}/widget.schema.json",
    } <= set(rel_paths)


def test_load_contracts_refuses_an_absolute_ref(contracts_dir: Path) -> None:
    schema = {**NEW_SCHEMA, "properties": {"part": {"$ref": "https://example.com/other.schema.json"}}}
    (contracts_dir / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(schema))
    with pytest.raises(ContractSourceError, match="must be relative"):
        load_contracts(contracts_dir)


def test_python_models_cover_a_new_schema_without_generator_changes(
    contracts_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contracts = load_contracts(contracts_dir)
    out = tmp_path / "out" / "generated_models"
    write_python(contracts, contracts_dir, out)
    header = (out / SYNTHETIC_PACKAGE / "widget_schema.py").read_text().splitlines()[:2]
    assert header[1] == f"# Source: contracts/{SYNTHETIC_DIR}/widget.schema.json"
    write_schemas(contracts, contracts_dir, tmp_path / "schemas")
    assert (tmp_path / "schemas" / SYNTHETIC_DIR / "widget.schema.json").read_bytes() == (
        contracts_dir / SYNTHETIC_DIR / "widget.schema.json"
    ).read_bytes()
    # The module imports, so its $ref into ../provider/protocol became a working cross-package import.
    monkeypatch.syspath_prepend(str(out.parent))
    try:
        importlib.import_module(f"generated_models.{SYNTHETIC_PACKAGE}.widget_schema")
    finally:
        for name in [name for name in sys.modules if name.startswith("generated_models")]:
            del sys.modules[name]


def test_fixtures_hold_valid_examples_and_rejected_mutations(contracts_dir: Path, tmp_path: Path) -> None:
    contracts = load_contracts(contracts_dir)
    write_examples(contracts, tmp_path)
    registry = contract_registry(contracts)
    document = json.loads((tmp_path / SYNTHETIC_DIR / "widget.examples.json").read_text())
    assert document["$comment"].endswith(f"Source: contracts/{SYNTHETIC_DIR}/widget.schema.json")
    cases = {case["schema_id"]: case for case in document["cases"]}
    assert set(cases) == {NEW_ID, f"{NEW_ID}#/$defs/PartNumber"}
    for schema_id, case in cases.items():
        validator = ContractValidator({"$ref": schema_id}, registry=registry)
        assert case["valid"] and all(validator.is_valid(example) for example in case["valid"])
        assert case["invalid"] and not any(
            validator.is_valid(fixture["instance"]) for fixture in case["invalid"]
        )
    root_mutations = {(fixture["mutation"], fixture["pointer"]) for fixture in cases[NEW_ID]["invalid"]}
    assert root_mutations == {
        ("remove-property", "/part"),
        ("add-unknown-property", "/x-conformance-unknown"),
        ("wrong-type", "/part"),
    }
    assert cases[f"{NEW_ID}#/$defs/PartNumber"]["invalid"] == [
        {"example": 0, "mutation": "wrong-type", "pointer": "", "instance": 12345}
    ]


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"examples": [{"part": "lowercase"}]}, r"widget\.schema\.json: examples\[0\] doesn't validate"),
        (
            {"properties": {**NEW_SCHEMA["properties"], "note": {"type": "string", "examples": [3]}}},
            r"widget\.schema\.json#/properties/note: examples\[0\] doesn't validate",
        ),
        (
            {
                "$defs": {
                    **NEW_SCHEMA["$defs"],
                    "Loose": {"anyOf": [{"type": "string"}, {}], "examples": ["x"]},
                }
            },
            r"#/\$defs/Loose: no mutation of its examples is rejected",
        ),
    ],
    ids=["invalid-root-example", "invalid-nested-example", "no-invalid-fixture"],
)
def test_examples_that_cant_be_fixtures_fail_generation(
    contracts_dir: Path, tmp_path: Path, changes: dict[str, Any], message: str
) -> None:
    schema = {**NEW_SCHEMA, **changes}
    (contracts_dir / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(schema))
    with pytest.raises(ExampleError, match=message):
        write_examples(load_contracts(contracts_dir), tmp_path)


def test_docs_render_each_contract_and_an_index(contracts_dir: Path, tmp_path: Path) -> None:
    write_docs(load_contracts(contracts_dir), tmp_path)
    page = (tmp_path / SYNTHETIC_DIR / "widget.md").read_text()
    assert page.startswith("# widget\n\nGenerated by tools/gen (`just contracts`). Do not edit.")
    assert f"](../../../../contracts/{SYNTHETIC_DIR}/widget.schema.json)" in page
    assert "| `part` | [`PartNumber`](#partnumber) | yes |" in page
    assert "| `kind` | [`HookKind`](../provider/protocol.md#hookkind) | no |" in page
    assert "### `Unused`" in page
    assert f"[widget]({SYNTHETIC_DIR}/widget.md)" in (tmp_path / "README.md").read_text()


@needs_node
def test_typescript_exports_a_type_and_a_validator_per_def(contracts_dir: Path, tmp_path: Path) -> None:
    """The generator fails on a $def without a type; the types it writes compile, aliases included."""
    out = tmp_path / "contracts"
    contracts = load_contracts(contracts_dir)
    write_typescript(contracts, contracts_dir, out)
    for contract in contracts:
        types = (out / f"{contract.stem}.ts").read_text()
        validators = (out / f"{contract.stem}.validate.d.ts").read_text()
        assert types.startswith(
            f"// Generated by tools/gen (`just contracts`). Do not edit.\n// Source: {contract.source}\n"
        )
        for name in contract.schema.get("$defs", {}):
            assert f"export declare const validate{name}: ValidateFunction;" in validators
    widget = (out / SYNTHETIC_DIR / "widget.ts").read_text()
    # The compiler names snake_case $defs in PascalCase; an alias must use those names too.
    for name in ("PartNumber", "PartAlias", "SemanticId", "RouteKind"):
        assert re.search(rf"^export (type|interface) {name}\b", widget, re.M), name
    tsconfig = {
        "compilerOptions": {"module": "NodeNext", "strict": True, "noEmit": True, "skipLibCheck": True},
        "include": ["contracts/**/*.ts"],
    }
    (tmp_path / "tsconfig.json").write_text(json.dumps(tsconfig))
    tsc = REPO_ROOT / "ui" / "shared" / "node_modules" / ".bin" / "tsc"
    result = subprocess.run([str(tsc), "-p", str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


@needs_node
def test_ajv_validators_accept_examples_and_reject_fixtures(tmp_path: Path) -> None:
    """The generated ESM validators load in Node and agree with the Python fixtures."""
    examples_root = REPO_ROOT / EXAMPLES_OUT
    script = """
import { readFileSync } from "node:fs";
const [modulePath, fixturePath] = process.argv.slice(2);
const validators = await import(modulePath);
const results = [];
for (const testCase of JSON.parse(readFileSync(fixturePath, "utf8")).cases) {
  const name = "validate" + (testCase.schema_id.split("#/$defs/")[1] ?? "");
  const check = validators[name];
  results.push({
    name,
    valid: testCase.valid.map((instance) => check(instance)),
    invalid: testCase.invalid.map((fixture) => check(fixture.instance)),
  });
}
console.log(JSON.stringify(results));
"""
    runner = tmp_path / "run.mjs"
    runner.write_text(script)
    fixtures = sorted(examples_root.rglob("*.examples.json"))
    assert fixtures
    for fixture in fixtures:
        stem = fixture.relative_to(examples_root).as_posix().removesuffix(".examples.json")
        module = REPO_ROOT / TYPESCRIPT_OUT / f"{stem}.validate.js"
        output = subprocess.run(
            ["node", str(runner), module.as_uri(), str(fixture)], capture_output=True, text=True, check=True
        ).stdout
        for result in json.loads(output):
            assert all(result["valid"]), result
            assert not any(result["invalid"]), result


PROTOCOL_ID = "https://benchhand.github.io/benchhand/contracts/provider/protocol.schema.json"
EDGE_CASES: list[tuple[str, Any, bool]] = [
    ("HookId", "kernel", True),
    ("HookId", "kernel\n", False),  # Python's re lets $ match before a final newline; ECMAScript doesn't
    ("ProgressParams", {"id": 1, "fraction": 0.5}, True),
    ("ProgressParams", {"id": 1, "fraction": 2}, False),
    ("ProgressParams", {"id": 1, "fraction": float("nan")}, False),
    ("ProgressParams", {"id": 1, "fraction": float("inf")}, False),
]


def _python_accepts(name: str, instance: Any) -> bool:
    try:
        validate(f"{PROTOCOL_ID}#/$defs/{name}", instance)
    except ContractViolation:
        return False
    return True


@needs_node
def test_python_and_ajv_validators_agree_on_edge_cases(tmp_path: Path) -> None:
    # json.dumps writes NaN and Infinity as the JavaScript literals, so the cases are a JS expression.
    cases = json.dumps([[name, instance] for name, instance, _ in EDGE_CASES])
    runner = tmp_path / "run.mjs"
    runner.write_text(
        "const validators = await import(process.argv[2]);\n"
        f"const cases = {cases};\n"
        "console.log(JSON.stringify(cases.map(([name, value]) => validators['validate' + name](value))));\n"
    )
    module = REPO_ROOT / TYPESCRIPT_OUT / "provider" / "protocol.validate.js"
    output = subprocess.run(
        ["node", str(runner), module.as_uri()], capture_output=True, text=True, check=True
    ).stdout
    expected = [valid for _, _, valid in EDGE_CASES]
    assert json.loads(output) == expected
    assert [_python_accepts(name, instance) for name, instance, _ in EDGE_CASES] == expected


@needs_node
def test_generation_is_deterministic_and_drift_is_reported(contracts_dir: Path, tmp_path: Path) -> None:
    tree = tmp_path / "tree"
    generate(tree, contracts_dir)
    assert drift(tree, contracts_dir) == []
    model = tree / MODELS_OUT / SYNTHETIC_PACKAGE / "widget_schema.py"
    model.write_text(model.read_text() + "# hand edit\n")
    (tree / TYPESCRIPT_OUT / "stray.ts").write_text("")
    (tree / DOCS_OUT / SYNTHETIC_DIR / "widget.md").unlink()
    assert drift(tree, contracts_dir) == [
        f"changed  {MODELS_OUT}/{SYNTHETIC_PACKAGE}/widget_schema.py",
        f"extra    {TYPESCRIPT_OUT}/stray.ts",
        f"missing  {DOCS_OUT}/{SYNTHETIC_DIR}/widget.md",
    ]

    # A failed regeneration leaves the previous outputs in place.
    schema = {**NEW_SCHEMA, "examples": [{"part": "lowercase"}]}
    (contracts_dir / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(schema))
    with pytest.raises(ExampleError):
        generate(tree, contracts_dir)
    assert model.read_text().endswith("# hand edit\n")
    assert (tree / TYPESCRIPT_OUT / "stray.ts").is_file()
