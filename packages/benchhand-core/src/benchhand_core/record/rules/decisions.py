"""Decision references: every cited DR-### has a readable record, a freeze, change or flow profile cites an
approving decision, and an approved gate records its approval unless hw/policy.yaml sets its gate to auto."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from benchhand_contracts.models.record.decision_schema import Channel, GateDecision
from benchhand_contracts.models.record.policy_schema import Mode

from benchhand_core.record import documents
from benchhand_core.record.finding import Finding, error, pointer
from benchhand_core.record.model import Decision, Policy, Product, as_json
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
    """(project-relative path, JSON of the document) of every read document that may cite a decision."""
    for spec, document in (
        (documents.PRODUCT, read.product),
        (documents.REQUIREMENTS, read.requirements),
        (documents.INTERFACES, read.interfaces),
        (documents.ASSEMBLY, read.assembly),
        (documents.POLICY, read.policy),
    ):
        if document is not None:
            yield spec.path, as_json(document)
    yield from ((documents.part(pn).path, as_json(part)) for pn, part in read.parts.items())
    for name, document in read.manufacturing.items():
        yield documents.manufacturing(name).path, as_json(document)
    yield from ((documents.guideline(stem).path, as_json(doc)) for stem, doc in read.guidelines.items())
    for decision in read.decisions.values():
        yield documents.decision_path(decision.file_name), as_json(decision.front)


def _reference(path: str, where: Where, ref: str, read: RecordRead) -> Finding | None:
    at = pointer(*where)
    if ref not in read.decisions:
        message = f"{ref} has no readable record {documents.DECISIONS_DIR}/{ref}-<slug>.md"
        return error("decision.reference", path, message, pointer=at, subject=ref)
    if documents.decision_path(read.decisions[ref].file_name) == path:
        return error("decision.reference", path, f"{ref} names itself", pointer=at, subject=ref)
    return None


def _approvals(product: Product, decisions: dict[str, Decision]) -> Iterator[Finding]:
    flow = product.flow
    for key, rule in APPROVALS.items():
        anchor = getattr(flow, key)
        ref = anchor.decision if anchor is not None else None
        decision = decisions.get(ref) if ref is not None else None
        if decision is not None and not decision.approves:
            front = decision.front
            message = (
                f"flow/{key} cites {ref}, a {front.kind} decision with status {front.status.value}; {rule}: "
                "a gate approved or a design decision accepted"
            )
            at = pointer("flow", key, "decision")
            yield error("decision.not_approving", documents.PRODUCT.path, message, pointer=at, subject=ref)


def gate_mode(policy: Policy | None, gate: str) -> Mode:
    """The mode hw/policy.yaml sets for `gate`: its own entry, else the default, else ask."""
    if policy is None:
        return Mode.ask
    entry = (policy.gates or {}).get(gate)
    return entry.mode if entry is not None else policy.default


def _gate_approval(decision: Decision, front: GateDecision, mode: Mode) -> Finding | None:
    """Under ask or chat, an approved gate records a person's approval; auto is only the auto mode's."""
    path = documents.decision_path(decision.file_name)
    gate = f"{decision.id} approves gate {front.gate}"
    policy = f"{documents.POLICY.path} sets the gate to {mode.value}"
    if front.approval is None:
        message = (
            f"{gate} without an approval, but {policy}; record the channel, who approved and what they said"
        )
        return error("decision.approval_missing", path, message, pointer="/approval", subject=decision.id)
    if front.approval.channel is Channel.auto:
        message = f"{gate} through channel auto, but {policy}; record who approved and what they said"
        return error(
            "decision.approval_channel", path, message, pointer="/approval/channel", subject=decision.id
        )
    return None


def _gate_approvals(decisions: dict[str, Decision], policy: Policy | None) -> Iterator[Finding]:
    for decision in decisions.values():
        front = decision.front
        if not isinstance(front, GateDecision) or front.status.value != "approved":
            continue
        mode = gate_mode(policy, front.gate)
        if mode is not Mode.auto and (finding := _gate_approval(decision, front, mode)) is not None:
            yield finding


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
