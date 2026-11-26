"""The evidence assessment of one built version: the status of every obligation, the facets and the digest.

A port of the prototype's evidence.py `assess` (skills/cad-record/scripts/evidence.py at release.toml
reference_commit 412b5d9, lines 713-848), with `_disposition` and `_dispose` (1009-1044), `_facets`
(1047-1066) and the evidence.csv_unsupported rule of `_verification` (1069-1102). Every obligation gets
exactly one status, from three sources only: the record itself, the version's sealed packets and the
accepted ledger. Pure over (record, built version, today): no I/O and no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from benchhand_contracts.models.record.common_schema import Obligation
from benchhand_contracts.models.record.evidence_assessment_schema import (
    BenchhandEvidenceAssessmentOfOneBuiltVersion as EvidenceAssessment,
)

from benchhand_core.record.evidence import fingerprints as fp
from benchhand_core.record.evidence.built import BuiltVersion, ChangedSinceBuild, NotComputed, Packet
from benchhand_core.record.evidence.digest import acceptance_digest, acceptance_inventory, expected_digest
from benchhand_core.record.evidence.joints import joint_results
from benchhand_core.record.evidence.ledger import (
    EntryContext,
    EntryJudgement,
    credit,
    entry_targets,
    judge_entry,
)
from benchhand_core.record.evidence.obligations import required_checks, subject_of
from benchhand_core.record.evidence.packets import Candidate, OutcomeReading, packet_problems, read_outcomes
from benchhand_core.record.evidence.paths import PATH_CODES, dependents, disposition_problems
from benchhand_core.record.evidence.results import LEVELS, NOT_REQUIRED, best, facets, worst
from benchhand_core.record.evidence.use_case import assess_use_case
from benchhand_core.record.evidence.view import JsonMap, RecordView, items, mapping, view
from benchhand_core.record.evidence.waivers import WaiverScope, waiver_problem
from benchhand_core.record.finding import Finding
from benchhand_core.record.model import Record, as_json
from benchhand_core.record.rules.assembly import Inventory, Occurrence, inventory

FINDINGS = "hw/manufacturing/findings.yaml"
EVIDENCE = "hw/manufacturing/evidence.yaml"
NOT_COMPUTED = "not_computed"
__all__ = ["EvidenceAssessment", "assess"]


def _finding(code: str, severity: str, path: str, message: str, **optional: str | None) -> Finding:
    data: dict[str, Any] = {"code": code, "severity": severity, "path": path, "message": message}
    data.update({key: value for key, value in optional.items() if value})
    return Finding.model_validate(data)


def _part_of(placed: Inventory | None):
    """The PN a part reference (a PN or @occurrence) names, None when it names none."""

    def part_of(ref: str) -> str | None:
        found = placed.resolve(ref) if placed is not None else None
        return found.pn if isinstance(found, Occurrence) else None

    return part_of


def _obligation_requirements(obligation: Obligation | None) -> tuple[str, ...]:
    if obligation is None:
        return ()
    ids = {obligation.requirement, *items(subject_of(obligation).get("requirements"))}
    return tuple(sorted(i for i in ids if i))


@dataclass
class _State:
    record: RecordView
    placed: Inventory | None
    built: BuiltVersion
    today: date
    expected: tuple[Obligation, ...]
    by_id: dict[str, Obligation]
    candidates: dict[str, list[Candidate]]
    findings: list[Finding] = field(default_factory=list)
    waivers: dict[str, JsonMap] = field(default_factory=dict)
    entry_results: dict[str, str] = field(default_factory=dict)
    untargeted: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    critical: list[dict[str, Any]] = field(default_factory=list)
    accepted: list[Packet] = field(default_factory=list)
    complete: bool = True


def _record_sources(state: _State) -> None:
    """intent.* and assembly.joint are decided by the record itself (evidence.py:739-750)."""
    joints = joint_results(state.record, _part_of(state.placed))
    use_case = assess_use_case(state.record)
    for obligation in state.expected:
        found = state.candidates[obligation.id]
        if obligation.family == "intent.use_case":
            ready = ("pass", "record", "the use case is confirmed and supports a final choice")
            blocked = ("unknown", "record", "; ".join(use_case.blocking))
            found.append(ready if use_case.final_ready else blocked)
        elif obligation.family == "assembly.joint":
            result, reason = joints.get(obligation.id, ("unknown", obligation.basis))
            found.append((result, "record", reason))
        elif obligation.family.startswith(fp.RECORD_FAMILIES):
            found.append(("unknown", "record", obligation.basis))


def _stale_since_build(state: _State) -> dict[str, tuple[str, ...]]:
    staleness = state.built.staleness
    if isinstance(staleness, NotComputed):
        message = (
            f"build staleness was not computed: {staleness.reason}; no producer outcome it decides counts"
        )
        state.findings.append(_finding("evidence.staleness_not_computed", "error", "hw/versions", message))
        return {}
    subjects = [fp.SubjectOf(o, subject_of(o)) for o in state.expected]
    return fp.stale_obligations(subjects, staleness.changed)


def _packet_sources(state: _State) -> None:
    """The version's sealed packets (evidence.py:752-790)."""
    state.findings.extend(state.built.packet_findings)
    if state.built.packet_findings:
        state.complete = False
    stale = _stale_since_build(state)
    reading = OutcomeReading(state.candidates, state.findings)
    for packet in state.built.packets:
        problems = packet_problems(packet.data, state.by_id)
        if problems:
            message = f"{packet.bundle}/result.json: " + "; ".join(problems)
            path = f"{packet.bundle}/result.json"
            state.findings.append(_finding("packet.invalid", "error", path, message))
            state.complete = False
            continue
        state.accepted.append(packet)
        if packet.data.get("complete") is not True:
            state.complete = False
        read_outcomes(packet, state.by_id, state.built.staleness, stale, reading)


def _reliant(state: _State, judged: dict[str, EntryJudgement]) -> None:
    """An entry resting on an entry the path rules refuse is unknown too, directly or through others
    (evidence.py:801-806, evidence_paths.py:238)."""
    refused = {ident for ident, found in judged.items() if any(f.code in PATH_CODES for f in found.findings)}
    reliant = dependents(state.record.evidence, refused) if refused else {}
    for index, entry in enumerate(state.record.evidence):
        ident = str(entry.get("id"))
        if ident not in reliant:
            continue
        names = ", ".join(reliant[ident])
        message = (
            f"{ident} relies on {names}, which the record refuses. Its evidence earns no credit until the "
            "dependency is promoted into the record"
        )
        finding = _finding(
            "evidence.refused_dependency", "error", EVIDENCE, message, pointer=f"/entries/{index}"
        )
        reason = f"{ident} rests on refused evidence {names}"
        judged[ident] = EntryJudgement("unknown", (reason,), (*judged[ident].findings, finding))


def _path_refusals(state: _State) -> None:
    """Path findings of the finding dispositions (evidence.py:819-823); with the entries' own, they refuse
    the acceptance inventory (evidence.py:1292-1294)."""
    for index, disposition in enumerate(state.record.dispositions):
        for problem in disposition_problems(state.built.path_verdicts, disposition):
            message = f"finding {disposition.get('finding')}: {problem.message}"
            pointer = f"/dispositions/{index}"
            state.findings.append(_finding(problem.code, "error", FINDINGS, message, pointer=pointer))


def _ledger_sources(state: _State) -> None:
    """The accepted ledger (evidence.py:792-816)."""
    context = EntryContext(state.record, state.placed, state.by_id, state.built, state.today)
    judgements = {
        str(entry.get("id")): judge_entry(entry, index, context)
        for index, entry in enumerate(state.record.evidence)
    }
    _reliant(state, judgements)
    for index, entry in enumerate(state.record.evidence):
        ident = str(entry.get("id"))
        judged = judgements[ident]
        state.findings.extend(judged.findings)
        targets = entry_targets(entry, state.expected)
        credited = [credit(entry, index, judged, state.by_id[target], context) for target in targets]
        # an entry is as good as its weakest credit: a replacement that credits nothing settles nothing
        shown = {c.result for c in credited}
        state.entry_results[ident] = judged.result if shown <= {judged.result} else "unknown"
        for target, given in zip(targets, credited, strict=True):
            state.findings.extend(f for f in given.findings if f not in judged.findings)
            if given.result == "waived":
                state.waivers.setdefault(target, mapping(entry.get("waiver")))
            state.candidates[target].append((given.result, ident, "; ".join(given.reasons)))
        if not targets and entry.get("requirement"):
            key = (str(entry["requirement"]), str(entry.get("level")))
            state.untargeted.setdefault(key, []).append(judged.result)


def _disposition(state: _State, item: JsonMap, packet: Packet) -> JsonMap | None:
    """The latest disposition of a producer finding (findings.yaml is append-only) (evidence.py:1009)."""
    found = None
    for index, disposition in enumerate(state.record.dispositions):
        producer = mapping(disposition.get("producer"))
        if (
            disposition.get("finding") == item.get("id")
            and producer.get("bundle") == packet.bundle
            and producer.get("manifest_sha256") == packet.manifest_sha256
        ):
            found = {**disposition, "_index": index}
    return found


def _dispose(
    state: _State, item: JsonMap, disposition: JsonMap | None, obligation: Obligation | None
) -> bool:
    """Whether the finding is settled; an accepted waiver that stands is recorded (evidence.py:1020)."""
    if disposition is None:
        return False
    status = disposition.get("status")
    if status == "resolved":
        replacements = items(disposition.get("replacement_evidence"))
        if replacements:
            return all(state.entry_results.get(e) == "pass" for e in replacements)
        return state.record.approves(disposition.get("decision"))
    if status != "accepted_waiver":
        return False
    scope = WaiverScope(
        subject=mapping(item.get("subject")),
        obligation=obligation.id if obligation else None,
        family=obligation.family if obligation else None,
        obligation_requirements=_obligation_requirements(obligation),
        requirements=tuple(items(item.get("requirements"))),
        critical=item.get("severity") == "critical",
    )
    problem = waiver_problem(mapping(disposition.get("waiver")), scope, state.record, state.today)
    if problem is not None:
        message = f"finding {item.get('id')}: {problem.message}"
        pointer = f"/dispositions/{disposition['_index']}"
        finding = _finding(
            problem.code, "error", FINDINGS, message, pointer=pointer, subject=scope.obligation
        )
        state.findings.append(finding)
        return False
    if obligation is not None:
        state.waivers.setdefault(obligation.id, mapping(disposition.get("waiver")))
    return True


def _dispositions(state: _State) -> None:
    """Producer findings: dispositions, and the unresolved critical ones (evidence.py:824-833)."""
    for packet in state.accepted:
        for item in items(packet.data.get("findings")):
            item = mapping(item)
            obligation = state.by_id.get(str(item.get("obligation")))
            settled = _dispose(state, item, _disposition(state, item, packet), obligation)
            open_outcome = item.get("outcome") in ("fail", "unknown")
            if item.get("severity") == "critical" and open_outcome and not settled:
                entry = {"finding": item.get("id"), "bundle": packet.bundle}
                for key in ("code", "obligation", "consequence"):
                    if item.get(key):
                        entry[key] = item[key]
                state.critical.append(entry)


def _statuses(state: _State) -> list[dict[str, Any]]:
    """One status per obligation from all its evidence (evidence.py:835-841)."""
    statuses = []
    for obligation in state.expected:
        found = state.candidates[obligation.id]
        result = best([r for r, _, _ in found], obligation.id in state.waivers)
        status: dict[str, Any] = {
            "obligation": as_json(obligation),
            "result": result,
            "sources": list(dict.fromkeys(s for _, s, _ in found)),
            "reasons": list(dict.fromkeys(reason for _, _, reason in found if reason)),
        }
        if result == "waived" and state.waivers.get(obligation.id):
            status["waiver"] = dict(state.waivers[obligation.id])
        statuses.append(status)
    return statuses


def _facets(state: _State, statuses: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    """Each level's worst status per requirement, part, interface, operation and product
    (evidence.py:1047)."""
    collected: dict[str, dict[str, list[str]]] = {}

    def add(key: str, level: str, result: str) -> None:
        collected.setdefault(key, {}).setdefault(level, []).append(result)

    for obligation, status in zip(state.expected, statuses, strict=True):
        subject, level = subject_of(obligation), obligation.level.value
        add(fp.subject_key(subject), level, status["result"])
        for req in {obligation.requirement, *items(subject.get("requirements"))} - {None}:
            add(str(req), level, status["result"])
    for (req, level), results in state.untargeted.items():
        if level in LEVELS:
            add(req, level, best(results, False))
    record = state.record
    return facets(collected, {"product", *record.parts, *record.interfaces, *record.requirements})


def _verification(state: _State, table: Mapping[str, Mapping[str, str]]) -> None:
    """A stated pass, waiver or not_assessed in verification.csv that the evidence does not show is a
    finding: a CSV result alone is not evidence (evidence.py:1069-1102)."""
    for index, row in enumerate(state.record.verification):
        req = str(row.get("requirement") or "")
        levels = [result for result in (table.get(req) or {}).values() if result != NOT_REQUIRED]
        shown = worst(levels) or "unknown"
        stated = str(row.get("result") or "").strip()
        if (
            (stated == "pass" and shown != "pass")
            or (stated == "waived" and shown not in ("pass", "waived"))
            or (stated == "not_assessed" and shown != "not_assessed")
        ):
            message = (
                f"{req} states {stated} but its accepted evidence shows {shown}: record current evidence in "
                "hw/manufacturing/evidence.yaml (a CSV result alone is not evidence)"
            )
            pointer = f"/{index}/result"
            state.findings.append(
                _finding("evidence.csv_unsupported", "error", "hw/verification.csv", message, pointer=pointer)
            )


def _acceptance(state: _State) -> dict[str, Any]:
    refusals = [f for f in state.findings if f.code in PATH_CODES or f.code == "evidence.refused_dependency"]
    if refusals:
        return {"status": "refused", "reason": "; ".join(f"{f.path}: {f.message}" for f in refusals)}
    # every collected sealed and bound packet, including one the assessment refuses (evidence.py:1326-1334)
    found, reason = acceptance_inventory(state.record, state.built.packets, state.built.files)
    if found is None:
        return {"status": "refused", "reason": reason}
    return {"status": "formed", "evidence_sha256": acceptance_digest(found), "inventory": found}


def assess(record: Record, built: BuiltVersion, today: date) -> EvidenceAssessment:
    """The evidence assessment of `record` for the built version `built`; `today` judges valid_until."""
    record_view = view(record)
    placed, _ = inventory(record.assembly, record.parts)
    expected = required_checks(record_view)
    state = _State(
        record_view,
        placed,
        built,
        today,
        expected,
        {o.id: o for o in expected},
        {o.id: [] for o in expected},
    )
    _record_sources(state)
    _packet_sources(state)
    _ledger_sources(state)
    _path_refusals(state)
    _dispositions(state)
    statuses = _statuses(state)
    table = _facets(state, statuses)
    _verification(state, table)
    return EvidenceAssessment.model_validate(
        {
            "version": built.label,
            "manifest_sha256": built.manifest_sha256,
            "build_staleness": "computed" if isinstance(built.staleness, ChangedSinceBuild) else NOT_COMPUTED,
            "expected_sha256": expected_digest(as_json(o) for o in expected),
            "statuses": statuses,
            "facets": table,
            "findings": [as_json(f) for f in state.findings],
            "critical": state.critical,
            "complete": state.complete,
            "acceptance": _acceptance(state),
        }
    )
