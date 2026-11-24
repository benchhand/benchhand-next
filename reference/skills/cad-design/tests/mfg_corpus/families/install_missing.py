# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""install_missing: an assembly occurrence that no operation installs, other than its one base.

The verdict is what a release concludes about the assembly.order obligations of the packet access.py publishes, taken
through support.assembly_verdict. A part that lost its installing operation looks like a second base part, and the
sequence passes unless the product order obligation fails. The mutant drops one installing operation from the housing
assembly sequence. The twin keeps it.
"""

import copy
from typing import Any

from corpus import Family, Outcome, Pair
from support import assembly_verdict, reordered, socket_operations

VALID = ("seat-bearing", "fit-cover", "fasten-cover", "mount-bracket")  # the screw goes in before the bracket
ORDER = ("assembly.order@", "intent.assembly_operations@")


def _verdict(dropped: str | None) -> Outcome:
    items: list[dict[str, Any]] = [copy.deepcopy(op) for op in reordered(socket_operations("blocked_socket.yaml"), *VALID)
                                   if op["id"] != dropped]
    return assembly_verdict(items, *ORDER)


def _pair(pair_id: str, dropped: str, defect: str) -> Pair:
    def run(mutant: bool) -> Outcome:
        return _verdict(dropped if mutant else None)

    return Pair(pair_id, defect, run)


FAMILY = Family(
    id="install_missing",
    check="skills/cad-motion/scripts/access.py packet, assessed by cad-record evidence (assembly.order@product)",
    owner="pkgE",
    pairs=(
        _pair("bracket", "mount-bracket", "the bracket's installing join is missing and nothing else names it"),
        _pair("screw", "fasten-cover", "the cover screw's installing fasten is missing and nothing else names it"),
        _pair("cover", "fit-cover", "the cover's installing close is missing and the screw still fastens into it"),
        _pair("bearing", "seat-bearing", "the bearing's installing press fit is missing and the cover still closes over it"),
    ),
)
