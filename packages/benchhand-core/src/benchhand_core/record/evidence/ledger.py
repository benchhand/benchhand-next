"""The status one accepted ledger entry (hw/manufacturing/evidence.yaml) shows for the assessed version.

A port of the prototype's evidence.py `_entry` (skills/cad-record/scripts/evidence.py at release.toml
reference_commit 412b5d9, lines 941-1006), `_entry_targets` (932), `_REQUIRED_DOMAINS` (130-155),
`_subject_kind` (316) and `_owning_version` (330). Without a path rule (evidence_paths.py, left out),
every structured path is a contract project_path below hw/.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from benchhand_contracts.models.record.common_schema import Obligation

from benchhand_core.record.evidence import fingerprints as fp
from benchhand_core.record.evidence.built import BuiltVersion
from benchhand_core.record.evidence.digest import MANIFEST
from benchhand_core.record.evidence.obligations import obligation_anchor, subject_of
from benchhand_core.record.evidence.packets import GUIDELINE_CATALOG_MISSING
from benchhand_core.record.evidence.paths import entry_problems as path_problems
from benchhand_core.record.evidence.results import LEVELS, PHYSICAL
from benchhand_core.record.evidence.view import JsonMap, RecordView, items, mapping
from benchhand_core.record.evidence.waivers import WaiverScope, waiver_problem
from benchhand_core.record.finding import Finding
from benchhand_core.record.rules.assembly import Inventory

EVIDENCE = "hw/manufacturing/evidence.yaml"
# Fingerprint domains pass or fail evidence must record, by subject kind and level (evidence.py:130).
REQUIRED_DOMAINS: Mapping[str, Mapping[str, frozenset[str]]] = {
    "made": {
        "cad_valid": frozenset({"geometry"}),
        "geometrically_manufacturable": frozenset({"geometry", "route"}),
        "process_planned": frozenset({"route", "capability", "material"}),
        "simulation_supported": frozenset({"geometry", "material", "load", "criterion"}),
        PHYSICAL: frozenset({"geometry", "material", "route", "criterion"}),
    },
    "bought": {
        "cad_valid": frozenset({"geometry"}),
        "geometrically_manufacturable": frozenset({"geometry", "route"}),
        "process_planned": frozenset({"route"}),
        "simulation_supported": frozenset({"route", "load", "criterion"}),
        PHYSICAL: frozenset({"route", "criterion"}),
    },
    "interface": {
        "cad_valid": frozenset({"geometry", "interface"}),
        "geometrically_manufacturable": frozenset({"geometry", "interface"}),
        "process_planned": frozenset({"geometry", "interface", "criterion"}),
        "simulation_supported": frozenset({"geometry", "interface", "material", "criterion"}),
        PHYSICAL: frozenset({"geometry", "interface", "material", "criterion"}),
    },
    "operation": {level: frozenset({"geometry", "interface"}) for level in LEVELS},
    "product": {
        "cad_valid": frozenset({"geometry", "criterion"}),
        "geometrically_manufacturable": frozenset({"geometry", "criterion"}),
        "process_planned": frozenset({"criterion", "use_case"}),
        "simulation_supported": frozenset({"geometry", "criterion", "use_case"}),
        PHYSICAL: frozenset({"geometry", "criterion", "use_case"}),
    },
}
# The version-bound roots below hw/ (layout.json bundle.* entries, and versions/).
BUNDLE_ROOTS = ("versions", "checks", "drawings", "renders", "captures", "motion", "analysis")
_OWNER = re.compile(rf"^hw/(?:{'|'.join(BUNDLE_ROOTS)})/(v[1-9][0-9]*)(?:/|$)")
LOCATION_KEYS = ("product", "PN", "component", "operation", "feature", "interface", "assembly_operation")
# The required fields of manufacturing-evidence `physical` (contracts/record/manufacturing-evidence.tsp).
PHYSICAL_FIELDS = (
    "specimen",
    "configuration",
    "material",
    "process",
    "protocol",
    "instrument",
    "results",
    "date",
    "approver",
    "scope",
)


@dataclass(frozen=True)
class EntryContext:
    record: RecordView
    inventory: Inventory | None
    expected: Mapping[str, Obligation]
    built: BuiltVersion
    today: date


@dataclass(frozen=True)
class EntryJudgement:
    result: str
    reasons: tuple[str, ...]
    findings: tuple[Finding, ...] = ()


def entry_finding(code: str, index: int, message: str, subject: str | None = None) -> Finding:
    data = {"code": code, "severity": "error", "path": EVIDENCE, "pointer": f"/entries/{index}"}
    data["message"] = message
    return Finding.model_validate({**data, **({"subject": subject} if subject else {})})


def owning_version(path: str) -> str | None:
    """The version a project path is sealed under (evidence.py:330)."""
    match = _OWNER.match(path)
    return match.group(1) if match else None


def subject_kind(record: RecordView, subject: Mapping[str, object]) -> str:
    """evidence.py:316."""
    pn = subject.get("PN")
    if isinstance(pn, str) and pn:
        return "bought" if pn in record.parts and not record.made(pn) else "made"
    if subject.get("interface"):
        return "interface"
    if subject.get("assembly_operation"):
        return "operation"
    return "product"


def entry_targets(entry: JsonMap, expected: Sequence[Obligation]) -> list[str]:
    """The obligation an entry names, else the requirement and evidence-policy obligations of its
    requirement at its level (evidence.py:932)."""
    named = entry.get("obligation")
    if named:
        return [named] if any(o.id == named for o in expected) else []
    requirement, level = entry.get("requirement"), entry.get("level")
    families = (f"requirement.{level}", f"policy.{level}")
    return [o.id for o in expected if o.requirement == requirement and o.family in families]


def waiver_scope(entry: JsonMap, obligation: Obligation | None) -> WaiverScope:
    """What a waived entry asks to cover for one target: the entry's subject, the target obligation and the
    requirements that govern the target, read from the obligation's own requirement and subject
    (evidence.py:340-348 `_requirements_of`), with the entry's requirement."""
    governing = ()
    if obligation is not None:
        found = {obligation.requirement, *items(subject_of(obligation).get("requirements"))}
        governing = tuple(sorted(str(ident) for ident in found if ident))
    return WaiverScope(
        subject=mapping(entry.get("subject")),
        obligation=obligation.id if obligation else None,
        family=obligation.family if obligation else None,
        obligation_requirements=governing,
        requirements=(entry["requirement"],) if entry.get("requirement") else (),
    )


def _waived(entry: JsonMap, index: int, obligation: Obligation | None, ctx: EntryContext) -> EntryJudgement:
    ident, waiver = entry.get("id"), mapping(entry.get("waiver"))
    scope = waiver_scope(entry, obligation)
    problem = waiver_problem(waiver, scope, ctx.record, ctx.today)
    if problem is not None:
        finding = entry_finding(problem.code, index, f"{ident}: {problem.message}", scope.obligation)
        return EntryJudgement("unknown", (problem.message,), (finding,))
    return EntryJudgement("waived", (f"{ident} waived by {waiver.get('decision')}",))


def _configuration(entry: JsonMap, ctx: EntryContext) -> EntryJudgement | None:
    """Evidence of another build, or of another part revision, is stale (evidence.py:971-978)."""
    ident, configuration = entry.get("id"), mapping(entry.get("configuration"))
    built = ctx.built
    version = configuration.get("version")
    if version != built.label or configuration.get("manifest_sha256") != built.manifest_sha256:
        return EntryJudgement("stale", (f"{ident} is evidence of {version}, not the built {built.label}",))
    part = ctx.record.parts.get(mapping(entry.get("subject")).get("PN") or "")
    if part is not None and configuration.get("rev") not in (None, part.get("rev")):
        reason = f"{ident} is evidence of revision {configuration.get('rev')}, not {part.get('rev')}"
        return EntryJudgement("stale", (reason,))
    return None


def _fingerprinted(entry: JsonMap, index: int, ctx: EntryContext) -> EntryJudgement | None:
    """Unqualified evidence (no fingerprint of a required domain) counts as unknown; a changed dependency
    fingerprint makes it stale (evidence.py:979-990)."""
    ident, subject, level = entry.get("id"), mapping(entry.get("subject")), entry.get("level")
    recorded = mapping(entry.get("fingerprints"))
    current = fp.fingerprints(ctx.record, ctx.inventory, subject, ctx.built.current_geometry)
    required = REQUIRED_DOMAINS[subject_kind(ctx.record, subject)].get(str(level), frozenset())
    missing = sorted((required | set(fp.unrecorded_domains(entry, current))) - set(recorded))
    if missing:
        message = (
            f"{ident} ({level} {entry.get('result')}) records no fingerprint of {', '.join(missing)}: the "
            "evidence is not tied to what it relied on; recheck it"
        )
        finding = entry_finding("evidence.unqualified", index, message)
        return EntryJudgement("unknown", (f"{ident} is unqualified",), (finding,))
    changed = fp.evidence_staleness(entry, current)
    if changed:
        reason = f"{ident} relied on {', '.join(changed)} that changed"
        if ctx.built.guideline_catalog_missing and "source" in changed:
            reason = f"{GUIDELINE_CATALOG_MISSING}; {reason}"
        return EntryJudgement("stale", (reason,))
    return None


def _cited(entry: JsonMap) -> dict[str, object]:
    claimed = {mapping(a).get("path"): mapping(a).get("sha256") for a in items(entry.get("artifacts"))}
    bundle = entry.get("bundle")
    if isinstance(bundle, Mapping):
        claimed[f"{bundle.get('path')}/{MANIFEST}"] = bundle.get("manifest_sha256")
    return {str(path): sha for path, sha in claimed.items()}


def _bytes(entry: JsonMap, index: int, ctx: EntryContext) -> EntryJudgement | None:
    """Cited bytes that changed make the evidence stale; evidence sealed for another version needs an
    approving impact decision (evidence.py:991-1005)."""
    ident, label = entry.get("id"), ctx.built.label
    bundle = entry.get("bundle")
    if isinstance(bundle, Mapping):
        path = str(bundle.get("path"))
        problems = ctx.built.bundle_seals.get(path, (f"{path} was not verified",))
        if problems:
            message = f"{ident} cites {path}, which fails its seal: {'; '.join(problems)}"
            finding = entry_finding("evidence.bundle_seal", index, message)
            reason = f"stale: {ident} cites {path}, which fails its seal"
            return EntryJudgement("stale", (reason,), (finding,))
    claimed = _cited(entry)
    files = ctx.built.files
    drifted = sorted(path for path, sha in claimed.items() if getattr(files.get(path), "sha256", None) != sha)
    if drifted:
        return EntryJudgement("stale", (f"stale: {ident} cites {', '.join(drifted)}, which changed",))
    cited = [*claimed]
    if isinstance(entry.get("bundle"), Mapping):
        cited.append(str(entry["bundle"].get("path")))
    foreign = sorted({owner for path in cited if (owner := owning_version(path)) not in (None, label)})
    decisions = items(entry.get("decisions"))
    if foreign and not (decisions and all(ctx.record.approves(d) for d in decisions)):
        message = (
            f"{ident} cites evidence sealed for {', '.join(foreign)} as evidence of {label} without an "
            "approving impact decision; run impact and record the decision"
        )
        reason = f"{ident} is carried from {', '.join(foreign)} without an approved impact assessment"
        return EntryJudgement("stale", (reason,), (entry_finding("evidence.carry_forward", index, message),))
    return None


def judge_entry(entry: JsonMap, index: int, ctx: EntryContext) -> EntryJudgement:
    """The status one ledger entry shows, before it is credited to any target (evidence.py:941). An entry
    citing a file the record cannot hold is unknown (evidence.py:947-949). Whether it speaks to a target's
    level and subject is `credit`'s question."""
    ident, result = entry.get("id"), entry.get("result")
    named = entry.get("obligation")
    obligation = ctx.expected.get(named) if isinstance(named, str) else None
    refused = path_problems(ctx.built.path_verdicts, entry)
    if refused:
        about = obligation.id if obligation else None
        found = tuple(entry_finding(p.code, index, f"{ident}: {p.message}", about) for p in refused)
        return EntryJudgement("unknown", (f"{ident} cites files the record cannot hold",), found)
    if result in ("planned", "unknown"):
        return EntryJudgement(str(result), (f"{ident} is {result}",))
    if result == "waived":
        return _waived(entry, index, obligation, ctx)
    for rule in (_configuration(entry, ctx), _fingerprinted(entry, index, ctx), _bytes(entry, index, ctx)):
        if rule is not None:
            return rule
    return EntryJudgement(str(result), (f"{ident} {entry.get('level')} {result}",))


def location(subject: Mapping[str, object]) -> dict[str, object]:
    """Where a subject is: the product, a part (with component, operation and feature), an interface or an
    assembly operation. Its requirements, occurrence and region do not move it."""
    return {key: subject[key] for key in LOCATION_KEYS if subject.get(key)}


def _physical_gap(entry: JsonMap) -> list[str]:
    physical = mapping(entry.get("physical"))
    return [name for name in PHYSICAL_FIELDS if not physical.get(name)]


def credit(
    entry: JsonMap, index: int, judged: EntryJudgement, obligation: Obligation, ctx: EntryContext
) -> EntryJudgement:
    """What the judged entry credits one target: its judgement when the entry is evidence at the target's own
    level, about the target's exact location, and (for a physically_validated pass or fail) carries every
    physical test field the manufacturing-evidence contract requires; otherwise unknown, with a finding.

    The prototype has a gap here: evidence.py:932-939 (`_entry_targets`) credits an inferred requirement or
    policy target by requirement and level alone, and evidence.py:947-951 checks a named target's anchor but
    never compares the entry's level with the obligation's. A cad_valid entry could pass a
    physically_validated obligation, and one part's evidence a policy obligation of another."""
    ident, level = entry.get("id"), obligation.level.value
    where = obligation.id.split("@", 1)[1]
    subject = mapping(entry.get("subject"))
    if entry.get("level") != level:
        message = f"{ident} is {entry.get('level')} evidence; {obligation.id} asks {level}"
        finding = entry_finding("evidence.level", index, message, obligation.id)
        return EntryJudgement("unknown", (f"{ident} is evidence at another level",), (finding,))
    if location(subject) != location(subject_of(obligation)):
        message = (
            f"{ident} is about {obligation_anchor(subject)}, but {obligation.id} is about {where}: evidence "
            "covers its own subject only"
        )
        finding = entry_finding("evidence.subject", index, message, obligation.id)
        return EntryJudgement("unknown", (f"{ident} is about another subject",), (finding,))
    missing = _physical_gap(entry) if level == PHYSICAL and judged.result in ("pass", "fail") else []
    if missing:
        message = f"{ident} is physical evidence without {', '.join(missing)}: record the test it reports"
        finding = entry_finding("evidence.physical_fields", index, message, obligation.id)
        return EntryJudgement("unknown", (f"{ident} does not record its physical test",), (finding,))
    if judged.result == "waived":
        # the waiver must stand for this target and the requirements that govern it, not the entry's alone
        return _waived(entry, index, obligation, ctx)
    return judged
