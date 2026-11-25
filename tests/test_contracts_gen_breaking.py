"""The breaking-change check in contracts_gen.breaking, against the rules in docs/contract/versioning.md."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from contracts_gen.breaking import check_against, compare, compare_contracts, last_release_tag
from contracts_gen.sources import SCHEMAS_OUT
from jsonschema import Draft202012Validator

WIDGET_ID = "https://example.invalid/widget.schema.json"
OBJECT: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "maxLength": 40},
        "kind": {"enum": ["kernel", "check"]},
        "count": {"type": "integer", "minimum": 0},
    },
    "required": ["name"],
    "$defs": {"Name": {"type": "string"}},
}


def _with(**changes: Any) -> dict[str, Any]:
    schema = json.loads(json.dumps(OBJECT))
    for pointer, value in changes.items():
        *parents, key = pointer.split("__")
        node = schema
        for part in parents:
            node = node[part]
        if value is None:
            del node[key]
        else:
            node[key] = value
    return schema


@pytest.mark.parametrize(
    ("new", "rule", "pointer"),
    [
        (_with(properties__count=None), "property-removed", "/properties/count"),
        (_with(**{"$defs": {}}), "definition-removed", "/$defs/Name"),
        (_with(required=["name", "kind"]), "required-added", "/required"),
        (_with(properties__kind={"enum": ["kernel"]}), "enum-value-removed", "/properties/kind/enum"),
        (_with(properties__count={"type": "string"}), "type-narrowed", "/properties/count/type"),
        (
            _with(properties__name={"type": "string", "maxLength": 20}),
            "bound-tightened",
            "/properties/name/maxLength",
        ),
        (_with(additionalProperties=False), "schema-closed", "/additionalProperties"),
        (_with(additionalProperties={"type": "string"}), "schema-constrained", "/additionalProperties"),
    ],
    ids=lambda value: value if isinstance(value, str) and not value.startswith("/") else None,
)
def test_compare_reports_a_breaking_change(new: dict[str, Any], rule: str, pointer: str) -> None:
    assert [(change.rule, change.pointer) for change in compare(OBJECT, new)] == [(rule, pointer)]


@pytest.mark.parametrize(
    "new",
    [
        _with(properties__extra={"type": "string"}),
        _with(properties__kind={"enum": ["kernel", "check", "render"]}),
        _with(properties__name={"type": "string", "maxLength": 80}),
        _with(properties__count={"type": "number", "minimum": 0}),
        _with(required=[]),
        _with(**{"$defs": {"Name": {"type": "string"}, "Other": {"type": "integer"}}}),
        _with(description="documentation only"),
    ],
    ids=[
        "optional-property",
        "enum-widened",
        "bound-loosened",
        "type-widened",
        "required-dropped",
        "definition-added",
        "description",
    ],
)
def test_compare_accepts_a_compatible_change(new: dict[str, Any]) -> None:
    assert list(compare(OBJECT, new)) == []


COVERAGE: dict[str, Any] = {
    "type": "object",
    "properties": {"status": {"enum": ["pass", "fail", "unknown"]}, "reason": {"type": "string"}},
    "required": ["status"],
    "additionalProperties": False,
    "allOf": [{"if": {"properties": {"status": {"const": "unknown"}}}, "then": {"required": ["reason"]}}],
}


def _kind(kind: str, **properties: Any) -> dict[str, Any]:
    """An object told apart from the other branches of a oneOf by its required ``kind``."""
    return {
        "type": "object",
        "properties": {"kind": {"const": kind}, "size": {"type": "integer"}, **properties},
        "required": ["kind"],
        "additionalProperties": False,
    }


def _changes(old: dict[str, Any], new: dict[str, Any]) -> list[tuple[str, str]]:
    [report] = compare_contracts({"w.schema.json": old}, {"w.schema.json": new})
    return [(change.rule, change.pointer) for change in report.changes]


@pytest.mark.parametrize(
    ("old", "new", "instance", "rule", "pointer"),
    [
        (
            COVERAGE,
            {**COVERAGE, "allOf": [{**COVERAGE["allOf"][0], "else": {"required": ["reason"]}}]},
            {"status": "pass"},
            "schema-constrained",
            "/allOf/0/else",
        ),
        (
            {"oneOf": [{"type": "integer"}, {"type": "string"}]},
            {"oneOf": [{"type": "integer"}, {"type": "string"}, {"type": "number"}]},
            1,
            "unproven-change",
            "/oneOf",
        ),
        (
            {
                "oneOf": [{"$ref": "#/$defs/Count"}, {"type": "string"}],
                "$defs": {"Count": {"type": "integer"}},
            },
            {"oneOf": [{"$ref": "#/$defs/Count"}, {"type": "string"}], "$defs": {"Count": {}}},
            "text",
            "unproven-change",
            "/$defs/Count",
        ),
        (
            {"not": {"type": "string", "maxLength": 1}},
            {"not": {"type": "string"}},
            "ab",
            "unproven-change",
            "/not",
        ),
        (
            {"if": {"required": ["a"], "properties": {"a": {"const": 1}}}, "then": {"required": ["b"]}},
            {"if": {"required": ["a"]}, "then": {"required": ["b"]}},
            {"a": 2},
            "unproven-change",
            "/if",
        ),
        (
            {"type": "object", "additionalProperties": {"type": "string"}},
            {
                "type": "object",
                "properties": {"x": {"const": "y"}},
                "additionalProperties": {"type": "string"},
            },
            {"x": "z"},
            "const-changed",
            "/properties/x/const",
        ),
        (
            {"prefixItems": [{"type": "string"}]},
            {"prefixItems": [{"type": "string"}, {"type": "integer"}]},
            ["a", "b"],
            "unproven-change",
            "/prefixItems",
        ),
        (
            {"contains": {"type": "string"}, "minContains": 0},
            {"contains": {"type": "string"}},
            [1],
            "bound-tightened",
            "/minContains",
        ),
    ],
    ids=[
        "else-added",
        "overlapping-oneOf-branch",
        "oneOf-target-widened",
        "not-widened",
        "if-widened",
        "property-under-additionalProperties",
        "prefixItems-extended",
        "minContains-default",
    ],
)
def test_a_change_that_rejects_an_old_valid_instance_is_reported(
    old: dict[str, Any], new: dict[str, Any], instance: Any, rule: str, pointer: str
) -> None:
    assert Draft202012Validator(old).is_valid(instance)
    assert not Draft202012Validator(new).is_valid(instance)
    assert _changes(old, new) == [(rule, pointer)]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ({"type": "integer", "oneOf": [{"minimum": 0}, {"maximum": -10}]}, {"type": "integer"}),
        (COVERAGE, {**COVERAGE, "allOf": []}),
        (
            {"oneOf": [{"type": "integer", "description": "a count"}, {"type": "string"}]},
            {"oneOf": [{"type": "integer", "description": "how many"}, {"type": "string"}]},
        ),
        (
            {"properties": {"n": {"$ref": "#/$defs/Count"}}, "$defs": {"Count": {"type": "integer"}}},
            {"properties": {"n": {"$ref": "#/$defs/Count"}}, "$defs": {"Count": {"type": "number"}}},
        ),
        (
            {
                "oneOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}],
                "$defs": {"A": _kind("a"), "B": _kind("b")},
            },
            {
                "oneOf": [{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}, {"$ref": "#/$defs/C"}],
                "$defs": {"A": _kind("a", size={"type": "number"}), "B": _kind("b"), "C": _kind("c")},
            },
        ),
    ],
    ids=[
        "oneOf-removed",
        "conditional-removed",
        "oneOf-description",
        "def-widened-outside-oneOf",
        "discriminated-oneOf-widened",
    ],
)
def test_a_widening_change_is_accepted(old: dict[str, Any], new: dict[str, Any]) -> None:
    assert _changes(old, new) == []


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write_contract(repo: Path, schema: dict[str, Any]) -> None:
    path = repo / SCHEMAS_OUT / "record" / "widget.schema.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema))


@pytest.fixture
def released_repo(tmp_path: Path) -> Path:
    """A repository whose published record/widget.schema.json was released as v1.0.0."""
    _git(tmp_path, "init", "-q")
    _write_contract(tmp_path, {"$id": WIDGET_ID, "x-version": "1.0.0", **OBJECT})
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "release")
    _git(tmp_path, "tag", "v1.0.0")
    return tmp_path


def test_a_breaking_change_needs_a_major_bump_over_the_release_tag(released_repo: Path) -> None:
    assert last_release_tag(released_repo) == "v1.0.0"
    breaking = {"$id": WIDGET_ID, **_with(required=["name", "kind"])}

    _write_contract(released_repo, {**breaking, "x-version": "1.1.0"})
    [report] = check_against(released_repo, "v1.0.0")
    assert not report.allowed
    assert [change.rule for change in report.changes] == ["required-added"]

    _write_contract(released_repo, {**breaking, "x-version": "2.0.0"})
    [report] = check_against(released_repo, "v1.0.0")
    assert report.allowed


def test_removing_a_released_contract_is_breaking(released_repo: Path) -> None:
    (released_repo / SCHEMAS_OUT / "record" / "widget.schema.json").unlink()
    (released_repo / SCHEMAS_OUT / "record" / "other.schema.json").write_text(
        json.dumps({"$id": "https://example.invalid/other.schema.json", **OBJECT})
    )
    [report] = check_against(released_repo, "v1.0.0")
    assert not report.allowed
    assert [change.rule for change in report.changes] == ["schema-removed"]


def test_no_release_tag_means_nothing_to_compare(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    assert last_release_tag(tmp_path) is None
