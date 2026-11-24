"""The breaking-change check in contracts_gen.breaking, against the rules in docs/contract/versioning.md."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from contracts_gen.breaking import check_against, compare, last_release_tag

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
        (_with(additionalProperties=False), "schema-constrained", "/additionalProperties"),
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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write_contract(repo: Path, schema: dict[str, Any]) -> None:
    path = repo / "contracts" / "record" / "widget.schema.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema))


@pytest.fixture
def released_repo(tmp_path: Path) -> Path:
    """A repository whose contracts/record/widget.schema.json was released as v1.0.0."""
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
    (released_repo / "contracts" / "record" / "widget.schema.json").unlink()
    (released_repo / "contracts" / "record" / "other.schema.json").write_text(
        json.dumps({"$id": "https://example.invalid/other.schema.json", **OBJECT})
    )
    [report] = check_against(released_repo, "v1.0.0")
    assert not report.allowed
    assert [change.rule for change in report.changes] == ["schema-removed"]


def test_no_release_tag_means_nothing_to_compare(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
    assert last_release_tag(tmp_path) is None
