"""cad-motion access.py: the geometric part-path and tool-reach check on the access fixture's built geometry.

Judged on the assembly.access obligations only (order is the assembly_operations_order family). Mutants and twins
reuse cad-motion's operation files. Each twin holds the same operations in an order or tool description that works.
"""

from typing import Any

from corpus import Family, Outcome, Pair
from support import access_outcomes, reordered, socket_operations, verdict

ACCESS = "assembly.access@"
VALID = ("seat-bearing", "fit-cover", "fasten-cover", "mount-bracket")  # screw driven before the bracket goes on


def _verdict(items: list[dict[str, Any]]) -> Outcome:
    return verdict(v for k, v in access_outcomes(items).items() if k.startswith(ACCESS))


def socket_blocked_by_bracket(mutant: bool) -> Outcome:
    items = socket_operations("blocked_socket.yaml")  # bracket mounted first: the socket cannot reach the screw
    return _verdict(items if mutant else reordered(items, *VALID))


def bearing_path_closed_by_cover(mutant: bool) -> Outcome:
    items = socket_operations("blocked_socket.yaml")  # the full set, so the screw and bracket are not in place from the start
    order = ("fit-cover", "seat-bearing", "fasten-cover", "mount-bracket") if mutant else VALID  # cover before the bearing
    return _verdict(reordered(items, *order))


def tool_named_only(mutant: bool) -> Outcome:
    items = reordered(socket_operations("blocked_socket.yaml"), *VALID)
    if mutant:
        del items[2]["tool_access"]
        items[2]["tools"] = ["3 mm hex key"]  # a name carries no reach or envelope
    return _verdict(items)


FAMILY = Family(
    id="access_assembly", check="cad-motion/scripts/access.py", owner="cad-motion",
    pairs=(
        Pair("socket_blocked", "bracket mounted before the screw is driven: the socket collides", socket_blocked_by_bracket),
        Pair("bearing_path_closed", "cover fitted over the seat before the bearing goes in", bearing_path_closed_by_cover),
        Pair("tool_named_only", "tool known by name only: reach is not computable", tool_named_only),
    ))
