"""Decision references: every cited DR-### has a readable record, a freeze, change or flow profile cites an
approving decision, and an approved gate records its approval unless hw/policy.yaml sets its gate to auto."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, pointer
from benchhand_core.record.model import Decision
from benchhand_core.record.store import RecordRead

LIST_KEYS = ("decisions", "supersedes", "superseded_by")
APPROVALS = {
    "frozen": "only an approving decision freezes a version",
    "change": "only an approving decision opens an engineering change",
    "profile": "only an approving decision sets the flow profile",
}

Where = tuple[str | int, ...]


def references(node: Any, *where: str | int) -> Iterator[tuple[Where, str]]:
    """Every decision id `node` cites, with its path: a `decision` value, or an item of a `decisions`,
    `supersedes` or `superseded_by` list."""
    if isinstance(node, list):
        for index, item in enumerate(node):
            yield from references(item, *where, index)
        return
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        if key == "decision" and isinstance(value, str):
            yield (*where, key), value
        elif key in LIST_KEYS and isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, str):
                    yield (*where, key, index), item
        else:
            yield from references(value, *where, key)


def _cited(read: RecordRead) -> Iterator[tuple[str, Any]]:
    """(project-relative path, document) of every read document that may cite a decision."""
    for spec, document in (
        (documents.PRODUCT, read.product),
        (documents.REQUIREMENTS, read.requirements),
        (documents.INTERFACES, read.interfaces),
        (documents.ASSEMBLY, read.assembly),
        (documents.POLICY, read.policy),
    ):
        if document is not None:
            yield spec.path, document
    yield from ((documents.part(pn).path, part) for pn, part in read.parts.items())
    yield from ((documents.manufacturing(name).path, doc) for name, doc in read.manufacturing.items())
    yield from ((documents.guideline(stem).path, doc) for stem, doc in read.guidelines.items())
    for decision in read.decisions.values():
        yield documents.decision_path(decision.file_name), decision.front


def _reference(path: str, where: Where, ref: str, read: RecordRead) -> Finding | None:
    at = pointer(*where)
    if ref not in read.decisions:
        message = f"{ref} has no readable record {documents.DECISIONS_DIR}/{ref}-<slug>.md"
        return Finding("decision.reference", path, message, pointer=at, subject=ref)
    if documents.decision_path(read.decisions[ref].file_name) == path:
        return Finding("decision.reference", path, f"{ref} names itself", pointer=at, subject=ref)
    return None


def _approvals(product: dict[str, Any], decisions: dict[str, Decision]) -> Iterator[Finding]:
    flow = product["flow"]
    for key, rule in APPROVALS.items():
        ref = flow.get(key, {}).get("decision")
        decision = decisions.get(ref) if ref is not None else None
        if decision is not None and not decision.approves:
            front = decision.front
            message = (
                f"flow/{key} cites {ref}, a {front['kind']} decision with status {front['status']}; {rule}: "
                "a gate approved or a design decision accepted"
            )
            at = pointer("flow", key, "decision")
            yield Finding("decision.not_approving", documents.PRODUCT.path, message, pointer=at, subject=ref)


def gate_mode(policy: dict[str, Any] | None, gate: str) -> str:
    """The mode hw/policy.yaml sets for `gate`: its own entry, else the default, else ask."""
    policy = policy or {}
    return policy.get("gates", {}).get(gate, {}).get("mode") or policy.get("default", "ask")


def _gate_approvals(decisions: dict[str, Decision], policy: dict[str, Any] | None) -> Iterator[Finding]:
    for decision in decisions.values():
        front = decision.front
        if front["kind"] != "gate" or front["status"] != "approved" or "approval" in front:
            continue
        mode = gate_mode(policy, front["gate"])
        if mode != "auto":
            message = (
                f"{decision.id} approves gate {front['gate']} without an approval, but "
                f"{documents.POLICY.path} sets the gate to {mode}; record the channel, who approved and "
                "what they said"
            )
            path = documents.decision_path(decision.file_name)
            code = "decision.approval_missing"
            yield Finding(code, path, message, pointer="/approval", subject=decision.id)


def check(read: RecordRead) -> list[Finding]:
    findings = [
        finding
        for path, document in _cited(read)
        for where, ref in references(document)
        if (finding := _reference(path, where, ref, read)) is not None
    ]
    if read.product is not None:
        findings.extend(_approvals(read.product, read.decisions))
    findings.extend(_gate_approvals(read.decisions, read.policy))
    return findings
