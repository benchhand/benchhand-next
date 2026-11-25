"""Obligation enumeration: every check the record implies, before any producer runs.

A port of the prototype's manufacturing_intent.required_checks (skills/cad-record/scripts/
manufacturing_intent.py at release.toml reference_commit 412b5d9, lines 2557-2848). An obligation is the
generated model of contracts/record/common `obligation`. A producer cannot shrink this list by omission; an
unknown route kind gets process.<kind>.coverage, which no handler can pass.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from benchhand_contracts.models.record.common_schema import Obligation

from benchhand_core.record.evidence.view import JsonMap, RecordView, is_fact, items, mapping
from benchhand_core.record.model import as_json

# Per route kind: (check family, evidence level, stage due) (manufacturing_intent.py:2578 PROCESS_CHECKS).
PROCESS_CHECKS: Mapping[str, tuple[tuple[str, str, str], ...]] = {
    "fdm": (
        ("orientation", "process_planned", "detail"),
        ("geometry", "geometrically_manufacturable", "parts"),
        ("support", "process_planned", "detail"),
        ("thermal_distortion", "geometrically_manufacturable", "detail"),
        ("trial", "physically_validated", "release"),
    ),
    "resin": (
        ("orientation", "process_planned", "detail"),
        ("geometry", "geometrically_manufacturable", "parts"),
        ("support", "process_planned", "detail"),
        ("drainage", "geometrically_manufacturable", "detail"),
        ("post_cure", "process_planned", "detail"),
        ("trial", "physically_validated", "release"),
    ),
    "cnc": (
        ("stock", "process_planned", "parts"),
        ("setup", "process_planned", "detail"),
        ("access", "geometrically_manufacturable", "detail"),
        ("features", "geometrically_manufacturable", "parts"),
        ("precision", "process_planned", "detail"),
    ),
    "laser": (
        ("material", "process_planned", "parts"),
        ("kerf", "geometrically_manufacturable", "detail"),
        ("features", "geometrically_manufacturable", "parts"),
        ("thermal", "process_planned", "detail"),
        ("nesting", "process_planned", "detail"),
        ("fit_coupon", "physically_validated", "release"),
    ),
    "waterjet": (
        ("material", "process_planned", "parts"),
        ("kerf", "geometrically_manufacturable", "detail"),
        ("features", "geometrically_manufacturable", "parts"),
        ("edge", "process_planned", "detail"),
    ),
    "plasma": (
        ("material", "process_planned", "parts"),
        ("kerf", "geometrically_manufacturable", "detail"),
        ("features", "geometrically_manufacturable", "parts"),
        ("thermal", "process_planned", "detail"),
    ),
    "sheet_forming": (
        ("bend", "geometrically_manufacturable", "detail"),
        ("sequence", "process_planned", "detail"),
        ("distortion", "process_planned", "detail"),
    ),
    "casting": (
        ("draft", "geometrically_manufacturable", "detail"),
        ("walls", "geometrically_manufacturable", "parts"),
        ("tooling", "process_planned", "detail"),
        ("defects", "process_planned", "detail"),
    ),
    "moulding": (
        ("draft", "geometrically_manufacturable", "detail"),
        ("walls", "geometrically_manufacturable", "parts"),
        ("tooling", "process_planned", "detail"),
        ("defects", "process_planned", "detail"),
    ),
    "extrusion": (
        ("profile", "geometrically_manufacturable", "parts"),
        ("secondary", "process_planned", "detail"),
    ),
    "drilling": (
        ("access", "geometrically_manufacturable", "detail"),
        ("feature", "geometrically_manufacturable", "detail"),
    ),
    "reaming": (
        ("access", "geometrically_manufacturable", "detail"),
        ("allowance", "process_planned", "detail"),
    ),
    "tapping": (
        ("access", "geometrically_manufacturable", "detail"),
        ("engagement", "geometrically_manufacturable", "detail"),
    ),
    "finishing": (
        ("allowance", "process_planned", "detail"),
        ("access", "geometrically_manufacturable", "detail"),
    ),
    "coating": (("allowance", "process_planned", "detail"), ("access", "process_planned", "detail")),
    "joining": (
        ("access", "geometrically_manufacturable", "detail"),
        ("distortion", "process_planned", "detail"),
    ),
    "inspection": (
        ("access", "geometrically_manufacturable", "detail"),
        ("capability", "process_planned", "detail"),
    ),
    "purchased": (
        ("identity", "process_planned", "parts"),
        ("rating", "process_planned", "parts"),
        ("dimensions", "geometrically_manufacturable", "parts"),
        ("mounting", "process_planned", "detail"),
        ("availability", "process_planned", "parts"),
    ),
}
# manufacturing_intent.py:78-82: the route kinds with a check contract.
KNOWN_ROUTE_KINDS = frozenset(PROCESS_CHECKS)
ADDITIVE_KINDS = frozenset({"fdm", "resin"})
LEVEL_STAGE = {
    "cad_valid": "layout",
    "geometrically_manufacturable": "parts",
    "process_planned": "detail",
    "simulation_supported": "analysis",
    "physically_validated": "release",
}
# The assembly operation kinds that make a joint (manufacturing_intent.py:2620 JOINING_KINDS).
JOINING_KINDS = frozenset(("press_fit", "heat_set", "retaining_ring", "insert", "fasten", "join"))
# (function, family, level) (manufacturing_intent.py:2779 _FUNCTION_CHECKS).
FUNCTION_CHECKS = (
    ("rotating", "contact.wear", "physically_validated"),
    ("sliding", "contact.wear", "physically_validated"),
    ("rotating", "motion.play", "simulation_supported"),
    ("sliding", "motion.play", "simulation_supported"),
    ("locating", "feature.datum", "process_planned"),
    ("sealing", "function.sealing", "physically_validated"),
    ("spring", "function.spring", "physically_validated"),
    ("thermal", "function.thermal", "physically_validated"),
    ("electrical", "function.electrical", "physically_validated"),
    ("other", "function.other", "physically_validated"),
)
NO_INTENT = {"status": "unknown", "reason": "part.yaml has no intent"}

Add = Callable[..., None]


def obligation_anchor(subject: Mapping[str, Any]) -> str:
    """product, PN[.component][/operation][#feature], IF[#feature], REQ or op:<id>
    (manufacturing_intent.py:2621)."""
    if subject.get("PN"):
        anchor = str(subject["PN"])
        if subject.get("component"):
            anchor += f".{subject['component']}"
        if subject.get("operation"):
            anchor += f"/{subject['operation']}"
        if subject.get("feature"):
            anchor += f"#{subject['feature']}"
        return anchor
    if subject.get("interface"):
        return str(subject["interface"]) + (f"#{subject['feature']}" if subject.get("feature") else "")
    if subject.get("assembly_operation"):
        return f"op:{subject['assembly_operation']}"
    if subject.get("requirements"):
        return str(list(subject["requirements"])[0])
    return "product"


def subject_of(obligation: Obligation) -> JsonMap:
    """An obligation's subject as its JSON."""
    return as_json(obligation.subject)


def _intent(part: JsonMap) -> JsonMap:
    """A part's intent; a part without one has every intent input unknown (manufacturing_intent.py:1700)."""
    intent = part.get("intent")
    if isinstance(intent, Mapping):
        return intent
    return {
        key: NO_INTENT for key in ("functions", "material_profile", "critical_surfaces", "route", "service")
    }


def _components(intent: JsonMap) -> tuple[str | None, ...]:
    return tuple(item.get("id") for item in items(intent.get("components")) if isinstance(item, Mapping)) or (
        None,
    )


def _functions(intent: JsonMap) -> tuple[str, ...]:
    """The part's and its components' functions (manufacturing_intent.py:2742)."""
    own = () if is_fact(intent.get("functions")) else items(intent.get("functions"))
    found = [entry.get("function") for entry in own if isinstance(entry, Mapping)]
    for component in items(intent.get("components")):
        for entry in items(mapping(component).get("functions")):
            found.append(mapping(entry).get("function"))
    return tuple(name for name in found if isinstance(name, str))


def _route(intent: JsonMap) -> list[JsonMap]:
    route = intent.get("route")
    return [] if is_fact(route) else [op for op in items(route) if isinstance(op, Mapping)]


def _intent_checks(pn: str, intent: JsonMap, made: bool, add: Add) -> None:
    """intent.* obligations for unknown inputs that hide checks (manufacturing_intent.py:2701-2714)."""
    base = {"PN": pn}
    functions, material = intent.get("functions"), intent.get("material_profile")
    surfaces, route = intent.get("critical_surfaces"), intent.get("route")
    if is_fact(functions):
        add("intent.functions", base, "process_planned", "parts", f"{pn} functions are {functions['status']}")
    if made and is_fact(material) and material["status"] != "not_applicable":
        add(
            "intent.material",
            base,
            "process_planned",
            "parts",
            f"{pn} material profile is {material['status']}",
        )
    if made and is_fact(surfaces) and surfaces["status"] == "unknown":
        add(
            "intent.critical_surfaces",
            base,
            "process_planned",
            "detail",
            f"{pn} critical surfaces are unknown",
        )
    if is_fact(route):
        add(
            "intent.route",
            base,
            "process_planned",
            "parts",
            f"{pn} route is {route['status']}: its process checks are unknown",
        )


def _made_checks(pn: str, part: JsonMap, components: tuple[str | None, ...], add: Add) -> None:
    """Geometry, route consistency and export checks of a custom-made part (manufacturing_intent.py:2716)."""
    base = {"PN": pn}
    for component in components:
        add(
            "cad.readback",
            {**base, "component": component},
            "cad_valid",
            "layout",
            f"{pn}: B-rep validity, readback, manufacturing state and component identity",
        )
        add(
            "route.consistency",
            {**base, "component": component},
            "process_planned",
            "parts",
            f"{pn}: route, profile, material and capability consistency",
        )
    add(
        "cad.glb_step_agreement",
        base,
        "cad_valid",
        "layout",
        f"{pn}: each occurrence's assembly.glb node shows its assembly.step shape and placement",
    )
    if part.get("process") == "fdm":
        add(
            "export.3mf",
            base,
            "cad_valid",
            "layout",
            f"{pn}: part.3mf, the FDM part's 3MF export of geometry, material and colour",
        )


def _route_checks(pn: str, intent: JsonMap, components: tuple[str | None, ...], add: Add) -> None:
    """Each route operation x its kind's check families, per component (manufacturing_intent.py:2725)."""
    for op in _route(intent):
        named = items(op.get("components"))
        targets = [c for c in components if c is None or not named or c in named]
        kind = op.get("kind")
        checks = PROCESS_CHECKS.get(kind) if isinstance(kind, str) else None
        for component in targets if kind != "purchased" else [None]:
            subject = {"PN": pn, "component": component, "operation": op.get("id")}
            if checks is None:
                basis = f"{pn} {op.get('id')}: route kind {kind} has no check contract"
                add(f"process.{kind}.coverage", subject, "process_planned", "parts", basis)
                continue
            prefix = "purchase" if kind == "purchased" else f"process.{kind}"
            for family, level, stage in checks:
                add(f"{prefix}.{family}", subject, level, stage, f"{pn} {op.get('id')}: {kind} operation")
            if kind != "purchased":
                add(
                    "route.operation_plan",
                    subject,
                    "process_planned",
                    "detail",
                    f"{pn} {op.get('id')}: setup, orientation, supports, allowances and inspection",
                )


def _optical_checks(pn: str, part: JsonMap, functions: tuple[str, ...], add: Add) -> None:
    """manufacturing_intent.py:2744."""
    if "optical" not in functions and part.get("transparency") not in ("translucent", "transparent"):
        return
    base = {"PN": pn}
    add(
        "optical.route",
        base,
        "process_planned",
        "parts",
        f"{pn} has an optical requirement: only a purchased transparent part or identified transparent stock "
        "on a suitable route qualifies; opaque processes are eliminated",
    )
    add(
        "optical.transmission",
        base,
        "physically_validated",
        "release",
        f"{pn}: sourced optical grade and transmission",
    )


def part_loads(record: RecordView, intent: JsonMap) -> tuple[JsonMap, ...] | None:
    """The use-case loads a part carries, None while they are unknown (manufacturing_intent.py:2788)."""
    service, loads = intent.get("service"), record.use_case.get("loads")
    if is_fact(service) or not isinstance(loads, list):
        return None
    wanted = mapping(service).get("loads")
    if not wanted:
        return None
    return tuple(load for load in loads if isinstance(load, Mapping) and load.get("id") in wanted)


def _structural_checks(record: RecordView, pn: str, intent: JsonMap, add: Add) -> None:
    """manufacturing_intent.py:2751-2768."""
    base = {"PN": pn}
    add("engineering.strength", base, "simulation_supported", "analysis", f"{pn} is structural")
    add("engineering.stiffness", base, "simulation_supported", "analysis", f"{pn} is structural")
    loads = part_loads(record, intent)
    if loads is None:
        add(
            "engineering.load_cases",
            base,
            "simulation_supported",
            "analysis",
            f"{pn} is structural and its loads are unknown: creep, fatigue and impact applicability is "
            "unknown",
        )
    else:
        kinds = {load.get("kind") for load in loads}
        if "sustained" in kinds:
            add(
                "engineering.creep",
                base,
                "physically_validated",
                "analysis",
                f"{pn} carries a sustained load",
            )
        if kinds & {"cyclic", "vibration"}:
            add(
                "engineering.fatigue", base, "physically_validated", "analysis", f"{pn} carries a cyclic load"
            )
        if "impact" in kinds:
            add(
                "engineering.impact", base, "physically_validated", "analysis", f"{pn} carries an impact load"
            )
    if any(op.get("kind") in ADDITIVE_KINDS for op in _route(intent)):
        add(
            "engineering.anisotropy",
            base,
            "simulation_supported",
            "analysis",
            f"{pn} is structural and additive: layer direction against its loads",
        )


def _feature_checks(pn: str, intent: JsonMap, functions: tuple[str, ...], add: Add) -> None:
    """Critical surfaces and function-driven checks (manufacturing_intent.py:2769-2777)."""
    surfaces = intent.get("critical_surfaces")
    for surface in [] if is_fact(surfaces) else items(surfaces):
        surface = mapping(surface)
        subject = {"PN": pn, "component": surface.get("component"), "feature": surface.get("feature")}
        ident, role = surface.get("id"), surface.get("role")
        add("feature.fit", subject, "process_planned", "detail", f"{pn} {ident}: {role} finished fit")
        add(
            "feature.inspection",
            subject,
            "physically_validated",
            "release",
            f"{pn} {ident}: inspected finished dimensions",
        )
    for function, family, level in FUNCTION_CHECKS:
        if function in functions:
            stage = "detail" if level == "process_planned" else "analysis"
            add(family, {"PN": pn}, level, stage, f"{pn} function {function}")


def _part_checks(record: RecordView, pn: str, part: JsonMap, add: Add) -> None:
    """manufacturing_intent.py:2701 `_part_checks`."""
    intent, made = _intent(part), record.made(pn)
    components = _components(intent)
    _intent_checks(pn, intent, made, add)
    if made:
        _made_checks(pn, part, components, add)
    _route_checks(pn, intent, components, add)
    functions = _functions(intent)
    _optical_checks(pn, part, functions, add)
    if not made:
        return  # a catalogue item's function is its rating: the purchase checks cover it
    if "structural" in functions:
        _structural_checks(record, pn, intent, add)
    _feature_checks(pn, intent, functions, add)


def heat_set_feature(entry: int) -> str:
    """The feature naming the entry-th (0-based) limits.heat_set declaration
    (manufacturing_intent.py:2800)."""
    return f"heat_set_{entry + 1}"


def _heat_set_checks(if_id: str, interface: JsonMap, add: Add) -> None:
    """manufacturing_intent.py:2806."""
    for entry in range(len(items(mapping(interface.get("limits")).get("heat_set")))):
        add(
            "cad.declared_dimensions",
            {"interface": if_id, "feature": heat_set_feature(entry)},
            "cad_valid",
            "layout",
            f"{if_id} heat_set {entry + 1}: the declared hole_diameter_mm is a bore of its host in the "
            "sealed model",
        )


def _acceptance_checks(if_id: str, functional: JsonMap, add: Add) -> None:
    for index, acceptance in enumerate(items(functional.get("acceptance"))):
        acceptance = mapping(acceptance)
        name = mapping(acceptance.get("criterion")).get("id") or f"criterion_{index + 1}"
        for level in items(mapping(acceptance.get("verification")).get("evidence_required")):
            subject = {"interface": if_id, "feature": name}
            stage = LEVEL_STAGE.get(level, "detail")
            add(
                f"interface.acceptance.{level}",
                subject,
                level,
                stage,
                f"{if_id} acceptance {name}",
                criterion=name,
            )


def _interface_checks(if_id: str, interface: JsonMap, add: Add) -> None:
    """manufacturing_intent.py:2818."""
    functional = mapping(interface.get("functional"))
    base = {"interface": if_id}
    critical = functional.get("critical")
    status = critical.get("status") if is_fact(critical) else "unknown"
    if status != "known":
        if status != "not_applicable":
            add("intent.interface", base, "process_planned", "parts", f"{if_id} criticality is unknown")
        return
    if not is_fact(critical) or critical.get("value") is not True:
        return
    add(
        "interface.fit",
        base,
        "process_planned",
        "detail",
        f"{if_id} is critical: intended fit after tolerances",
    )
    add(
        "interface.stack",
        base,
        "process_planned",
        "detail",
        f"{if_id} is critical: worst-case stack with manufacturing, assembly, thermal, moisture, wear and "
        "deformation contributors",
    )
    _acceptance_checks(if_id, functional, add)
    contact = mapping(functional.get("contact"))
    if functional.get("contact"):
        basis = f"{if_id}: contacting pair friction, wear and life"
        add("contact.compatibility", base, "physically_validated", "analysis", basis)
    entries = functional.get("functions")
    functions = set() if is_fact(entries) else {mapping(e).get("function") for e in items(entries)}
    load = contact.get("load")
    loaded = functional.get("loads") or (isinstance(load, Mapping) and load.get("status") == "known")
    if "structural" in functions and loaded:
        add(
            "engineering.stop_reaction",
            base,
            "simulation_supported",
            "layout",
            f"{if_id} is critical, structural and loaded: the reaction its contact carries, from the "
            "modelled "
            "contact",
        )
    if functional.get("play") or functions & {"rotating", "sliding"}:
        basis = f"{if_id}: function under play and tolerance extremes"
        add("motion.play", base, "simulation_supported", "analysis", basis)


def _assembly_checks(record: RecordView, add: Add) -> None:
    """Order, access and joint evidence per assembly operation (manufacturing_intent.py:2668-2684)."""
    operations = record.operations
    if is_fact(operations) or not isinstance(operations, list):
        status = operations["status"] if is_fact(operations) else "unknown"
        if status != "not_applicable":
            add(
                "intent.assembly_operations",
                {"product": True},
                "process_planned",
                "detail",
                f"the assembly operations are {status}: installation order and access stay unchecked",
            )
        return
    for operation in operations:
        ident = mapping(operation).get("id")
        if not isinstance(ident, str):
            continue
        subject = {"assembly_operation": ident}
        basis = f"assembly operation {ident}"
        add(
            "assembly.order", subject, "process_planned", "detail", f"{basis}: installation order and closure"
        )
        add(
            "assembly.access",
            subject,
            "geometrically_manufacturable",
            "detail",
            f"{basis}: part path and tool reach",
        )
        if operation.get("kind") in JOINING_KINDS:
            add(
                "assembly.joint",
                subject,
                "process_planned",
                "detail",
                f"{basis}: engagement, edge distance, retention, torque and host suitability",
            )
    add(
        "assembly.order",
        {"product": True},
        "process_planned",
        "detail",
        "every assembly occurrence is installed by an operation, apart from the assembly's one base",
    )


def _requirement_checks(record: RecordView, add: Add) -> None:
    """Requirement evidence levels and the approved evidence policy (manufacturing_intent.py:2685-2698)."""
    for req_id, requirement in sorted(record.requirements.items()):
        for level in items(requirement.get("evidence_required")):
            subject = {"product": True, "requirements": [req_id]}
            stage = LEVEL_STAGE[level]
            basis = f"{req_id} evidence_required {level}"
            add(f"requirement.{level}", subject, level, stage, basis, requirement=req_id)
    policy = record.use_case.get("evidence_policy")
    if not isinstance(policy, Mapping) or "obligations" not in policy:
        return
    for item in items(policy.get("obligations")):
        item = mapping(item)
        level, requirement = item.get("level"), item.get("requirement")
        subject = item.get("subject") or (
            {"product": True, "requirements": [requirement]} if requirement else None
        )
        if subject is not None and level in LEVEL_STAGE:
            stage = LEVEL_STAGE[level]
            basis = "the approved evidence policy"
            add(f"policy.{level}", subject, level, stage, basis, requirement=requirement)


def required_checks(record: RecordView) -> tuple[Obligation, ...]:
    """Every check obligation the record implies, sorted by id (manufacturing_intent.py:2642). The first
    obligation enumerated for an id wins."""
    found: dict[str, Obligation] = {}

    def add(
        family: str, subject: Mapping[str, Any], level: str, stage: str, basis: str, **named: str
    ) -> None:
        """`named` holds the optional requirement and criterion the obligation derives from."""
        clean = {key: value for key, value in subject.items() if value is not None}
        ident = f"{family}@{obligation_anchor(clean)}"
        if ident in found:
            return
        data: dict[str, Any] = {
            "id": ident,
            "family": family,
            "subject": clean,
            "level": level,
            "stage": stage,
            "basis": basis,
        }
        data.update({key: value for key, value in named.items() if value})
        found[ident] = Obligation.model_validate(data)

    add(
        "intent.use_case",
        {"product": True},
        "process_planned",
        "intent",
        "a final material and process recommendation needs a confirmed use case",
    )
    for pn, part in sorted(record.parts.items()):
        _part_checks(record, pn, part, add)
    for if_id, interface in sorted(record.interfaces.items()):
        _heat_set_checks(if_id, interface, add)
        _interface_checks(if_id, interface, add)
    _assembly_checks(record, add)
    _requirement_checks(record, add)
    return tuple(found[key] for key in sorted(found))
