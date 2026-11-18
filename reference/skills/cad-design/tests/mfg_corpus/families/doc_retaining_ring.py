"""Build documentation: a retaining ring (DIN 471) with no pliers step, and a ring with no groove.

A worker fits the lamp's three rings with external circlip pliers, named on each operation and listed in the guide's tool
table. The mutant drops the pliers. The two groove pairs remove the groove from the interface that joins ring and pin
and from the pin's own drawing. The release holds `assembly.joint@op:<id>` for each ring operation, and it reads neither
the tool nor the groove. Both variants stay unknown. See GAP.
"""

from pathlib import Path
from typing import Any

from corpus import Family, Pair
from doc_support import edit, lamp_verdict

JOINT = "assembly.joint@op:ring_"
GAP = "#133: no release obligation carries the ring tool or the groove. The joint obligation stays unknown on unsourced retention."


def pliers(hw: Path, mutant: bool) -> None:
    def apply(assembly: dict[str, Any]) -> None:
        for op in assembly["operations"]:
            if mutant and op["kind"] == "retaining_ring":
                op.pop("tools", None)

    edit(hw, "assembly.yaml", apply)


def interface_groove(hw: Path, mutant: bool) -> None:
    def apply(interfaces: dict[str, Any]) -> None:
        for item in interfaces["interfaces"]:
            if mutant and item["id"] == "IF-001":
                item["limits"].pop("retaining_ring")

    edit(hw, "interfaces.yaml", apply)


def part_groove(hw: Path, mutant: bool) -> None:
    def apply(part: dict[str, Any]) -> None:
        if not mutant:
            return
        drawing = part["drawing"]
        drawing["features"].pop("groove")
        drawing["dimensions"] = [item for item in drawing["dimensions"] if "groove" not in item["features"]]
        drawing["views"] = [item for item in drawing["views"] if item.get("feature") != "groove"]
        drawing["notes"] = [item for item in drawing["notes"] if item.get("reference") != "groove"]

    edit(hw, "parts/LMP-0005/part.yaml", apply)


FAMILY = Family(
    id="doc_retaining_ring", check="cad-record evidence: assembly.joint obligations of the ring operations", owner="cad-record",
    pairs=(
        Pair("no_pliers", "the ring operations name no circlip pliers", lamp_verdict(pliers, JOINT), known_gap=GAP),
        Pair("no_groove_interface", "the pin-ring interface IF-001 records no ring and groove", lamp_verdict(interface_groove, JOINT), known_gap=GAP),
        Pair("no_groove_part", "the pin LMP-0005 has no groove feature for its ring", lamp_verdict(part_groove, JOINT), known_gap=GAP),
    ))
