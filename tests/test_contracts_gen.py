# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The contract generator in tools/gen (ADR-0017): TypeSpec to the published schemas, then the models,
fixtures, TypeScript and docs generated from those, and drift."""

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
from contracts_gen.docs import type_expr, write_docs
from contracts_gen.emit import TSP, TypeSpecError, read_source, write_published_schemas
from contracts_gen.examples import ExampleError, contract_registry, write_examples
from contracts_gen.generate import drift, generate
from contracts_gen.python_models import write_python
from contracts_gen.sources import (
    CONTRACTS_DIR,
    DOCS_OUT,
    EXAMPLES_OUT,
    MODELS_OUT,
    REPO_ROOT,
    SCHEMAS_OUT,
    TYPESCRIPT_OUT,
    ContractSourceError,
    load_contracts,
)
from contracts_gen.typescript import write_typescript

NODE_READY = (
    shutil.which("node") is not None
    and all(
        (REPO_ROOT / "ui" / "shared" / "node_modules" / name).is_dir()
        for name in ("ajv", "json-schema-to-typescript")
    )
    and (REPO_ROOT / CONTRACTS_DIR / TSP).is_file()
)
needs_node = pytest.mark.skipif(not NODE_READY, reason="needs node and `pnpm install` in ui/ and contracts/")

# A directory no real contract uses, so the copied contracts tree can never already have it.
SYNTHETIC_DIR = "generator-test"
SYNTHETIC_PACKAGE = "generator_test"  # datamodel-codegen's module name for SYNTHETIC_DIR
NEW_ID = f"https://benchhand.github.io/benchhand/contracts/{SYNTHETIC_DIR}/widget.schema.json"
NEW_SOURCE = f"contracts/{SYNTHETIC_DIR}/widget.tsp"
NEW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": NEW_ID,
    "title": "widget",
    "x-version": "1.0.0",
    "type": "object",
    "properties": {
        "part": {"$ref": "#/$defs/PartNumber"},
        "kind": {"$ref": "../provider/protocol.schema.json#/$defs/HookKind"},
        "notes": {"type": "object", "properties": {"text": {"type": "string"}}},
    },
    "required": ["part"],
    "additionalProperties": False,
    "allOf": [{"if": {"required": ["kind"]}, "then": {"required": ["part"]}}],
    "$defs": {
        "PartNumber": {"type": "string", "pattern": "^[A-Z]{3}-[0-9]{4}$", "examples": ["LMP-0003"]},
        "PartAlias": {"$ref": "#/$defs/PartNumber"},
        "semantic_id": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
        "route_kind": {"$ref": "#/$defs/semantic_id"},
        "Unused": {"type": "integer"},
    },
    "examples": [{"part": "LMP-0003", "kind": "kernel"}],
}


# NEW_SCHEMA's core, as TypeSpec: a closed root with a local and a cross-contract $ref, a condition, an open
# nested object, and examples.
NEW_TYPESPEC = f"""import "@typespec/json-schema";
import "../provider/protocol.tsp";

using TypeSpec.JsonSchema;

@jsonSchema
@baseUri("https://benchhand.github.io/benchhand/contracts/{SYNTHETIC_DIR}/widget/")
namespace GeneratorTest.Widget;

/** A widget. */
@summary("widget")
@id("{NEW_ID}")
@extension("x-version", "1.0.0")
@extension("allOf", #[#{{ `if`: #{{ required: #["kind"] }}, `then`: #{{ required: #["part"] }} }}])
model Widget {{
  part: PartNumber;
  kind?: Provider.Protocol.HookKind;
  notes?: {{
    text?: string;
    ...Record<unknown>;
  }};
}}

@example("LMP-0003")
@pattern("^[A-Z]{{3}}-[0-9]{{4}}$")
scalar PartNumber extends string;

@@example(Widget, #{{ part: "LMP-0003", kind: "kernel" }});
"""


@pytest.fixture
def schemas_dir(tmp_path: Path) -> Path:
    """The published schemas plus a new one in a new directory: the input of every generator after emit."""
    target = tmp_path / "schemas"
    shutil.copytree(REPO_ROOT / SCHEMAS_OUT, target)
    (target / SYNTHETIC_DIR).mkdir()
    (target / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(NEW_SCHEMA, indent=2))
    return target


@pytest.fixture
def contracts_dir(tmp_path: Path) -> Path:
    """The repository's TypeSpec contracts plus a new contract in a new directory."""
    target = tmp_path / CONTRACTS_DIR
    source = REPO_ROOT / CONTRACTS_DIR
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("node_modules", "tsp-output"))
    (target / "node_modules").symlink_to(source / "node_modules")
    (target / SYNTHETIC_DIR).mkdir()
    _write_widget(target, NEW_TYPESPEC)
    main = target / "main.tsp"
    main.write_text(main.read_text() + f'import "./{SYNTHETIC_DIR}/widget.tsp";\n')
    return target


def _write_widget(contracts_dir: Path, source: str) -> None:
    (contracts_dir / SYNTHETIC_DIR / "widget.tsp").write_text(source)


def test_load_contracts_discovers_every_schema_file(schemas_dir: Path) -> None:
    rel_paths = [contract.rel_path for contract in load_contracts(schemas_dir)]
    assert rel_paths == sorted(rel_paths)
    assert {
        "provider/protocol.schema.json",
        "provider/manifest.schema.json",
        f"{SYNTHETIC_DIR}/widget.schema.json",
    } <= set(rel_paths)


def test_load_contracts_refuses_an_absolute_ref(schemas_dir: Path) -> None:
    schema = {**NEW_SCHEMA, "properties": {"part": {"$ref": "https://example.com/other.schema.json"}}}
    (schemas_dir / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(schema))
    with pytest.raises(ContractSourceError, match="must be relative"):
        load_contracts(schemas_dir)


@pytest.mark.parametrize(
    "prop",
    [
        {"type": "string", "description": "A CEL guard"},
        {"type": "array", "description": "CEL requirements", "items": {"type": "string"}},
    ],
)
def test_load_contracts_refuses_a_cel_expression_that_is_a_plain_string(schemas_dir: Path, prop: Any) -> None:
    schema = {**NEW_SCHEMA, "properties": {"guard": prop}}
    (schemas_dir / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(schema))
    with pytest.raises(ContractSourceError, match="#/properties/guard: a CEL expression is a plain string"):
        load_contracts(schemas_dir)


def test_load_contracts_takes_a_cel_expression_that_refers_to_the_cel_type(schemas_dir: Path) -> None:
    prop = {"description": "A CEL guard", "$ref": "../common/cel.schema.json#/$defs/CelExpression"}
    schema = {**NEW_SCHEMA, "properties": {"guard": prop}}
    (schemas_dir / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(schema))
    assert f"{SYNTHETIC_DIR}/widget.schema.json" in [
        contract.rel_path for contract in load_contracts(schemas_dir)
    ]


@pytest.mark.parametrize("keyword", ["examples", "default", "const", "enum", "x-payload"])
def test_load_contracts_does_not_lint_instance_data_that_looks_like_a_cel_schema(
    schemas_dir: Path, keyword: str
) -> None:
    payload = {"description": "CEL output", "type": "string"}
    data = [payload] if keyword in ("examples", "enum") else payload
    schema = {**NEW_SCHEMA, "properties": {"payload": {"type": "object", keyword: data}}}
    (schemas_dir / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(schema))
    assert f"{SYNTHETIC_DIR}/widget.schema.json" in [
        contract.rel_path for contract in load_contracts(schemas_dir)
    ]


def test_load_contracts_lints_a_property_named_like_a_data_keyword(schemas_dir: Path) -> None:
    schema = {**NEW_SCHEMA, "properties": {"default": {"type": "string", "description": "A CEL guard"}}}
    (schemas_dir / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(schema))
    with pytest.raises(ContractSourceError, match="#/properties/default: a CEL expression is a plain string"):
        load_contracts(schemas_dir)


@needs_node
def test_a_typespec_contract_is_published_under_its_id_with_file_relative_refs(
    contracts_dir: Path, tmp_path: Path
) -> None:
    write_published_schemas(contracts_dir, tmp_path)
    published = json.loads((tmp_path / SYNTHETIC_DIR / "widget.schema.json").read_text())
    assert published == {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": NEW_ID,
        "title": "widget",
        "description": "A widget.",
        "x-version": "1.0.0",
        "type": "object",
        "properties": {
            "part": {"$ref": "#/$defs/PartNumber"},
            "kind": {"$ref": "../provider/protocol.schema.json#/$defs/HookKind"},
            "notes": {"type": "object", "properties": {"text": {"type": "string"}}},
        },
        "required": ["part"],
        "additionalProperties": False,
        "allOf": NEW_SCHEMA["allOf"],
        "examples": NEW_SCHEMA["examples"],
        "$defs": {"PartNumber": NEW_SCHEMA["$defs"]["PartNumber"]},
    }
    # The repository's own contracts come out as they are published.
    for path in sorted((REPO_ROOT / SCHEMAS_OUT).rglob("*.schema.json")):
        rel_path = path.relative_to(REPO_ROOT / SCHEMAS_OUT)
        assert (tmp_path / rel_path).read_bytes() == path.read_bytes(), rel_path


@needs_node
def test_the_compiler_lists_the_declarations_in_source_order(contracts_dir: Path) -> None:
    # The TypeSpec compiler reads the names, so a backticked name, an @id and a template need no parser of
    # our own; a template isn't a declaration until it is instantiated, and its instance is inlined. A
    # relative @id resolves against the namespace's @baseUri, as the emitter resolves it.
    extra = (
        "\nmodel Box<T> {\n  value: T;\n}\n\n"
        '@id("https://benchhand.github.io/benchhand/contracts/generator-test/widget/renamed.json")\n'
        "model Original {\n  box: Box<string>;\n}\n\nscalar `then` extends string;\n"
        '\n@id("relative.json")\nscalar Relative extends string;\n'
    )
    _write_widget(contracts_dir, NEW_TYPESPEC + extra)
    widget = f"{NEW_ID.removesuffix('.schema.json')}/"
    ids = [schema_id for schema_id in read_source(contracts_dir).ids if schema_id.startswith(widget[:-1])]
    assert ids == [
        NEW_ID,
        f"{widget}PartNumber.json",
        f"{widget}renamed.json",
        f"{widget}then.json",
        f"{widget}relative.json",
    ]


@needs_node
def test_a_typespec_warning_fails_the_compile(contracts_dir: Path, tmp_path: Path) -> None:
    # The JSON Schema emitter warns about a scalar it can't map; --warn-as-error makes that a failure.
    _write_widget(
        contracts_dir, NEW_TYPESPEC + "\nscalar Unmapped;\n\nmodel Holder {\n  value: Unmapped;\n}\n"
    )
    with pytest.raises(TypeSpecError, match="unknown-scalar"):
        write_published_schemas(contracts_dir, tmp_path)


def test_python_models_cover_a_new_schema_without_generator_changes(
    schemas_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contracts = load_contracts(schemas_dir)
    out = tmp_path / "out" / "generated_models"
    write_python(contracts, schemas_dir, out)
    header = (out / SYNTHETIC_PACKAGE / "widget_schema.py").read_text().splitlines()[:2]
    assert header[1] == f"# Source: {NEW_SOURCE}"
    # The module imports, so its $ref into ../provider/protocol became a working cross-package import.
    monkeypatch.syspath_prepend(str(out.parent))
    try:
        widget = importlib.import_module(f"generated_models.{SYNTHETIC_PACKAGE}.widget_schema").Widget
        # An object the schema leaves open keeps the keys it doesn't name; a closed one refuses them.
        notes = {"text": "keep", "author": "sjors"}
        assert widget.model_validate({"part": "LMP-0003", "notes": notes}).model_dump(
            mode="json", exclude_unset=True
        ) == {"part": "LMP-0003", "notes": notes}
        with pytest.raises(ValueError, match="Extra inputs"):
            widget.model_validate({"part": "LMP-0003", "colour": "red"})
    finally:
        for name in [name for name in sys.modules if name.startswith("generated_models")]:
            del sys.modules[name]


def test_fixtures_hold_valid_examples_and_rejected_mutations(schemas_dir: Path, tmp_path: Path) -> None:
    contracts = load_contracts(schemas_dir)
    write_examples(contracts, tmp_path)
    registry = contract_registry(contracts)
    document = json.loads((tmp_path / SYNTHETIC_DIR / "widget.examples.json").read_text())
    assert document["$comment"].endswith(f"Source: {NEW_SOURCE}")
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
    schemas_dir: Path, tmp_path: Path, changes: dict[str, Any], message: str
) -> None:
    schema = {**NEW_SCHEMA, **changes}
    (schemas_dir / SYNTHETIC_DIR / "widget.schema.json").write_text(json.dumps(schema))
    with pytest.raises(ExampleError, match=message):
        write_examples(load_contracts(schemas_dir), tmp_path)


def test_docs_render_each_contract_and_an_index(schemas_dir: Path, tmp_path: Path) -> None:
    write_docs(load_contracts(schemas_dir), tmp_path)
    page = (tmp_path / SYNTHETIC_DIR / "widget.md").read_text()
    assert page.startswith("# widget\n\nGenerated by tools/gen (`just contracts`). Do not edit.")
    assert f"](../../../../{NEW_SOURCE})" in page
    assert "| `part` | [`PartNumber`](#partnumber) | yes |" in page
    assert "| `kind` | [`HookKind`](../provider/protocol.md#hookkind) | no |" in page
    assert "### `Unused`" in page
    assert "Type: object\n" in page  # the allOf of conditions doesn't hide the type
    assert 'Condition:\n\n```json\n{\n  "if": {\n    "required": [\n      "kind"' in page
    assert f"[widget]({SYNTHETIC_DIR}/widget.md)" in (tmp_path / "README.md").read_text()


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        ("common.schema.json#/$defs/Decision", "[`Decision`](common.md#decision)"),
        # A property has a table row, not a heading, so its link has no anchor.
        ("part.schema.json#/properties/transparency", "[`part.transparency`](part.md)"),
        ("#/properties/transparency", "`transparency`"),
    ],
)
def test_docs_link_a_ref_only_to_an_anchor_that_exists(ref: str, expected: str) -> None:
    assert type_expr({"$ref": ref}, None) == expected  # pyright: ignore[reportArgumentType]


def _descriptions(node: Any, pointer: str = "") -> list[tuple[str, str]]:
    if isinstance(node, list):
        return [
            found for index, item in enumerate(node) for found in _descriptions(item, f"{pointer}/{index}")
        ]
    if not isinstance(node, dict):
        return []
    found = [(pointer, node["description"])] if isinstance(node.get("description"), str) else []
    for key, value in node.items():
        if key not in ("description", "examples", "const", "enum", "default"):
            found += _descriptions(value, f"{pointer}/{key}")
    return found


def test_docs_show_every_description(tmp_path: Path) -> None:
    """Some generators drop descriptions (ADR-0017); the reference docs carry every one of them."""
    contracts = load_contracts(REPO_ROOT / SCHEMAS_OUT)
    write_docs(contracts, tmp_path)
    missing = []
    for contract in contracts:
        page = (tmp_path / f"{contract.stem}.md").read_text()
        for pointer, text in _descriptions(contract.schema):
            shown = (text, text.replace("|", "\\|").replace("\n", " "), json.dumps(text, ensure_ascii=False))
            if not any(form in page for form in shown):
                missing.append(f"{contract.rel_path}#{pointer}")
    assert missing == []


def test_docs_say_which_branch_requires_a_property(tmp_path: Path) -> None:
    """A drawing's coordinate_frame origin is one of two objects, each requiring its own property; the table
    says which, so a reader doesn't take both as required."""
    contracts = load_contracts(REPO_ROOT / SCHEMAS_OUT)
    write_docs(contracts, tmp_path)
    rows = {
        row.split(" | ")[0].strip("| `"): row.split(" | ")[2]
        for row in (tmp_path / "record" / "drawing.md").read_text().splitlines()
        if row.startswith("| `coordinate_frame")
    }
    assert rows["coordinate_frame.origin"] == "yes"
    assert rows["coordinate_frame.origin.intersection"] == "yes (oneOf branch 1 of 2)"
    assert rows["coordinate_frame.origin.at"] == "yes (oneOf branch 2 of 2)"
    assert rows["coordinate_frame.x"] == "no"


@needs_node
def test_typescript_exports_a_type_and_a_validator_per_def(schemas_dir: Path, tmp_path: Path) -> None:
    """The generator fails on a $def without a type; the types it writes compile, aliases included."""
    out = tmp_path / "contracts"
    contracts = load_contracts(schemas_dir)
    write_typescript(contracts, schemas_dir, out)
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


CONTRACTS_BASE = "https://benchhand.github.io/benchhand/contracts/"
EDGE_CASES: list[tuple[str, str, Any, bool]] = [
    ("provider/protocol", "HookId", "kernel", True),
    # Python's re lets $ match before a final newline; ECMAScript doesn't
    ("provider/protocol", "HookId", "kernel\n", False),
    ("provider/protocol", "ProgressParams", {"id": 1, "fraction": 0.5}, True),
    ("provider/protocol", "ProgressParams", {"id": 1, "fraction": 2}, False),
    ("provider/protocol", "ProgressParams", {"id": 1, "fraction": float("nan")}, False),
    ("provider/protocol", "ProgressParams", {"id": 1, "fraction": float("inf")}, False),
    # A date-time has an uppercase T and an explicit offset (ADR-0017): some parsers refuse t and z.
    ("jobs/job", "Timestamp", "2026-11-25T05:08:13Z", True),
    ("jobs/job", "Timestamp", "2026-11-25T05:08:13.134+01:00", True),
    ("jobs/job", "Timestamp", "2026-11-25t05:08:13Z", False),
    ("jobs/job", "Timestamp", "2026-11-25T05:08:13z", False),
    ("jobs/job", "Timestamp", "2026-11-25 05:08:13Z", False),
]


def _python_accepts(stem: str, name: str, instance: Any) -> bool:
    try:
        validate(f"{CONTRACTS_BASE}{stem}.schema.json#/$defs/{name}", instance)
    except ContractViolation:
        return False
    return True


@needs_node
def test_python_and_ajv_validators_agree_on_edge_cases(tmp_path: Path) -> None:
    # json.dumps writes NaN and Infinity as the JavaScript literals, so the cases are a JS expression.
    modules = {stem: (REPO_ROOT / TYPESCRIPT_OUT / f"{stem}.validate.js").as_uri() for stem, *_ in EDGE_CASES}
    cases = json.dumps([[modules[stem], name, instance] for stem, name, instance, _ in EDGE_CASES])
    runner = tmp_path / "run.mjs"
    runner.write_text(
        f"const cases = {cases};\n"
        "const results = [];\n"
        "for (const [module, name, value] of cases) {\n"
        "  results.push((await import(module))['validate' + name](value));\n"
        "}\n"
        "console.log(JSON.stringify(results));\n"
    )
    output = subprocess.run(["node", str(runner)], capture_output=True, text=True, check=True).stdout
    expected = [valid for *_, valid in EDGE_CASES]
    assert json.loads(output) == expected
    assert [_python_accepts(stem, name, instance) for stem, name, instance, _ in EDGE_CASES] == expected


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
    _write_widget(contracts_dir, NEW_TYPESPEC.replace('part: "LMP-0003", kind', 'part: "lowercase", kind'))
    with pytest.raises(ExampleError):
        generate(tree, contracts_dir)
    assert model.read_text().endswith("# hand edit\n")
    assert (tree / TYPESCRIPT_OUT / "stray.ts").is_file()
