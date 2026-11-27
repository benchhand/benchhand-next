# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""One migration rule: a row of the rule table in `rules.py`."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from benchhand_core.record.finding import Finding, error
from benchhand_core.record.migrate.yaml_edit import LayoutError


@dataclass(frozen=True)
class Rewrite:
    """A rule's result for one file: its new text (the same text when the rule finds nothing to change) and
    what the rule reports. An error finding refuses the file, and the text is then left as it was."""

    text: str
    findings: tuple[Finding, ...] = ()


# (project-relative path with / separators, the file's text) -> its rewrite
Transform = Callable[[str, str], Rewrite]


@dataclass(frozen=True)
class Rule:
    """One prototype change and how a migration undoes it. Applied to its own output, a rule changes
    nothing, so a rerun after an interrupted apply finishes the files it did not reach."""

    id: str  # stable; names the fixture directory and appears in the plan
    documents: tuple[str, ...]  # globs relative to the project root; * matches within one path segment
    changes: str  # what the rule changes, for people
    source: str  # the prototype commit or PR the old form comes from
    fixture: str  # the before/ and after/ trees, relative to packages/benchhand-core/tests/record
    transform: Transform

    def run(self, path: str, text: str) -> Rewrite:
        """The rule's rewrite of one file; a YAML layout it cannot edit safely refuses the file."""
        try:
            return self.transform(path, text)
        except LayoutError as layout:
            refusal = error(
                "migrate.unsupported_layout",
                path,
                f"{self.id}: {layout.message}",
                pointer=layout.pointer or None,
                action=layout.fix,
            )
            return Rewrite(text, (refusal,))
