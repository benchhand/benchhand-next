# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Targeted edits of YAML text: rename a key, replace a scalar value, insert or remove mapping entries.

Each edit is a splice at the character positions PyYAML's composer reports for the nodes it touches, so every
other byte of the file (comments, key order, quoting, flow or block style, indentation, line endings) stays as
written. A round-trip dump through a YAML library would re-flow the flow mappings the prototype writes.

An edit that would change an anchored node, a node reached through an alias, or a mapping with a merge key
raises LayoutError instead: the text of a shared node is not the place of one value. So does an edit of a
node the editor cannot locate by its delimiter tokens: a tagged or anchored key or value, a flow mapping whose
marks are not its braces, and a key that a mapping holds only through a merge key.
"""

from __future__ import annotations

import bisect
import json
from collections.abc import Iterator
from dataclasses import dataclass, field

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

from benchhand_core.record.finding import pointer as json_pointer
from benchhand_core.record.formats import FormatError

ANY = "*"  # a path step that matches every item of a sequence or every value of a mapping
MERGE_KEY = "<<"
Steps = tuple[str | int, ...]


class LayoutError(ValueError):
    """A YAML layout that a targeted edit cannot change safely; the file needs a hand edit."""

    def __init__(self, steps: Steps, message: str, fix: str) -> None:
        super().__init__(message)
        self.pointer = json_pointer(*steps)
        self.message = message
        self.fix = fix


SHARED_FIX = "Write the shared node out in full in place of its anchor (&) and its aliases (*), then migrate."
PLAIN_FIX = "Remove the YAML tag (!!) or anchor (&) from it, writing the value in full, then migrate again."
BLOCK_FIX = "Write the mapping in block style, one entry per line, then migrate again."
EXPLICIT_FIX = "Write the entry as `key: value` on one line, without the ? explicit-key marker, then migrate."


@dataclass(frozen=True, order=True)
class Splice:
    """Replace text[start:end] with `text`."""

    start: int
    end: int
    text: str


@dataclass(frozen=True)
class Target:
    """A mapping a rule edits: the steps that reach it, and whether it is shared through an anchor."""

    steps: Steps
    mapping: MappingNode
    shared: bool


def _compose(text: str) -> tuple[Node | None, tuple[int, ...]]:
    """The composed root, and where each anchor (&name) starts. An alias (*name) is not an anchor: removing
    one removes a use, not the shared node."""
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        events = yaml.parse(text, Loader=yaml.SafeLoader)
        anchored = tuple(
            sorted(
                event.start_mark.index
                for event in events
                if getattr(event, "anchor", None) is not None and not isinstance(event, yaml.AliasEvent)
            )
        )
    except yaml.YAMLError as error:
        raise FormatError(str(error)[:300]) from error
    return root, anchored


def _is_key(node: Node, name: str) -> bool:
    return isinstance(node, ScalarNode) and node.value == name


def entry(mapping: MappingNode, key: str) -> int | None:
    """The index of `key`'s entry in `mapping`, or None."""
    return next((index for index, (node, _) in enumerate(mapping.value) if _is_key(node, key)), None)


def value_of(mapping: MappingNode, key: str) -> Node | None:
    index = entry(mapping, key)
    return None if index is None else mapping.value[index][1]


def _merged(mapping: MappingNode, seen: frozenset[int] = frozenset()) -> set[str]:
    """The keys `mapping` holds only through its merge key (<<), however deeply merged."""
    value = value_of(mapping, MERGE_KEY)
    sources = value.value if isinstance(value, SequenceNode) else [value] if value is not None else []
    keys: set[str] = set()
    for source in sources:
        if isinstance(source, MappingNode) and id(source) not in seen:
            keys |= {str(key.value) for key, _ in source.value if isinstance(key, ScalarNode)}
            keys |= _merged(source, seen | {id(mapping)})
    return keys - {MERGE_KEY}


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


def _next_token(text: str, index: int) -> int:
    """The index of the next character after `index` that is neither white space nor part of a comment."""
    while index < len(text):
        char = text[index]
        if char == "#":
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
        elif char in " \t\r\n":
            index += 1
        else:
            return index
    return index


@dataclass
class Document:
    """A YAML text being edited: its composed nodes, where its anchors are, and the splices made so far."""

    text: str
    root: Node | None
    anchored: tuple[int, ...]  # sorted
    splices: list[Splice] = field(default_factory=list)

    @classmethod
    def parse(cls, text: str) -> Document:
        root, anchored = _compose(text)
        return cls(text, root, anchored)

    def _shared(self, node: Node) -> bool:
        return self._anchors_in(node.start_mark.index, node.start_mark.index + 1)

    def _anchors_in(self, start: int, end: int) -> bool:
        index = bisect.bisect_left(self.anchored, start)
        return index < len(self.anchored) and self.anchored[index] < end

    def root_target(self) -> Target | None:
        if not isinstance(self.root, MappingNode):
            return None
        return Target((), self.root, self._shared(self.root) or entry(self.root, MERGE_KEY) is not None)

    def mappings_at(self, path: tuple[str, ...]) -> Iterator[Target]:
        """Every mapping at `path` below the root; ANY steps over each sequence item or mapping value."""
        if self.root is not None:
            yield from self._walk(self.root, path, (), self._shared(self.root))

    def _walk(self, node: Node, path: tuple[str, ...], steps: Steps, shared: bool) -> Iterator[Target]:
        if not path:
            if isinstance(node, MappingNode):
                yield Target(steps, node, shared or entry(node, MERGE_KEY) is not None)
            return
        for step, child in _children(node, path[0]):
            yield from self._walk(child, path[1:], (*steps, step), shared or self._shared(child))

    def _refuse_shared(self, target: Target, key: str) -> None:
        if target.shared:
            raise LayoutError(
                (*target.steps, key),
                f"{key} sits in a mapping shared through a YAML anchor, alias or merge key",
                SHARED_FIX,
            )

    def has(self, target: Target, key: str) -> bool:
        """Whether `target` holds `key`, directly or through a merge key."""
        return entry(target.mapping, key) is not None or key in _merged(target.mapping)

    def _locate(self, target: Target, key: str) -> int | None:
        """The index of `key`'s entry, for an edit; LayoutError when the edit cannot be made in place."""
        index = entry(target.mapping, key)
        if index is None and key in _merged(target.mapping):
            message = f"{key} comes into this mapping only through a merge key (<<)"
            raise LayoutError((*target.steps, key), message, SHARED_FIX)
        if index is not None:
            self._refuse_shared(target, key)
            self._check_plain(target, key, target.mapping.value[index][0])
            if _explicit_key(self.text, target.mapping.value[index][0]):
                message = f"{key} is written as an explicit key (? {key})"
                raise LayoutError((*target.steps, key), message, EXPLICIT_FIX)
        return index

    def _check_plain(self, target: Target, key: str, node: Node) -> None:
        """Refuse a scalar whose marks span more than its own text: a tag or an anchor before it."""
        start, end = node.start_mark.index, node.end_mark.index
        quoted = isinstance(node, ScalarNode) and node.style in ("'", '"')
        own = self.text[start:end]
        plain = isinstance(node, ScalarNode) and (
            (quoted and own[:1] == node.style) or (not quoted and own == node.value)
        )
        if not plain or self._shared(node):
            raise LayoutError((*target.steps, key), f"{key} carries a YAML tag or anchor", PLAIN_FIX)

    def _check_braces(self, target: Target) -> None:
        """Refuse a flow mapping whose marks are not its braces, such as one written after a tag."""
        mapping = target.mapping
        if self.text[mapping.start_mark.index] != "{" or self.text[mapping.end_mark.index - 1] != "}":
            message = "a flow mapping with a YAML tag or anchor before its {"
            raise LayoutError(target.steps, message, PLAIN_FIX)

    def result(self) -> str:
        """The text with every splice made; the same splice made twice counts once."""
        ordered = sorted(set(self.splices), reverse=True)
        for later, earlier in zip(ordered, ordered[1:], strict=False):
            if earlier.end > later.start:
                raise LayoutError((), "two edits of this file overlap", BLOCK_FIX)
        text = self.text
        for splice in ordered:
            text = text[: splice.start] + splice.text + text[splice.end :]
        return text

    # --- edits ------------------------------------------------------------------------------------------

    def replace_value(self, target: Target, key: str, plain: str) -> None:
        """Write `plain` (a name or a number, which needs no escaping) as `key`'s value, quoted as it was."""
        index = self._locate(target, key)
        value = None if index is None else target.mapping.value[index][1]
        if not isinstance(value, ScalarNode) or value.value == plain:
            return
        self._check_plain(target, key, value)
        self.splices.append(_scalar_splice(value, plain))

    def rename_key(self, target: Target, old: str, new: str) -> None:
        index = self._locate(target, old)
        if index is not None:
            key = target.mapping.value[index][0]
            assert isinstance(key, ScalarNode)  # _locate checked it
            self.splices.append(_scalar_splice(key, new))

    def insert_first(self, target: Target, entries: list[tuple[str, str]], newline: str = "\n") -> None:
        """Insert `entries` (key, text value) before the first entry of `target`, a top-level mapping."""
        mapping = target.mapping
        self._refuse_shared(target, entries[0][0])
        if mapping.flow_style:
            self._check_braces(target)
            rendered = ", ".join(f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in entries)
            at = mapping.start_mark.index + 1
            self.splices.append(Splice(at, at, rendered + (", " if mapping.value else "")))
            return
        if mapping.value:
            self._check_plain(target, str(mapping.value[0][0].value), mapping.value[0][0])
        lines = yaml.safe_dump(dict(entries), sort_keys=False, allow_unicode=True, width=1 << 30)
        at = mapping.value[0][0].start_mark.index if mapping.value else mapping.start_mark.index
        self.splices.append(Splice(at, at, lines.replace("\n", newline)))

    def remove_entries(self, target: Target, keys: tuple[str, ...]) -> None:
        """Remove the entries of `keys` from `target`; a mapping left empty becomes {}. An anchor inside a
        removed entry refuses the edit, since an alias elsewhere may name it."""
        removed = {index for key in keys if (index := self._locate(target, key)) is not None}
        if not removed:
            return
        for index in removed:
            key, value = target.mapping.value[index]
            if self._anchors_in(key.start_mark.index, _content_end(value)):
                name = str(key.value)
                raise LayoutError((*target.steps, name), f"{name} holds a YAML anchor", SHARED_FIX)
        if target.mapping.flow_style:
            self._check_braces(target)
            self.splices.extend(_flow_removal(self.text, target.mapping, removed))
        else:
            self.splices.extend(_block_removal(self.text, target.mapping, removed))


def _scalar_splice(node: ScalarNode, plain: str) -> Splice:
    quote = node.style if node.style in ("'", '"') else ""
    return Splice(node.start_mark.index, node.end_mark.index, f"{quote}{plain}{quote}")


def _flow_removal(text: str, mapping: MappingNode, removed: set[int]) -> list[Splice]:
    """Each removed entry goes with the separator after it. When the removed entries end the mapping, the
    comma after the last kept entry goes too, but not the comment after that comma."""
    entries = mapping.value
    kept = [index for index in range(len(entries)) if index not in removed]
    if not kept:
        return [Splice(mapping.start_mark.index + 1, mapping.end_mark.index - 1, "")]
    last_kept = kept[-1]
    splices = [
        Splice(entries[index][0].start_mark.index, entries[index + 1][0].start_mark.index, "")
        for index in sorted(removed)
        if index < last_kept
    ]
    if last_kept + 1 < len(entries):
        comma = _next_token(text, _content_end(entries[last_kept][1]))
        tail = entries[last_kept + 1][0].start_mark.index
        end = _content_end(entries[-1][1])
        after = _next_token(text, end)
        if text[after : after + 1] == ",":
            end = after + 1
        if text[comma + 1 : tail].strip():  # a comment after the comma stays with the kept entry
            splices.append(Splice(comma, comma + 1, ""))
            splices.append(Splice(tail, end, ""))
        else:
            splices.append(Splice(comma, end, ""))
    return splices


def _explicit_key(text: str, key: Node) -> bool:
    """Whether `key` is written after a `?` explicit-key marker."""
    before = text[: key.start_mark.index].rstrip(" \t")
    return before.endswith("?")


def _block_removal(text: str, mapping: MappingNode, removed: set[int]) -> list[Splice]:
    entries = mapping.value
    if len(removed) == len(entries):
        return [Splice(entries[0][0].start_mark.index, _content_end(entries[-1][1]), "{}")]
    splices = []
    covered: set[int] = set()
    for index in sorted(removed):
        if index in covered:
            continue
        start = entries[index][0].start_mark.index
        prefix = text[_line_start(text, start) : start].strip()
        if not prefix:
            end = _after_line(text, _content_end(entries[index][1]))
            splices.append(Splice(_line_start(text, start), end, ""))
            continue
        if not prefix.endswith("-"):
            message = "a removed entry starts its line after something other than a dash"
            raise LayoutError((), message, BLOCK_FIX)
        # The first entry, written after a sequence dash: the next kept key takes its place on that line, and
        # the removed entries between them go with it.
        following = next(other for other in range(index + 1, len(entries)) if other not in removed)
        splices.append(Splice(start, entries[following][0].start_mark.index, ""))
        covered.update(range(index + 1, following))
    return splices
