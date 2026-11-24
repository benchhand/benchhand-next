"""The in-memory record: a project's hw/ documents, each shaped by its contract in contracts/record/."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

JsonObject = dict[str, Any]

MANUFACTURING_DOCUMENTS = ("capabilities", "materials", "selection", "findings", "evidence")


@dataclass(frozen=True)
class Decision:
    """A decision record file: its front matter (decision.schema.json), slug and verbatim Markdown body."""

    slug: str
    front: JsonObject
    body: str

    @property
    def id(self) -> str:
        return str(self.front["id"])

    @property
    def file_name(self) -> str:
        return f"{self.id}-{self.slug}.md"

    @property
    def approves(self) -> bool:
        """Whether citing this decision approves: a gate approved or a design accepted."""
        status = (self.front.get("kind"), self.front.get("status"))
        return status in (("gate", "approved"), ("design", "accepted"))


@dataclass
class Record:
    """Every record document of one project. Parts are keyed by their directory name, decisions by the id in
    their file name, manufacturing documents by name (capabilities, materials, selection, findings, evidence)
    and guideline sets by file stem. Optional documents that are absent are left out (policy is None)."""

    product: JsonObject
    requirements: JsonObject
    interfaces: JsonObject
    assembly: JsonObject
    bom: list[JsonObject]
    verification: list[JsonObject]
    parts: dict[str, JsonObject] = field(default_factory=dict)
    decisions: dict[str, Decision] = field(default_factory=dict)
    manufacturing: dict[str, JsonObject] = field(default_factory=dict)
    guidelines: dict[str, JsonObject] = field(default_factory=dict)
    policy: JsonObject | None = None
