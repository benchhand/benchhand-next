"""Producer packets: whether a sealed required-check packet counts, and what each outcome shows.

A port of the prototype's evidence.py (skills/cad-record/scripts/evidence.py at release.toml reference_commit
412b5d9): `_packet_problems` (lines 876-906) and the outcome loop of `assess` (750-790). The reader refuses a
bundle whose result.json breaks the manufacturing-check-result contract, fails its seal or is bound to
another build (evidence.py:1185-1228).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from benchhand_contracts.models.record.common_schema import Obligation

from benchhand_core.record.evidence.built import BuiltVersion, ChangedSinceBuild, NotComputed, Packet
from benchhand_core.record.evidence.fingerprints import RECORD_FAMILIES
from benchhand_core.record.evidence.results import PHYSICAL
from benchhand_core.record.evidence.view import JsonMap, items, mapping
from benchhand_core.record.finding import Finding

Candidate = tuple[str, str, str]  # (result, source, reason)


def packet_finding(
    code: str, severity: str, bundle: str, message: str, subject: str | None = None
) -> Finding:
    data = {"code": code, "severity": severity, "path": f"{bundle}/result.json", "message": message}
    return Finding.model_validate({**data, **({"subject": subject} if subject else {})})


def _shown(outcomes: list[JsonMap], covered: bool) -> str:
    """The packet result its outcomes show: fail, else unknown (or incomplete), else not_assessed, else
    pass."""
    results = {o.get("outcome") for o in outcomes}
    if "fail" in results:
        return "fail"
    if "unknown" in results or not covered:
        return "unknown"
    return "not_assessed" if "not_assessed" in results else "pass"


def packet_problems(data: JsonMap, expected: Mapping[str, Obligation]) -> list[str]:
    """Why a packet cannot be counted: it contradicts itself or the record (evidence.py:876)."""
    outcomes = [mapping(o) for o in items(data.get("outcomes"))]
    ids = [o.get("obligation") for o in outcomes]
    problems = []
    if len(ids) != len(set(ids)):
        problems.append("it gives an obligation two outcomes")
    own = {mapping(o).get("id"): mapping(o) for o in items(data.get("expected"))}
    if set(ids) - set(own):
        extra = ", ".join(sorted(map(str, set(ids) - set(own))))
        problems.append(f"outcomes for obligations it did not expect: {extra}")
    for ident, item in own.items():
        mine = expected.get(ident) if isinstance(ident, str) else None
        if mine is not None and (item.get("level"), item.get("stage"), item.get("family")) != (
            mine.level.value,
            mine.stage.value,
            mine.family,
        ):
            problems.append(f"it expects {ident} at another level, stage or family than the record")
    covered = set(own) <= set(ids)
    if data.get("complete") is True and not covered:
        missing = ", ".join(sorted(map(str, set(own) - set(ids))))
        problems.append(f"it claims complete but lacks outcomes for {missing}")
    shown = _shown(outcomes, covered)
    if data.get("result") != shown:
        problems.append(f"its result {data.get('result')!r} is not what its outcomes show ({shown})")
    given = {o.get("obligation"): o.get("outcome") for o in outcomes}
    for item in items(data.get("findings")):
        item = mapping(item)
        if item.get("outcome") == "fail" and given.get(item.get("obligation")) == "pass":
            failed = item.get("obligation")
            problems.append(f"its finding {item.get('id')} fails {failed}, whose outcome it gives as pass")
    return problems


GUIDELINE_CATALOG_MISSING = (
    "guideline.catalog_missing: the build resolved shipped guideline sets, but no shipped catalog is read now"
)


@dataclass
class OutcomeReading:
    """What a packet's outcomes added: candidates per obligation id, and findings."""

    candidates: dict[str, list[Candidate]]
    findings: list[Finding]


def _staleness(
    ident: str, result: str, staleness: ChangedSinceBuild | NotComputed, stale: Mapping, catalog_missing: bool
) -> Candidate | None:
    """A pass, fail or not_applicable whose inputs changed since the build is stale; one whose staleness was
    not computed counts as unknown (evidence.py:782-785, and the supervisor's not_computed rule)."""
    if result not in ("pass", "fail", "not_applicable"):
        return None
    if isinstance(staleness, NotComputed):
        return ("unknown", "", f"not_computed: build staleness is not computed ({staleness.reason})")
    if ident in stale:
        reason = "its inputs changed since the version was built: " + ", ".join(stale[ident])
        if catalog_missing and "source" in stale[ident]:
            reason = f"{GUIDELINE_CATALOG_MISSING}; {reason}"
        return ("stale", "", reason)
    return None


def _outcome(
    outcome: JsonMap, obligation: Obligation | None, packet: Packet, reading: OutcomeReading
) -> str | None:
    """The outcome's result, or None when it counts for nothing (a finding may say why)."""
    ident, result, bundle = outcome.get("obligation"), outcome.get("outcome"), packet.bundle
    record_family = obligation is not None and obligation.family.startswith(RECORD_FAMILIES)
    if record_family and result == "unknown":
        return None  # a producer naming a record-derived unknown claims nothing
    if obligation is None or record_family:
        message = f"{bundle}: outcome for {ident}, which this record does not expect from a producer"
        reading.findings.append(packet_finding("packet.unexpected", "warning", bundle, message))
        return None
    if outcome.get("level") not in (None, obligation.level.value):
        level = obligation.level.value
        message = f"{bundle}: {ident} is shown at {outcome.get('level')}, not its level {level}"
        finding = packet_finding("packet.unexpected", "warning", bundle, message, obligation.id)
        reading.findings.append(finding)
        return None
    if obligation.level.value == PHYSICAL and result == "not_assessed":
        return None  # not_assessed covers the tool's own checks, never a test the user must perform
    if obligation.level.value == PHYSICAL and result == "pass":
        message = (
            f"{bundle}: a producer cannot physically validate {ident}; record the test in "
            "hw/manufacturing/evidence.yaml"
        )
        finding = packet_finding("evidence.physical_claim", "error", bundle, message, obligation.id)
        reading.findings.append(finding)
        return None
    return str(result)


def read_outcomes(
    packet: Packet,
    expected: Mapping[str, Obligation],
    built: BuiltVersion,
    stale: Mapping[str, tuple[str, ...]],
    reading: OutcomeReading,
) -> None:
    """Add what each outcome of an accepted packet shows (evidence.py:760-790)."""
    for outcome in items(packet.data.get("outcomes")):
        outcome = mapping(outcome)
        ident = str(outcome.get("obligation"))
        result = _outcome(outcome, expected.get(ident), packet, reading)
        if result is None:
            continue
        found = _staleness(ident, result, built.staleness, stale, built.guideline_catalog_missing)
        if found is not None:
            reading.candidates[ident].append((found[0], packet.bundle, found[2]))
        elif result == "not_assessed":
            reading.candidates[ident].append((result, packet.bundle, str(outcome.get("reason") or "")))
        else:
            reading.candidates[ident].append((result, packet.bundle, str(outcome.get("method") or "")))
