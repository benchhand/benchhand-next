"""Targeted YAML edits keep every other byte, in each layout the prototype writes, and refuse shared nodes."""

from __future__ import annotations

import pytest
from benchhand_core.record.migrate import yaml_edit
from benchhand_core.record.migrate.renames import yaml_keys
from benchhand_core.record.migrate.rules import RULES

A = ("a",)
A_ITEMS = ("a", yaml_edit.ANY)


def _removed(text: str, path: tuple[str, ...], keys: tuple[str, ...] = ("gone",)) -> str:
    document = yaml_edit.Document.parse(text)
    [target] = list(document.mappings_at(path))
    document.remove_entries(target, keys)
    return document.result()


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        (A, "a: {x: 1, gone: 2}\n", "a: {x: 1}\n"),  # the last flow entry
        (A, "a: {gone: 2, x: 1}\n", "a: {x: 1}\n"),  # the first flow entry
        (A, "a: {gone: 2}\n", "a: {}\n"),  # the only flow entry
        (A, "a: {gone: 2,}\n", "a: {}\n"),  # the only flow entry, with a trailing comma
        (A, "a: {x: 1, gone: 2,}\n", "a: {x: 1}\n"),  # the last flow entry, with a trailing comma
        (A, "a: {keep: 1, # keep this note\n  gone: 2}\n", "a: {keep: 1 # keep this note\n  }\n"),
        (A, "a:\n  gone: 2 # note\n  x: 1\n", "a:\n  x: 1\n"),  # a block entry and its comment
        (A, "a:\n  x: 1\n  gone:\n    deep: 1\n\n# kept\nb: 2\n", "a:\n  x: 1\n\n# kept\nb: 2\n"),  # nested
        (A, "a:\n  gone: 2\nb: 3\n", "a:\n  {}\nb: 3\n"),  # the only block entry
        (A_ITEMS, "a:\n- gone: 2\n  x: 1\n", "a:\n- x: 1\n"),  # the first entry after a sequence dash
        (A, "a:\r\n  gone: 2\r\n  x: 1\r\n", "a:\r\n  x: 1\r\n"),  # CRLF
    ],
)
def test_removing_an_entry_keeps_every_other_byte(path: tuple[str, ...], text: str, expected: str) -> None:
    assert _removed(text, path) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("a: {x: [user], c: [], i: []}\n", "a: {x: [user]}\n"),  # adjacent empty lists end the mapping
        ("a: {c: [], i: [], x: 1}\n", "a: {x: 1}\n"),  # adjacent removals before a kept entry
        ("a: {c: [], i: []}\n", "a: {}\n"),
        ("a:\n- c: []\n  i: []\n  x: 1\n", "a:\n- x: 1\n"),  # after a dash, followed by another removal
    ],
)
def test_removing_adjacent_entries_together(text: str, expected: str) -> None:
    path = A_ITEMS if text.startswith("a:\n-") else A
    assert _removed(text, path, ("c", "i")) == expected


@pytest.mark.parametrize(
    "text",
    [
        # an aliased heat_set list shared with a custom field: renaming one would rename both
        "interfaces:\n- limits:\n    heat_set: &hs\n    - {hole_d: 7.7}\n    custom: *hs\n",
        # the mapping itself is anchored
        "interfaces:\n- limits:\n    heat_set:\n    - &one {hole_d: 7.7}\n",
        # a merge key brings in entries the rename cannot see
        "base: &b {hole_d: 7.7}\ninterfaces:\n- limits:\n    heat_set:\n    - {<<: *b, hole_d: 7.8}\n",
    ],
)
def test_a_rename_of_a_shared_node_is_refused_with_its_pointer(text: str) -> None:
    rule = next(rule for rule in RULES if rule.id == "heat-set-keys")
    rewrite = rule.run("hw/interfaces.yaml", text)
    assert rewrite.text == text
    [refusal] = rewrite.findings
    assert (refusal.code, refusal.pointer) == (
        "migrate.unsupported_layout",
        "/interfaces/0/limits/heat_set/0/hole_d",
    )
    assert "anchor" in (refusal.action or "")


def test_an_unshared_anchor_elsewhere_does_not_refuse_a_rename() -> None:
    text = "other: &o {x: 1}\ninterfaces:\n- limits:\n    heat_set:\n    - {hole_d: 7.7}\n"
    rewrite = yaml_keys((("interfaces", "*", "limits", "heat_set", "*"),), {"hole_d": "hole_diameter_mm"})(
        "hw/interfaces.yaml", text
    )
    assert rewrite.text == text.replace("hole_d", "hole_diameter_mm")
