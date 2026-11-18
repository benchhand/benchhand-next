"""Build documentation: an instruction order that contradicts the assembly order.

The guide numbers its steps in the order of the operations, so an operations list that fastens the cover screw before the
cover has its fit, or that declares a predecessor which comes later, prints instructions nobody can follow. Measured on the
access fixture's five parts, as `assembly_operations_order` is: the release obligation is `assembly.order@op:<id>` of the
packet access.py publishes. The two pairs overlap `assembly_operations_order/receiving_part_later` and `predecessor_after`.
"""

from collections.abc import Callable
from typing import Any

from corpus import Family, Outcome, Pair
from support import assembly_verdict, reordered, socket_operations

VALID = ("seat-bearing", "fit-cover", "fasten-cover", "mount-bracket")
ORDER = ("assembly.order@", "intent.assembly_operations@")


def ordered(change: Callable[[list[dict[str, Any]], bool], list[dict[str, Any]]]) -> Callable[[bool], Outcome]:
    def run(mutant: bool) -> Outcome:
        items = reordered(socket_operations("blocked_socket.yaml"), *VALID)
        return assembly_verdict(change(items, mutant), *ORDER)

    return run


def screw_before_cover(items: list[dict[str, Any]], mutant: bool) -> list[dict[str, Any]]:
    if not mutant:
        return items
    return reordered(items, "seat-bearing", "fasten-cover", "fit-cover", "mount-bracket")


def predecessor_after(items: list[dict[str, Any]], mutant: bool) -> list[dict[str, Any]]:
    if mutant:
        items[0]["predecessors"] = ["fit-cover"]  # seat-bearing must follow the cover, which comes after it
    return items


FAMILY = Family(
    id="doc_instruction_order", check="cad-record evidence: assembly.order obligations of the access.py packet", owner="cad-record",
    pairs=(
        Pair("screw_before_cover", "the cover screw is fastened before the cover is fitted", ordered(screw_before_cover)),
        Pair("predecessor_after", "the bearing names the cover, which comes after it, as its predecessor", ordered(predecessor_after)),
    ))
