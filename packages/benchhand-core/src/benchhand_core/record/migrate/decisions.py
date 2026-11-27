# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Rules for hw/decisions/DR-###-<slug>.md: MADR 4.0.0 front matter to the record version 3 decision.

Each rule edits the front matter text in place (yaml_edit), so comments, quoting, block or flow style and the
Markdown body stay as written. A file whose front matter already has `kind` is a record version 3 decision
and is left alone, so every rule is idempotent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from yaml.nodes import Node, ScalarNode, SequenceNode

from benchhand_core.record.finding import Finding, error, info
from benchhand_core.record.formats import FRONT_MATTER, FormatError, parse_yaml
from benchhand_core.record.migrate.rule import Rewrite
from benchhand_core.record.migrate.yaml_edit import Document, Target, value_of
from benchhand_core.record.store import DECISION_FILE

TITLE = re.compile(r"^# (?P<title>.*\S)\s*$", re.MULTILINE)
KEY_RENAMES = {"decision-makers": "decision_makers", "superseded-by": "superseded_by"}
NAME_LISTS = ("decision-makers", "consulted", "informed", "superseded-by")  # v3 states each with 1+ items


@dataclass(frozen=True)
class Madr:
    """A prototype decision file split for editing: where its front matter text sits, that text parsed and
    composed, and the body."""

    text: str
    front_start: int
    front_end: int
    data: dict[str, Any]
    document: Document
    target: Target
    body: str

    def edited(self) -> str:
        return self.text[: self.front_start] + self.document.result() + self.text[self.front_end :]

    @property
    def superseded(self) -> bool:
        return bool(self.data.get("superseded-by"))

    @property
    def newline(self) -> str:
        return "\r\n" if "\r\n" in self.document.text else "\n"


def madr(text: str) -> Madr | None:
    """The MADR decision in `text`, or None for a record version 3 decision (its front matter has kind)."""
    match = FRONT_MATTER.match(text)
    if match is None:
        raise FormatError("no YAML front matter between --- lines at the top of the file")
    front = match["front"] or ""
    data = parse_yaml(front)
    document = Document.parse(front)
    target = document.root_target()
    if not isinstance(data, dict) or target is None:
        raise FormatError("the front matter is not a mapping")
    if "kind" in data:
        return None
    start = match.start("front") if match["front"] is not None else match.start("body")
    return Madr(text, start, start + len(front), data, document, target, match["body"])


def _decision_id(path: str) -> str | None:
    match = DECISION_FILE.fullmatch(PurePosixPath(path).name)
    return None if match is None else match["id"]


def gate(path: str, text: str) -> Rewrite:
    """A MADR gate decision (gate: {from, to}) stays kind: design with its mapped status, without the gate
    key: a migrated record has no approval channel, approver or quote to make it a kind: gate decision."""
    record = madr(text)
    if record is None or "gate" not in record.data:
        return Rewrite(text)
    value = record.data["gate"]
    shown = f"{value.get('from')} to {value.get('to')}" if isinstance(value, dict) else repr(value)
    note = info(
        "migrate.gate_decision",
        path,
        f"this decision recorded the gate from {shown}. It stays a design decision with its status, and "
        "its gate key is removed: a migrated record has no approval channel, approver or quote, which a "
        "kind: gate decision carries.",
        pointer="/gate",
        subject=_decision_id(path),
        action="No change is needed. Gates the flow approves from now on are recorded as kind: gate.",
    )
    record.document.remove_entries(record.target, ("gate",))
    return Rewrite(record.edited(), (note,))


def deprecated(path: str, text: str) -> Rewrite:
    """status: deprecated has no record version 3 status. With superseded-by it becomes superseded (the
    decision-front-matter rule); without it the file is refused until the user picks a status."""
    record = madr(text)
    if record is None or record.data.get("status") != "deprecated" or record.superseded:
        return Rewrite(text)
    refusal = error(
        "migrate.deprecated_status",
        path,
        "status deprecated has no record version 3 counterpart, and the file names no superseded-by",
        pointer="/status",
        subject=_decision_id(path),
        action="Set status to accepted, rejected, or superseded with superseded-by: [DR-###] naming its "
        "replacement, then migrate again.",
    )
    return Rewrite(text, (refusal,))


def _empty(node: Node | None) -> bool:
    return (isinstance(node, SequenceNode) and not node.value) or (
        isinstance(node, ScalarNode) and node.tag.endswith(":null")
    )


def _rename_keys(record: Madr) -> None:
    """The prototype's hyphenated keys under their record version 3 names, and the name lists left empty
    (which record version 3 states with at least one name) removed."""
    mapping = record.target.mapping
    empty = tuple(key for key in NAME_LISTS if _empty(value_of(mapping, key)))
    record.document.remove_entries(record.target, empty)
    for old, new in KEY_RENAMES.items():
        if old not in empty:
            record.document.rename_key(record.target, old, new)


def _id_and_title(path: str, record: Madr) -> tuple[str, str] | Finding:
    """The decision's id (from its file name) and title (from the body's heading), or why it has none."""
    decision_id = _decision_id(path)
    title = TITLE.search(record.body)
    if decision_id is None:
        return error(
            "decision.file_name",
            path,
            "a decision record is named DR-###-<slug>.md; its id is taken from that name",
            pointer="/id",
            action="Rename the file to DR-###-<slug>.md (lowercase words joined by -), then migrate again.",
        )
    if title is None:
        return error(
            "migrate.decision_title",
            path,
            "the body has no '# ' heading, which record version 3 takes as the decision's title",
            pointer="/title",
            subject=decision_id,
            action="Add a '# <title>' heading at the top of the body, then migrate again.",
        )
    return decision_id, title["title"]


def front_matter(path: str, text: str) -> Rewrite:
    """A MADR decision as kind: design: id (from the file name), kind and title (from the body's heading)
    added; decision-makers and superseded-by renamed; status superseded when superseded-by names a
    record. A deprecated status without superseded-by is the decision-deprecated rule's to refuse."""
    record = madr(text)
    if record is None or (record.data.get("status") == "deprecated" and not record.superseded):
        return Rewrite(text)
    identity = _id_and_title(path, record)
    if isinstance(identity, Finding):
        return Rewrite(text, (identity,))
    decision_id, title = identity
    entries = [("id", decision_id), ("kind", "design"), ("title", title)]
    record.document.insert_first(record.target, entries, record.newline)
    _rename_keys(record)
    if record.superseded:
        record.document.replace_value(record.target, "status", "superseded")
    return Rewrite(record.edited())
