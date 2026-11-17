#!/usr/bin/env python3
"""Every `default` and every `examples` entry of every bundled schema validates against the subschema that
carries it, resolved through the shared registry so `$ref`s work."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

SKILL = Path(__file__).resolve().parents[1]


def load(name: str, path: Path) -> Any:
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, path)
        assert spec and spec.loader
        sys.modules[name] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules[name])
    return sys.modules[name]


registry = load("cad_record_schema_registry", SKILL / "scripts" / "schema_registry.py")

_SCHEMA = ("items", "additionalProperties", "unevaluatedProperties", "unevaluatedItems", "contains", "not",
           "if", "then", "else", "propertyNames", "contentSchema", "additionalItems")
_SCHEMA_LIST = ("prefixItems", "allOf", "anyOf", "oneOf")
_SCHEMA_MAP = ("properties", "patternProperties", "$defs", "definitions", "dependentSchemas")


def subschemas(node: Any, pointer: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Walks `node` and yields each schema object with its JSON pointer. The data keywords (default,
    examples, const, enum) hold values, not schemas, so the walk skips them."""
    if not isinstance(node, dict):
        return
    yield pointer, node
    for key in _SCHEMA:
        yield from subschemas(node.get(key), f"{pointer}/{key}")
    for key in _SCHEMA_LIST:
        for index, child in enumerate(node.get(key) or ()):
            yield from subschemas(child, f"{pointer}/{key}/{index}")
    for key in _SCHEMA_MAP:
        for name, child in (node.get(key) or {}).items():
            yield from subschemas(child, f"{pointer}/{key}/{name.replace('~', '~0').replace('/', '~1')}")


def check_values(root: Path, name: str, *, also: tuple[Path, ...] = ()) -> tuple[int, list[str]]:
    """(values checked, one message per failure) for the `default` and `examples` entries of `root/name`."""
    document = registry.schema(root, name)
    checked = 0
    failures: list[str] = []
    for pointer, node in subschemas(document):
        values = [("default", node["default"])] if "default" in node else []
        values += [(f"examples/{index}", value) for index, value in enumerate(node.get("examples") or ())]
        if not values:
            continue
        validator = registry.ref_validator(root, f"{document['$id']}#{quote(pointer)}", also=also)
        for where, value in values:
            checked += 1
            keyword, _, index = where.partition("/")
            path = f"{pointer}/{keyword}" + (f"/{index}" if index else "")
            failures += [f"{name}#{path}: {error.message}" for error in validator.iter_errors(value)]
    return checked, failures


def assert_no_failures(case: unittest.TestCase, failures: list[str]) -> None:
    """Fails with every message on its own line. A plain assertEqual would cut a long list at maxDiff."""
    if failures:
        case.fail("\n".join(failures))


class WalkerBites(unittest.TestCase):
    """The check reports a wrong default or example, in a nested subschema and through a `$ref`."""

    def check(self, schema: dict[str, Any]) -> tuple[int, list[str]]:
        temporary = tempfile.TemporaryDirectory(prefix="cad-schema-defaults-")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "probe.schema.json").write_text(json.dumps(schema), encoding="utf-8")
        return check_values(root, "probe.schema.json")

    def test_every_invalid_value_is_reported_with_its_pointer(self) -> None:
        checked, failures = self.check({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://srobroek.com/cad/schemas/probe.schema.json",
            "type": "object",
            "properties": {
                "good": {"type": "string", "default": "a", "examples": ["b"]},
                "count": {"type": "integer", "default": "three", "examples": [1, "two", 3, "four"]},
                "named": {"$ref": "#/$defs/name", "default": 7},
                "list": {"type": "array", "items": {"type": "integer", "default": "x"}},
                "a/b": {"allOf": [{"type": "boolean", "default": 1}]},
            },
            "$defs": {"name": {"type": "string", "minLength": 2, "examples": ["x"]}},
        })
        self.assertEqual(checked, 11)
        reported = sorted(failure.split(": ")[0] for failure in failures)
        self.assertEqual(reported, [
            "probe.schema.json#/$defs/name/examples/0",
            "probe.schema.json#/properties/a~1b/allOf/0/default",
            "probe.schema.json#/properties/count/default",
            "probe.schema.json#/properties/count/examples/1",
            "probe.schema.json#/properties/count/examples/3",
            "probe.schema.json#/properties/list/items/default",
            "probe.schema.json#/properties/named/default",
        ])

    def test_a_long_failure_list_is_reported_in_full(self) -> None:
        properties = {f"property_{number:02d}": {"type": "integer", "default": "x"} for number in range(30)}
        _checked, failures = self.check({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://srobroek.com/cad/schemas/probe.schema.json",
            "type": "object",
            "properties": properties,
        })
        self.assertEqual(len(failures), 30)
        with self.assertRaises(AssertionError) as raised:
            assert_no_failures(self, failures)
        message = str(raised.exception)
        for name in properties:
            self.assertIn(f"probe.schema.json#/properties/{name}/default", message)

    def test_valid_values_report_nothing(self) -> None:
        checked, failures = self.check({
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://srobroek.com/cad/schemas/probe.schema.json",
            "type": "object",
            "properties": {"mode": {"enum": ["a", "b"], "default": "a", "examples": ["a", "b"]}},
        })
        self.assertEqual((checked, failures), (3, []))


class BundledSchemas(unittest.TestCase):
    def test_every_default_and_example_validates_against_its_subschema(self) -> None:
        directories = (registry.SCHEMAS, registry.CONCEPT_SCHEMAS)
        found = {directory: sorted(path.name for path in directory.glob("*.schema.json")) for directory in directories}
        for directory, names in found.items():
            self.assertTrue(names, f"no schemas in {directory}")
        checked = 0
        failures: list[str] = []
        for directory, names in found.items():
            other = tuple(entry for entry in directories if entry != directory)
            for name in names:
                count, problems = check_values(directory, name, also=other)
                checked += count
                failures += [f"{directory.name}/{problem}" for problem in problems]
        self.assertGreater(checked, 0, "no default or examples value found: the walk is vacuous")
        assert_no_failures(self, failures)
        print(f"checked {checked} values across {sum(map(len, found.values()))} schemas", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
