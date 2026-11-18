# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Build documentation: a heat-set insert with no install method or tool.

The lamp's three heat-set operations carry no tool and no consumable, and the guide's tool table lists none for them.
The twin names the iron, its tip temperature and the pressing depth the datasheet gives. The release holds one obligation
for each heat-set operation, `assembly.joint@op:<id>`, and it judges retention, edge distance and host temperature only.
The lamp records none of those facts with a source, so both variants stay unknown. See GAP.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from corpus import Family, Outcome, Pair
from doc_support import edit, lamp_verdict

JOINT = "assembly.joint@op:heat_set"
GAP = "#132: no release obligation carries the heat-set install method. The joint obligation stays unknown on unsourced retention."

IRON = "Soldering iron with M10 insert tip, 230 °C"


def tool(named: str, mutant_name: str) -> Callable[[bool], Outcome]:
    """Every heat-set operation names `mutant_name` as its tool in the mutant and `named` in the twin ('' names none)."""

    def change(hw: Path, mutant: bool) -> None:
        def apply(assembly: dict[str, Any]) -> None:
            for op in assembly["operations"]:
                if op["kind"] != "heat_set":
                    continue
                chosen = mutant_name if mutant else named
                if chosen:
                    op["tools"] = [chosen]
                else:
                    op.pop("tools", None)

        edit(hw, "assembly.yaml", apply)

    return lamp_verdict(change, JOINT)


def depth(hw: Path, mutant: bool) -> None:
    def apply(interfaces: dict[str, Any]) -> None:
        for item in interfaces["interfaces"]:
            for entry in item.get("limits", {}).get("heat_set", ()):
                if mutant:
                    entry.pop("depth_min", None)

    edit(hw, "interfaces.yaml", apply)


FAMILY = Family(
    id="doc_heatset_insert", check="cad-record evidence: assembly.joint obligations of the heat-set operations", owner="cad-record",
    pairs=(
        Pair("iron_missing", "no heat-set operation names an iron or tool", tool(IRON, ""), known_gap=GAP),
        Pair("iron_temperature", "the iron is named without its tip temperature", tool(IRON, "Soldering iron"), known_gap=GAP),
        Pair("pressing_depth", "the datasheet pressing depth is missing from the heat-set interface", lamp_verdict(depth, JOINT), known_gap=GAP),
    ))
