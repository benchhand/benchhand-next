"""Targeted edits of YAML text: rename a key, replace a scalar, remove a mapping entry.

Each edit is a splice at the character positions PyYAML's composer reports for the nodes it touches, so every
other byte of the file (comments, key order, quoting, flow or block style, indentation, line endings) stays as
written. A round-trip dump through a YAML library would re-flow the flow mappings the prototype writes.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from benchhand_core.record.formats import FormatError

ANY = "*"  # a path step that matches every item of a sequence or every value of a mapping


@dataclass(frozen=True, order=True)
class Splice:
    """Replace text[start:end] with `text`."""

    start: int
    end: int
    text: str


def compose(text: str) -> Node | None:
    try:
        return yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as error:
        raise FormatError(str(error)[:300]) from error


def _children(node: Node, step: str) -> list[tuple[str | int, Node]]:
    if step == ANY and isinstance(node, SequenceNode):
        return list(enumerate(node.value))
    if not isinstance(node, MappingNode):
        return []
    return [
        (str(key.value), value)
        for key, value in node.value
        if isinstance(key, ScalarNode) and (step == ANY or key.value == step)
    ]


def _is_key(node: Node, name: str) -> bool:
    return isinstance(node, ScalarNode) and node.value == name


def mappings_at(
    node: Node | None, path: tuple[str, ...], at: tuple[str | int, ...] = ()
) -> Iterator[tuple[tuple[str | int, ...], MappingNode]]:
    """Every mapping node at `path` below `node`, with the steps that reach it (for a JSON Pointer); ANY
    steps over each sequence item or mapping value."""
    if node is None:
        return
    if not path:
        if isinstance(node, MappingNode):
            yield at, node
        return
    for step, child in _children(node, path[0]):
        yield from mappings_at(child, path[1:], (*at, step))


def entry(mapping: MappingNode, key: str) -> int | None:
    """The index of `key`'s entry in `mapping`, or None."""
    return next((index for index, (node, _) in enumerate(mapping.value) if _is_key(node, key)), None)


def value_of(mapping: MappingNode, key: str) -> Node | None:
    index = entry(mapping, key)
    return None if index is None else mapping.value[index][1]


def replace_scalar(node: ScalarNode, plain: str) -> Splice:
    """Write `plain` (a name or a number, which needs no escaping) in place of `node`, quoted as it was."""
    quote = node.style if node.style in ("'", '"') else ""
    return Splice(node.start_mark.index, node.end_mark.index, f"{quote}{plain}{quote}")


def rename_key(mapping: MappingNode, old: str, new: str) -> Splice | None:
    index = entry(mapping, old)
    if index is None:
        return None
    key = mapping.value[index][0]
    return replace_scalar(key, new) if isinstance(key, ScalarNode) else None


def _line_start(text: str, index: int) -> int:
    return text.rfind("\n", 0, index) + 1


def _after_line(text: str, index: int) -> int:
    """The start of the line after the one `index` is on (past a trailing comment), or the end of the text."""
    if not text[_line_start(text, index) : index].strip():
        return _line_start(text, index)  # `index` is already at the start of a line, past its indentation
    newline = text.find("\n", index)
    return len(text) if newline < 0 else newline + 1


def _content_end(node: Node) -> int:
    """Where `node`'s own text ends. A block collection's end mark sits at the next token, past the line
    breaks and comments that follow it, so its end is its last child's."""
    if isinstance(node, MappingNode | SequenceNode) and not node.flow_style and node.value:
        last = node.value[-1]
        return _content_end(last[1] if isinstance(node, MappingNode) else last)
    return node.end_mark.index


def _remove_flow_entry(mapping: MappingNode, index: int) -> Splice:
    key, value = mapping.value[index]
    if index + 1 < len(mapping.value):
        return Splice(key.start_mark.index, mapping.value[index + 1][0].start_mark.index, "")
    if index > 0:
        return Splice(_content_end(mapping.value[index - 1][1]), value.end_mark.index, "")
    return Splice(key.start_mark.index, value.end_mark.index, "")


def remove_entry(text: str, mapping: MappingNode, key: str) -> Splice | None:
    """Remove `key`'s entry from `mapping`; a block mapping left empty becomes {}."""
    index = entry(mapping, key)
    if index is None:
        return None
    if mapping.flow_style:
        return _remove_flow_entry(mapping, index)
    key_node, value = mapping.value[index]
    start = key_node.start_mark.index
    if len(mapping.value) == 1:
        return Splice(start, _content_end(value), "{}")
    own_line = not text[_line_start(text, start) : start].strip()
    if own_line:
        return Splice(_line_start(text, start), _after_line(text, _content_end(value)), "")
    # The first entry, written after a sequence dash: the next key takes its place on that line.
    return Splice(start, mapping.value[index + 1][0].start_mark.index, "")


def apply(text: str, splices: Iterable[Splice | None]) -> str:
    """`text` with every splice made; the same splice reached twice (through an alias) is made once."""
    ordered = sorted({splice for splice in splices if splice is not None}, reverse=True)
    for later, earlier in zip(ordered, ordered[1:], strict=False):
        if earlier.end > later.start:
            raise ValueError(f"overlapping YAML edits at {earlier.start} and {later.start}")
    for splice in ordered:
        text = text[: splice.start] + splice.text + text[splice.end :]
    return text
