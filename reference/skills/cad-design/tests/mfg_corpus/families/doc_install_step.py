"""Build documentation: an assembly operation with no installation step.

Measured on the access fixture's five parts, as `assembly_operations_order` is, because the release obligations of the
order check (`assembly.order@op:<id>`) come from the packet access.py publishes, which needs the built geometry. The
lamp lacks it. A pair drops the one operation that installs a part: a pressed bearing, a screw that fastens the cover, a
joined bracket. Before #52 the release held an `assembly.order` obligation for each operation that is present and none for
the one that is gone, so all three mutants passed (#131). Since #52 an occurrence that no operation installs or names fails,
so all three fail. The pairs overlap `assembly_operations_order/part_never_installed`.
"""

from collections.abc import Callable
from typing import Any

from corpus import Family, Outcome, Pair
from support import assembly_verdict, reordered, socket_operations

VALID = ("seat-bearing", "fit-cover", "fasten-cover", "mount-bracket")
ORDER = ("assembly.order@", "intent.assembly_operations@")


def dropping(op_id: str) -> Callable[[bool], Outcome]:
    def run(mutant: bool) -> Outcome:
        items: list[dict[str, Any]] = reordered(socket_operations("blocked_socket.yaml"), *VALID)
        if mutant:
            items = [item for item in items if item["id"] != op_id]
        return assembly_verdict(items, *ORDER)

    return run


FAMILY = Family(
    id="doc_install_step", check="cad-record evidence: assembly.order obligations of the access.py packet", owner="cad-record",
    pairs=(
        Pair("pressed_bearing", "no operation presses the bearing into the housing", dropping("seat-bearing")),
        Pair("cover_screw", "no operation fastens the cover screw", dropping("fasten-cover")),
        Pair("joined_bracket", "no operation joins the bracket", dropping("mount-bracket")),
    ))
