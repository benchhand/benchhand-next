"""Removing a YAML mapping entry in place keeps every other byte, in each layout the prototype writes."""

from __future__ import annotations

import pytest
from benchhand_core.record.migrate import yaml_edit

A = ("a",)
A_ITEMS = ("a", yaml_edit.ANY)


@pytest.mark.parametrize(
    ("path", "text", "expected"),
    [
        (A, "a: {x: 1, gone: 2}\n", "a: {x: 1}\n"),  # the last flow entry
        (A, "a: {gone: 2, x: 1}\n", "a: {x: 1}\n"),  # the first flow entry
        (A, "a: {gone: 2}\n", "a: {}\n"),  # the only flow entry
        (A, "a:\n  gone: 2 # note\n  x: 1\n", "a:\n  x: 1\n"),  # a block entry and its comment
        (A, "a:\n  x: 1\n  gone:\n    deep: 1\n\n# kept\nb: 2\n", "a:\n  x: 1\n\n# kept\nb: 2\n"),  # nested
        (A, "a:\n  gone: 2\nb: 3\n", "a:\n  {}\nb: 3\n"),  # the only block entry
        (A_ITEMS, "a:\n- gone: 2\n  x: 1\n", "a:\n- x: 1\n"),  # the first entry after a sequence dash
        (A, "a:\r\n  gone: 2\r\n  x: 1\r\n", "a:\r\n  x: 1\r\n"),  # CRLF
    ],
)
def test_remove_entry_keeps_every_other_byte(path: tuple[str, ...], text: str, expected: str) -> None:
    [(_, mapping)] = list(yaml_edit.mappings_at(yaml_edit.compose(text), path))
    assert yaml_edit.apply(text, [yaml_edit.remove_entry(text, mapping, "gone")]) == expected
