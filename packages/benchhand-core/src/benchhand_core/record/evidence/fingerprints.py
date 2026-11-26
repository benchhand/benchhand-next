"""Dependency fingerprints: what each subject's evidence relied on, by domain, and what changed since a build.

A port of the prototype's impact.py (skills/cad-record/scripts/impact.py at release.toml reference_commit
412b5d9): DOMAINS and FAMILY_DOMAINS (lines 75-135), the per-subject values (`_Record`, lines 263-461),
`fingerprints` (463), `subject_fingerprints` (472), `changed_domains` (524), `stale_obligations` (535),
`unrecorded_domains` (556) and `evidence_staleness` (568). Values are read from the v3 documents as JSON, so
a digest is reproducible from the record; it is not byte-compatible with a prototype digest.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from benchhand_contracts.models.record.common_schema import Obligation

from benchhand_core.record.evidence.guidelines import digests_for
from benchhand_core.record.evidence.view import JsonMap, RecordView, items, mapping
from benchhand_core.record.rules.assembly import Inventory

DOMAINS = (
    "use_case",
    "load",
    "environment",
    "material",
    "condition",
    "lot",
    "process",
    "route",
    "capability",
    "setup",
    "orientation",
    "finish",
    "geometry",
    "interface",
    "occurrences",
    "criterion",
    "source",
    "appearance",
)
_EVERYTHING = frozenset(DOMAINS) - {"appearance", "occurrences"}
OPT_IN = frozenset(DOMAINS) - _EVERYTHING
_JUDGED = frozenset({"criterion", "source"})
_MAKING = frozenset(
    {"process", "route", "capability", "setup", "orientation", "finish", "material", "condition"}
)
_ENGINEERING = _JUDGED | {
    "use_case",
    "geometry",
    "material",
    "condition",
    "load",
    "environment",
    "orientation",
    "process",
    "route",
    "finish",
}
# The domains each check family depends on; the longest matching prefix decides (impact.py:101).
FAMILY_DOMAINS: tuple[tuple[str, frozenset[str]], ...] = (
    ("cad.", frozenset({"geometry"})),
    ("cad.glb_step_agreement", frozenset({"geometry", "occurrences"})),
    ("cad.declared_dimensions", frozenset({"occurrences"})),
    ("route.", _JUDGED | _MAKING),
    ("process.", _JUDGED | _MAKING | {"geometry"}),
    ("purchase.", _JUDGED | {"process", "route", "load", "environment", "geometry", "occurrences"}),
    ("optical.", _JUDGED | {"material", "process", "route", "finish"}),
    ("engineering.", _ENGINEERING),
    ("engineering.stop_reaction", _ENGINEERING | {"interface"}),
    ("feature.", _JUDGED | _MAKING | {"geometry", "interface"}),
    (
        "interface.",
        _JUDGED
        | {
            "geometry",
            "interface",
            "material",
            "condition",
            "process",
            "route",
            "capability",
            "finish",
            "load",
        }
        | {"environment"},
    ),
    (
        "contact.",
        _JUDGED | {"geometry", "interface", "material", "condition", "finish", "load", "environment"},
    ),
    ("motion.", _JUDGED | {"geometry", "interface", "material", "finish", "load", "process"}),
    ("assembly.", _JUDGED | {"geometry", "interface"}),
    (
        "function.",
        _JUDGED
        | {"geometry", "material", "condition", "load", "environment", "interface", "process", "finish"},
    ),
    ("export.3mf", frozenset({"geometry", "material", "appearance"})),
    ("requirement.", _EVERYTHING),
    ("policy.", _EVERYTHING),
)
# Obligations the record itself decides, recomputed on every read and never stale (impact.py:135).
RECORD_FAMILIES = ("intent.", "assembly.joint")
# A part that records no model_frame is modelled in assembly zero (assembly_data.py:33).
DEFAULT_FRAME = "assembly_zero"


def family_domains(family: str) -> frozenset[str]:
    """impact.py:138: an unlisted family depends on every domain but the opt-in ones."""
    best = max((prefix for prefix, _ in FAMILY_DOMAINS if family.startswith(prefix)), key=len, default=None)
    return dict(FAMILY_DOMAINS)[best] if best is not None else _EVERYTHING


def subject_key(subject: Mapping[str, Any]) -> str:
    """The fingerprinted subject: a PN, an IF, op:<id>, a REQ or product (impact.py:144)."""
    if subject.get("PN"):
        return str(subject["PN"])
    if subject.get("interface"):
        return str(subject["interface"])
    if subject.get("assembly_operation"):
        return f"op:{subject['assembly_operation']}"
    if subject.get("requirements"):
        return str(list(subject["requirements"])[0])
    return "product"


def digest(value: Any) -> str:
    """sha256 of `value` as canonical JSON: sorted keys, no whitespace (impact.py:172)."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _without(data: Any, *keys: str) -> Any:
    return {k: v for k, v in data.items() if k not in keys} if isinstance(data, Mapping) else data


def _get(data: Any, *path: str) -> Any:
    for key in path:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    return data


def artifacts_named(value: Any) -> dict[str, Any]:
    """Every `artifact` path a structure names, with the sha256 beside it (impact.py:192)."""
    found: dict[str, Any] = {}

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            if isinstance(item.get("artifact"), str):
                found.setdefault(item["artifact"], item.get("sha256"))
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return found


def record_artifacts(record: RecordView) -> dict[str, Any]:
    """Every source artifact (relative to hw/) the record names, with the first sha256 named: the record
    documents, the selection and the ledger entries' source and criterion source
    (manufacturing_intent.py:1340 `source`, 2230, 2253-2264)."""
    ledger = [
        [mapping(entry).get("source"), mapping(mapping(entry).get("criterion")).get("source")]
        for entry in record.evidence
    ]
    return artifacts_named(
        [
            record.product,
            record.requirements_document,
            list(record.interfaces.values()),
            record.assembly,
            list(record.parts.values()),
            list(record.materials.values()),
            list(record.capabilities.values()),
            record.selection,
            ledger,
        ]
    )


class _Values:
    """The values each domain of a subject depends on (impact.py:263 `_Record`)."""

    def __init__(self, record: RecordView, inventory: Inventory | None, geometry: Mapping[str, str | None]):
        self.record, self.inventory, self.geometry = record, inventory, geometry
        self.use_case = record.use_case or None
        self.operations = [op for op in items(record.operations) if isinstance(op, Mapping)]
        self.artifacts = record_artifacts(record)

    def intent(self, pn: str) -> JsonMap:
        return mapping((self.record.parts.get(pn) or {}).get("intent"))

    def route(self, pn: str) -> list[JsonMap]:
        return [op for op in items(self.intent(pn).get("route")) if isinstance(op, Mapping)]

    def profiles(self, pn: str) -> list[str]:
        intent = self.intent(pn)
        names = [intent.get("material_profile")]
        names += [mapping(c).get("material_profile") for c in items(intent.get("components"))]
        return [name for name in names if isinstance(name, str)]

    def _profile(self, table: Mapping[str, JsonMap], name: str) -> Any:
        return table[name] if name in table else {"missing": name}

    def part_values(self, pn: str) -> dict[str, Any]:
        part = self.record.parts.get(pn)
        if part is None:
            return {}
        values = self._making_values(pn, part)
        values.update(self._use_values(pn, part))
        sources = artifacts_named(
            [values["material"], values["capability"], part.get("procurement"), values["criterion"]]
        )
        values["source"] = {path: self.artifacts.get(path, sha) for path, sha in sorted(sources.items())}
        values["source"].update(self._guideline_sources(pn))
        mounting = self.mounting_inputs(pn)
        if mounting is not None:
            values["occurrences"] = mounting
        return values

    def _guideline_sources(self, pn: str) -> dict[str, str]:
        """`guideline:<id@revision>` -> sha256 of every guideline set a capability profile of the part's
        route resolves through for its own materials, or for every material when one is undecided
        (impact.py:343-351)."""
        intent = self.intent(pn)
        components = [mapping(c) for c in items(intent.get("components"))]
        declared = [intent.get("material_profile")]
        declared += [c.get("material_profile") for c in components if c.get("material_profile") is not None]
        undecided = any(
            not isinstance(m, str) and mapping(m).get("status") != "not_applicable" for m in declared
        )
        names = [] if undecided else self.profiles(pn)
        found: dict[str, str] = {}
        for op in self.route(pn):
            profile = op.get("capability")
            if isinstance(profile, str):
                chosen = digests_for(self.record.guideline_digests.get(profile), names)
                found.update({f"guideline:{ref}": sha for ref, sha in chosen.items()})
        return found

    def _making_values(self, pn: str, part: JsonMap) -> dict[str, Any]:
        intent, route = self.intent(pn), self.route(pn)
        materials = [self._profile(self.record.materials, name) for name in self.profiles(pn)]
        capabilities = [
            self._profile(self.record.capabilities, op["capability"])
            for op in route
            if isinstance(op.get("capability"), str)
        ]
        state_keys = ("id", "material_state_in", "material_state_out", "input_state", "output_state")
        return {
            "material": {
                "declared": part.get("material"),
                "profile": intent.get("material_profile"),
                "profiles": materials,
            },
            "condition": {
                "profiles": [mapping(m).get("process_state") for m in materials],
                "route": [{k: op.get(k) for k in state_keys} for op in route],
            },
            "process": {
                "process": part.get("process"),
                "make_buy": part.get("make_buy"),
                "procurement": _get(part, "procurement", "mode"),
                "kinds": [op.get("kind") for op in route],
                "route": None if route else intent.get("route"),
            },
            "route": [
                _without(op, "setup", "orientation", "supports", "post_processing", "allowances")
                for op in route
            ],
            "capability": {
                "profiles": capabilities,
                "facts": [op.get("capability") for op in route if isinstance(op.get("capability"), Mapping)],
            },
            "setup": [{"id": op.get("id"), "setup": op.get("setup")} for op in route],
            "orientation": [
                {"id": op.get("id"), "orientation": op.get("orientation"), "supports": op.get("supports")}
                for op in route
            ],
            "finish": {
                "finish": part.get("finish"),
                "operations": [
                    {
                        "id": op.get("id"),
                        "post_processing": op.get("post_processing"),
                        "allowances": op.get("allowances"),
                    }
                    for op in route
                ],
            },
        }

    def _use_values(self, pn: str, part: JsonMap) -> dict[str, Any]:
        intent = self.intent(pn)
        service = intent.get("service")
        wanted = service.get("loads") if isinstance(service, Mapping) else None
        loads = _get(self.use_case, "loads")
        if isinstance(loads, list) and wanted:
            loads = [load for load in loads if isinstance(load, Mapping) and load.get("id") in wanted]
        return {
            "use_case": _without(self.use_case, "status", "decision"),
            "load": {
                "loads": loads,
                "motion": _get(self.use_case, "motion"),
                "service": _without(service, "environment"),
            },
            "environment": {
                "product": _get(self.use_case, "environment"),
                "part": _get(service, "environment"),
            },
            "geometry": {
                "model": self.geometry.get(pn),
                "manufacture": part.get("manufacture"),
                "components": intent.get("components"),
                "critical_surfaces": intent.get("critical_surfaces"),
            },
            "appearance": {"color": intent.get("color")},
            "interface": {
                "interfaces": [self.record.interfaces[i] for i in sorted(self.interfaces_of(pn))],
                "operations": [op for op in self.operations if pn in (op.get("part"), op.get("into"))],
                "datums": _get(part, "drawing", "datum_features"),
            },
            "criterion": {
                "requirements": self.requirements_for(pn),
                "policy": _get(self.use_case, "evidence_policy"),
            },
        }

    def mounting_inputs(self, pn: str) -> Any:
        """The occurrences domain of a part (impact.py:357): a bought part's explicit occurrences, the
        operations naming them and its model_frame (impact.py:240-267); a made part, all of assembly.yaml with
        its model frame."""
        frame = (self.record.parts.get(pn) or {}).get("model_frame") or DEFAULT_FRAME
        if any(op.get("kind") == "purchased" for op in self.route(pn)):
            if self.inventory is None:
                return {"inventory": "unresolved", "model_frame": frame}
            mine = sorted(self.inventory.of(pn), key=lambda occurrence: occurrence.id)
            if not any(occurrence.explicit for occurrence in mine):
                return None
            explicit = {
                o.get("id"): o
                for o in items(self.record.assembly.get("occurrences"))
                if isinstance(o, Mapping)
            }
            occurrences = [
                {
                    "id": occurrence.id,
                    "ref": occurrence.ref,
                    "occurrence": explicit.get(occurrence.id),
                    "operations": sorted(
                        str(op.get("id"))
                        for op in self.operations
                        if occurrence.ref in (op.get("part"), op.get("into"))
                    ),
                }
                for occurrence in mine
            ]
            return {"model_frame": frame, "occurrences": occurrences}
        if not self.record.made(pn):
            return None
        return {
            "assembly": self.record.assembly,
            "model_frame": (self.record.parts.get(pn) or {}).get("model_frame"),
        }

    def heat_set_inputs(self, if_id: str) -> Any:
        """impact.py:376."""
        if not _get(self.record.interfaces.get(if_id), "limits", "heat_set"):
            return None
        return {
            "interfaces": [self.record.interfaces[i] for i in sorted(self.record.interfaces)],
            "assembly": self.record.assembly,
            "geometry": {pn: self.part_values(pn).get("geometry") for pn in sorted(self.record.parts)},
        }

    def interfaces_of(self, pn: str) -> set[str]:
        found = set()
        for if_id, interface in self.record.interfaces.items():
            members = {interface.get("from"), interface.get("to"), *items(interface.get("pair"))}
            members |= {mapping(s).get("PN") for s in items(_get(interface, "functional", "surfaces"))}
            if pn in members:
                found.add(if_id)
        return found

    def requirements_for(self, pn: str) -> list[Any]:
        """impact.py:397."""
        intent = self.intent(pn)
        ids: set[str] = set()
        for entry in items(intent.get("functions")) + items(intent.get("critical_surfaces")) + self.route(pn):
            ids.update(items(mapping(entry).get("requirements")))
        ids.update(items(_get(intent, "service", "requirements")))
        for req_id, requirement in self.record.requirements.items():
            if any(mapping(subject).get("PN") == pn for subject in items(requirement.get("subjects"))):
                ids.add(req_id)
        return [self.record.requirements[i] for i in sorted(ids) if i in self.record.requirements]

    def members(self, key: str) -> list[str]:
        """impact.py:413."""
        parts = self.record.parts
        if key in self.record.interfaces:
            interface = self.record.interfaces[key]
            ends = (interface.get("from"), interface.get("to"), *items(interface.get("pair")))
            return sorted({p for p in ends if isinstance(p, str) and p in parts})
        if key.startswith("op:"):
            op = next((o for o in self.operations if o.get("id") == key[3:]), {})
            return sorted({p for p in (op.get("part"), op.get("into")) if isinstance(p, str) and p in parts})
        if key in self.record.requirements:
            linked = sorted(pn for pn in parts if any(r.get("id") == key for r in self.requirements_for(pn)))
            return linked or sorted(parts)
        return sorted(parts)

    def values(self, key: str) -> dict[str, Any]:
        """impact.py:427."""
        if key in self.record.parts:
            return self.part_values(key)
        members = {pn: self.part_values(pn) for pn in self.members(key)}
        combined: dict[str, Any] = {d: {pn: v.get(d) for pn, v in members.items()} for d in DOMAINS}
        combined["use_case"] = _without(self.use_case, "status", "decision")
        combined.update(self._subject_view(key, combined))
        combined.pop("lot", None)
        for domain in OPT_IN:
            combined.pop(domain, None)
        heat_sets = self.heat_set_inputs(key) if key in self.record.interfaces else None
        if heat_sets is not None:
            combined["occurrences"] = heat_sets
        return combined

    def _subject_view(self, key: str, combined: Mapping[str, Any]) -> dict[str, Any]:
        policy = _get(self.use_case, "evidence_policy")
        requirements = self.record.requirements
        if key in self.record.interfaces:
            interface = self.record.interfaces[key]
            return {
                "interface": {
                    "interface": interface,
                    "operations": [o for o in self.operations if o.get("interface") == key],
                },
                "criterion": {
                    "acceptance": _get(interface, "functional", "acceptance"),
                    "requirements": [
                        requirements[r]
                        for r in items(_get(interface, "functional", "requirements"))
                        if r in requirements
                    ],
                    "policy": policy,
                },
            }
        if key.startswith("op:"):
            operation = next((o for o in self.operations if o.get("id") == key[3:]), None)
            return {"interface": {"operation": operation, "parts": combined["interface"]}}
        if key in requirements:
            return {"criterion": {"requirement": requirements[key], "policy": policy}}
        view = {"criterion": {"requirements": [r for _, r in sorted(requirements.items())], "policy": policy}}
        if key == "product":
            view["interface"] = {
                "parts": combined["interface"],
                "assembly_sequence": self.operations,
                "assembly_inventory": _without(self.record.assembly, "operations"),
            }
        return view


def fingerprints(
    record: RecordView,
    inventory: Inventory | None,
    subject: Mapping[str, Any],
    geometry: Mapping[str, str | None],
) -> dict[str, str]:
    """sha256 per dependency domain of `subject` (impact.py:463). `geometry` maps a PN to the sha256 of
    its model source; the lot is a property of physical evidence, never fingerprinted here."""
    values = _Values(record, inventory, geometry).values(subject_key(subject))
    return {domain: digest(values[domain]) for domain in DOMAINS if domain in values}


def subject_fingerprints(
    record: RecordView, inventory: Inventory | None, geometry: Mapping[str, str | None]
) -> dict[str, dict[str, str]]:
    """The fingerprints of every subject: product, parts, interfaces, operations and requirements
    (impact.py:472)."""
    view = _Values(record, inventory, geometry)
    keys = ["product", *sorted(record.parts), *sorted(record.interfaces)]
    keys += [f"op:{op['id']}" for op in view.operations if isinstance(op.get("id"), str)]
    keys += sorted(record.requirements)
    found = {}
    for key in keys:
        values = view.values(key)
        found[key] = {domain: digest(values[domain]) for domain in DOMAINS if domain in values}
    return found


def changed_domains(
    before: Mapping[str, Mapping[str, str]], after: Mapping[str, Mapping[str, str]]
) -> dict[str, tuple[str, ...]]:
    """Per subject key, the fingerprint domains that differ, appear or disappear (impact.py:524)."""
    changed = {}
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key, {}), after.get(key, {})
        domains = tuple(d for d in DOMAINS if old.get(d) != new.get(d))
        if domains:
            changed[key] = domains
    return changed


@dataclass(frozen=True)
class SubjectOf:
    """An obligation with its subject JSON, as the staleness rules read it."""

    obligation: Obligation
    subject: JsonMap


def stale_obligations(
    obligations: Iterable[SubjectOf], changed: Mapping[str, Iterable[str]]
) -> dict[str, tuple[str, ...]]:
    """The obligations whose subject changed in a domain their family depends on; record-derived
    obligations are recomputed, never stale (impact.py:535)."""
    stale = {}
    for item in obligations:
        family = item.obligation.family
        if family.startswith(RECORD_FAMILIES):
            continue
        hit = set(changed.get(subject_key(item.subject), ()))
        domains = tuple(d for d in DOMAINS if d in hit and d in family_domains(family))
        if domains:
            stale[item.obligation.id] = domains
    return stale


def declared_domains(entry: Mapping[str, Any]) -> frozenset[str]:
    """impact.py:549."""
    obligation = entry.get("obligation")
    return family_domains(obligation.split("@", 1)[0]) if isinstance(obligation, str) else frozenset()


def unrecorded_domains(entry: Mapping[str, Any], current: Mapping[str, str]) -> tuple[str, ...]:
    """The domains the entry's family declares and the subject has that it records no fingerprint of
    (impact.py:556)."""
    recorded, declared = mapping(entry.get("fingerprints")), declared_domains(entry)
    return tuple(d for d in DOMAINS if d in declared and d in current and d not in recorded)


def evidence_staleness(entry: Mapping[str, Any], current: Mapping[str, str]) -> tuple[str, ...]:
    """The domains in which accepted evidence no longer matches the current subject; ("unrecorded",) when it
    records none (impact.py:568)."""
    recorded = mapping(entry.get("fingerprints"))
    if not recorded:
        return ("unrecorded",)
    declared, missing = declared_domains(entry), unrecorded_domains(entry, current)
    return tuple(
        d
        for d in DOMAINS
        if d in missing
        or (d in recorded and recorded[d] != current.get(d) and (d not in OPT_IN or d in declared))
    )
