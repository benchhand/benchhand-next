"""Rules for hw/decisions/DR-###-<slug>.md: MADR 4.0.0 front matter to the record version 3 decision.

Each rule edits the front matter text in place (yaml_edit), so comments, quoting and the Markdown body stay as
written. A file whose front matter already has `kind` is a record version 3 decision and is left alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

import yaml
from yaml.nodes import MappingNode, ScalarNode, SequenceNode

from benchhand_core.record.finding import Finding, error, info
from benchhand_core.record.formats import FRONT_MATTER, FormatError, parse_yaml
from benchhand_core.record.migrate import yaml_edit
from benchhand_core.record.migrate.rule import Rewrite
from benchhand_core.record.store import DECISION_FILE

TITLE = re.compile(r"^# (?P<title>.*\S)\s*$", re.MULTILINE)
NEVER_ADOPTED = re.compile(r"\bnever\s+(?:been\s+)?adopted\b", re.IGNORECASE)
KEY_RENAMES = {"decision-makers": "decision_makers", "superseded-by": "superseded_by"}
NAME_LISTS = ("decision-makers", "consulted", "informed", "superseded-by")  # v3 states each with 1+ items


@dataclass(frozen=True)
class Madr:
    """A prototype decision file split for editing: the front matter text, where it starts, its parsed
    data and its composed node, and the body."""

    text: str
    front_start: int
    front: str
    data: dict[str, Any]
    node: MappingNode
    body: str

    def edited(self, splices: list[yaml_edit.Splice | None]) -> str:
        end = self.front_start + len(self.front)
        return self.text[: self.front_start] + yaml_edit.apply(self.front, splices) + self.text[end:]

    @property
    def superseded(self) -> bool:
        return bool(self.data.get("superseded-by"))

    @property
    def newline(self) -> str:
        return "\r\n" if "\r\n" in self.front else "\n"


def madr(text: str) -> Madr | None:
    """The MADR decision in `text`, or None for a record version 3 decision (its front matter has kind)."""
    match = FRONT_MATTER.match(text)
    if match is None:
        raise FormatError("no YAML front matter between --- lines at the top of the file")
    front = match["front"] or ""
    data = parse_yaml(front)
    node = yaml_edit.compose(front)
    if not isinstance(data, dict) or not isinstance(node, MappingNode):
        raise FormatError("the front matter is not a mapping")
    if "kind" in data:
        return None
    return Madr(text, match.start("front"), front, data, node, match["body"])


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
    return Rewrite(record.edited([yaml_edit.remove_entry(record.front, record.node, "gate")]), (note,))


def _status_node(record: Madr) -> ScalarNode | None:
    value = yaml_edit.value_of(record.node, "status")
    return value if isinstance(value, ScalarNode) else None


def deprecated(path: str, text: str) -> Rewrite:
    """status: deprecated has no record version 3 status. With superseded-by it becomes superseded (the
    decision-front-matter rule); a body that says it was never adopted makes it rejected; otherwise the
    file is refused until the user picks a status."""
    record = madr(text)
    if record is None or record.data.get("status") != "deprecated" or record.superseded:
        return Rewrite(text)
    status = _status_node(record)
    subject = _decision_id(path)
    if status is not None and NEVER_ADOPTED.search(record.body):
        note = info(
            "migrate.deprecated_rejected",
            path,
            "status deprecated becomes rejected: the body says the decision was never adopted",
            pointer="/status",
            subject=subject,
        )
        return Rewrite(record.edited([yaml_edit.replace_scalar(status, "rejected")]), (note,))
    refusal = error(
        "migrate.deprecated_status",
        path,
        "status deprecated has no record version 3 counterpart, and the file names no superseded-by and "
        "does not say the decision was never adopted",
        pointer="/status",
        subject=subject,
        action="Set status to accepted, rejected, or superseded with superseded-by: [DR-###] naming its "
        "replacement, then migrate again.",
    )
    return Rewrite(text, (refusal,))


def _identity(record: Madr, decision_id: str, title: str) -> yaml_edit.Splice:
    """The id, kind and title lines, inserted at the top of the front matter."""
    lines = yaml.safe_dump(
        {"id": decision_id, "kind": "design", "title": title},
        sort_keys=False,
        allow_unicode=True,
        width=1 << 30,
    )
    return yaml_edit.Splice(0, 0, lines.replace("\n", record.newline))


def _empty(node: object) -> bool:
    return (isinstance(node, SequenceNode) and not node.value) or (
        isinstance(node, ScalarNode) and node.tag.endswith(":null")
    )


def _renamed_keys(record: Madr) -> list[yaml_edit.Splice | None]:
    """The prototype's hyphenated keys under their record version 3 names, and the name lists left empty
    (which record version 3 states with at least one name) removed."""
    splices: list[yaml_edit.Splice | None] = []
    for key in NAME_LISTS:
        if _empty(yaml_edit.value_of(record.node, key)):
            splices.append(yaml_edit.remove_entry(record.front, record.node, key))
        elif key in KEY_RENAMES:
            splices.append(yaml_edit.rename_key(record.node, key, KEY_RENAMES[key]))
    return splices


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
    splices = [_identity(record, *identity), *_renamed_keys(record)]
    status = _status_node(record)
    if record.superseded and status is not None:
        splices.append(yaml_edit.replace_scalar(status, "superseded"))
    return Rewrite(record.edited(splices))
