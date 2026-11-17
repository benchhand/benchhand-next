"""Assembly operation order and closure over the access fixture's five parts, as a release sees it: the assembly.order
and intent.assembly_operations obligations of the packet access.py publishes, assessed by cad-record evidence.

Mutants reuse cad-motion's operation files. Each twin holds the same operations in a valid order.
"""

import copy
from typing import Any

from corpus import Family, Outcome, Pair
from support import assembly_verdict, reordered, socket_operations

VALID = ("seat-bearing", "fit-cover", "fasten-cover", "mount-bracket")
ORDER = ("assembly.order@", "intent.assembly_operations@")


def _verdict(items: list[dict[str, Any]]) -> Outcome:
    return assembly_verdict(items, *ORDER)


def _valid() -> list[dict[str, Any]]:
    return reordered(socket_operations("blocked_socket.yaml"), *VALID)


def closed_before_install(mutant: bool) -> Outcome:
    items = socket_operations("closed_bearing_install.yaml")  # the cover closes the bearing's seat, then the bearing goes in
    return _verdict(items if mutant else reordered(items, "seat-bearing", "fit-cover"))


def receiving_part_installed_later(mutant: bool) -> Outcome:
    items = socket_operations("blocked_socket.yaml")
    order = ("seat-bearing", "fasten-cover", "fit-cover", "mount-bracket") if mutant else VALID
    return _verdict(reordered(items, *order))


def predecessor_after(mutant: bool) -> Outcome:
    items = _valid()
    if mutant:
        items[0]["predecessors"] = ["fit-cover"]  # seat-bearing must follow the cover, which comes after it
    return _verdict(items)


def enclosed_part_removed(mutant: bool) -> Outcome:
    items = socket_operations("blocked_socket.yaml")[:2]
    pull = {"id": "pull-bearing", "kind": "disassemble", "part": "TST-0102", "into": "TST-0101", "direction": [0, 0, 1]}
    items = items + [pull] if mutant else [items[0], pull]  # the twin leaves the cover off the bearing
    return _verdict(items)


def part_never_installed(mutant: bool) -> Outcome:
    items = _valid()
    if mutant:
        items = [i for i in items if i["id"] != "mount-bracket"]  # the bracket is in the bill but no operation installs it
    return _verdict(items)


def part_installed_twice(mutant: bool) -> Outcome:
    items = _valid()
    if mutant:
        again = copy.deepcopy(items[0])
        again["id"] = "seat-bearing-again"
        items.insert(1, again)
    return _verdict(items)


FAMILY = Family(
    id="assembly_operations_order", check="cad-motion/scripts/access.py packet, assembly.order (check_order)", owner="cad-record",
    pairs=(
        Pair("closed_before_install", "bearing pressed in after the cover closed its seat", closed_before_install),
        Pair("receiving_part_later", "screw fastened into a cover not yet fitted", receiving_part_installed_later),
        Pair("predecessor_after", "declared predecessor comes after the operation", predecessor_after),
        Pair("enclosed_part_removed", "bearing pulled after the cover encloses it", enclosed_part_removed),
        Pair("part_never_installed", "a bill part no operation installs", part_never_installed),
        Pair("part_installed_twice", "the same part installed twice", part_installed_twice),
    ))
