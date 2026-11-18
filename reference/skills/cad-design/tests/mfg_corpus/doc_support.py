"""Shared helpers for the documentation-completeness families (doc_*): small records, edits and release verdicts.

The record is the lamp-arm example (realistic bushings, DIN 471 rings, a heat-set insert) or cad-record's
synthetic TST record (a printed part with a route, a CNC shaft, a catalog bearing). A verdict is what cad-record evidence
concludes for the obligations the release expects, never what one stage of the generators refuses: the guide generator, the
validator and the manufacturing plan publish no packet obligation. A defect no obligation carries is a known gap.

Heavy imports (yaml, jsonschema, OCP, the skill scripts) happen inside the functions.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from corpus import Outcome
from support import BUILD, MANIFEST_SHA256, REPO, SKILLS, load, purchase_verdict, require, state_verdict

RECORD = SKILLS / "cad-record"
LAMP_HW = REPO / "examples" / "lamp-arm" / "hw"
VERSION = "v1"


def fixtures() -> Any:
    """cad-record's synthetic-record fixtures (tests/fixtures/manufacturing_intent.py)."""
    need()
    return load("cad_record_mi_fixtures", RECORD / "tests" / "fixtures" / "manufacturing_intent.py")


def need() -> None:
    for module in ("yaml", "jsonschema"):
        require(module)


@contextmanager
def workspace() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="doc-corpus-") as name:
        yield Path(name)


def lamp(root: Path) -> Path:
    """A fresh copy of the lamp-arm example (record version 2) in `root`/hw."""
    need()
    return Path(shutil.copytree(LAMP_HW, root / "hw"))


def tst(root: Path) -> Path:
    """cad-record's synthetic TST record written below `root`/hw."""
    need()
    fx = fixtures()
    return Path(fx.write_record(root / "hw", fx.tst_record()))


def edit(hw: Path, name: str, change: Callable[[Any], None]) -> None:
    """Load the YAML document `hw`/`name`, let `change` mutate it in place, write it back."""
    import yaml

    path = hw / name
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def operation(data: dict[str, Any], op_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(op for op in data["operations"] if op["id"] == op_id)
    return found


def drop_operation(data: dict[str, Any], op_id: str) -> None:
    data["operations"] = [op for op in data["operations"] if op["id"] != op_id]


FASTENER_INTENT = {
    "functions": {"status": "unknown", "reason": "not recorded in this fixture", "question": "Q-012"},
    "material_profile": {"status": "not_applicable", "reason": "catalogue item"},
    "service": {"status": "unknown", "reason": "not recorded in this fixture", "question": "Q-012"},
    "critical_surfaces": {"status": "not_applicable", "reason": "catalogue item"},
    "route": {"status": "unknown", "reason": "not recorded in this fixture", "question": "Q-012"},
}


def add_fastener(hw: Path, pn: str, title: str, standard: str, qty: int, into: str = "LMP-0001") -> None:
    """Add a catalog fastener to the lamp record: its part.yaml, BOM row, `qty` placed occurrences in the base
    subassembly and drawing items, and one `fasten` operation per occurrence into `into`."""
    import csv

    import yaml

    material = "Steel 8.8 zinc plated"
    designation = f"{standard} - {title}"
    part = {"PN": pn, "rev": "X1", "title": title, "material": material, "process": "purchased", "finish": "Zinc plated",
            "mass_target": 8.0, "make_buy": "buy", "supplier": None, "decisions": ["DR-004"], "model_frame": "part_local",
            "intent": FASTENER_INTENT, "procurement": {"mode": "catalog", "standard": standard, "designation": designation}}
    (hw / "parts" / pn).mkdir()
    (hw / "parts" / pn / "part.yaml").write_text(yaml.safe_dump(part, sort_keys=False), encoding="utf-8")
    with (hw / "bom.csv").open(newline="", encoding="utf-8") as stream:
        columns = next(csv.reader(stream))
    row = {"level": "1", "PN": pn, "rev": "X1", "qty": str(qty), "title": title, "material": material, "process": "purchased",
           "make_buy": "buy", "mass": "8", "unit": "pcs", "designation": designation}
    with (hw / "bom.csv").open("a", newline="", encoding="utf-8") as stream:
        csv.writer(stream, lineterminator="\n").writerow([row.get(column, "") for column in columns])

    def place(assembly: dict[str, Any]) -> None:
        refs = []
        for number in range(qty):
            ident = f"{pn.lower()}-{number}"
            assembly.setdefault("occurrences", []).append({
                "id": ident, "PN": pn,
                "placement": {"translation_mm": [20 + 60 * number, 0, 0], "rotation": {"axis": [1, 0, 0], "angle_deg": 0}}})
            refs.append(f"@{ident}")
            assembly["operations"].append({
                "id": f"fasten_{ident}", "kind": "fasten", "part": f"@{ident}", "into": into, "direction": [0, 0, -1],
                "acceptance": {"kind": "seated", "features": ["head_underside", "mount_counterbores"]}})
        assembly["subassemblies"][0].setdefault("occurrences", []).extend(refs)
        item = max(entry["item"] for entry in assembly["drawing"]["items"]) + 1
        assembly["drawing"]["items"].append({"item": item, "PN": pn, "occurrences": refs})

    edit(hw, "assembly.yaml", place)


# --- route plans and purchased items, assessed by cad-design process_checks ---------------------------------------

POLYMER = "tst_polymer"
ALUMINIUM = "tst_alu"
APPROVED_ORIENTATION = {"status": "approved", "rotation": {"quaternion": [1, 0, 0, 0]}, "decision": "DR-001"}


def process_checks() -> Any:
    need()
    import sys

    scripts = str(SKILLS / "cad-design" / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import process_checks as module  # noqa: PLC0415

    return module


def made_part(pn: str, route: Any, process: str, material: Any) -> dict[str, Any]:
    fx = fixtures()
    intent = fx.intent(functions=[{"function": "cosmetic"}], material_profile=material, route=route,
                       critical_surfaces=fx.not_applicable("none here"))
    part: dict[str, Any] = fx.part(pn, process=process, part_intent=intent)
    return part


def fdm_part(*, orientation: bool = True, supports: bool = True, material: bool = True, route: bool = True) -> dict[str, Any]:
    """A printed part whose route states (or leaves out) its approved orientation and support plan, and its stock."""
    fx = fixtures()
    stock: Any = POLYMER if material else fx.unknown("stock not identified")
    if not route:
        return made_part("TST-0001", fx.unknown("route not recorded"), "fdm", stock)
    extra: dict[str, Any] = {}
    if orientation:
        extra["orientation"] = dict(APPROVED_ORIENTATION)
    if supports:
        extra["supports"] = {"strategy": "none"}
    return made_part("TST-0001", [fx.operation("print", "fdm", "tst_printer", output_state="printed", **extra)], "fdm", stock)


def cnc_part(*, setup: bool = True, workholding: bool = True) -> dict[str, Any]:
    """A milled part whose route states (or leaves out) its setup: stock, datums, tool access, workholding."""
    fx = fixtures()
    cutter = [fx.source("datasheet", "TST cutter")]
    plan: dict[str, Any] = {
        "stock": {"material_profile": ALUMINIUM, "grade": fx.known("TST 6061-T6"), "dimensions": fx.known("45 x 35 x 30")},
        "datums": ["datum_a"],
        "access": {"sides": ["+Z"], "tools": [{
            "description": "4 mm end mill", "diameter": fx.known(fx.quantity(4.0), "supplier_typical", cutter),
            "reach": fx.known(fx.quantity(25.0), "supplier_typical", cutter)}]}}
    if workholding:
        plan["workholding"] = {"method": fx.known("vice on the datum faces")}
    extra = {"setup": plan} if setup else {}
    return made_part("TST-0002", [fx.operation("mill", "cnc", "tst_mill", **extra)], "cnc", ALUMINIUM)


def judge(hw: Path, root: Path, prefixes: tuple[str, ...]) -> Outcome:
    """What a release concludes about the obligations starting with one of `prefixes` for the record in `hw`: cad-record
    evidence's assessment with the producer packets the record's version holds, none here. The `assembly.joint` obligations
    come from the declared joint facts of the record, as evidence assesses them itself."""
    need()
    evidence = load("cad_record_evidence", RECORD / "scripts" / "evidence.py")
    record, problems = evidence.mi.check_record(hw)
    errors = [problem.message for problem in problems if problem.severity == "error"]
    if errors:
        raise ValueError(f"the fixture record is invalid: {errors}")
    return state_verdict(record, [], BUILD, MANIFEST_SHA256, prefixes)


def lamp_verdict(change: Callable[[Path, bool], None], *prefixes: str) -> Callable[[bool], Outcome]:
    """A pair's `run` on the lamp record: `change(hw, mutant)` applies the defect, or the repair for the twin, and a release
    judges the obligations starting with `prefixes`."""

    def run(mutant: bool) -> Outcome:
        with workspace() as root:
            hw = lamp(root)
            change(hw, mutant)
            return judge(hw, root, prefixes)

    return run


def route_verdict(part: dict[str, Any], *prefixes: str) -> Outcome:
    """What a release concludes about the obligations starting with one of `prefixes` for a record holding `part` on the
    TST printer and mill profiles, with no geometry."""
    need()
    fx, checks = fixtures(), process_checks()
    profiles = [fx.material_profile(POLYMER, form="printed"), fx.material_profile(ALUMINIUM, form="wrought", family="TST aluminium")]
    capabilities = [fx.capability_profile("tst_printer", "fdm"),
                    fx.capability_profile("tst_mill", "cnc", parameters={"axes": fx.known(fx.quantity(3, units="count"))})]
    with workspace() as root:
        hw = fx.write_record(root / "project" / "hw", fx.record(parts=[part], capabilities=capabilities, materials=profiles))
        record, problems = checks.intent().check_record(hw)
    errors = [problem.message for problem in problems if problem.severity == "error"]
    if errors:
        raise ValueError(f"the fixture record is invalid: {errors}")
    return purchase_verdict(record, *prefixes)


def edit_bom(hw: Path, pn: str, change: Callable[[dict[str, str]], None]) -> None:
    """Rewrite the BOM row of `pn` through `change`."""
    import csv

    path = hw / "bom.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        columns, rows = list(reader.fieldnames or ()), list(reader)
    for row in rows:
        if row["PN"] == pn:
            change(row)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
