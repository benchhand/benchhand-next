"""Build documentation: a made part with no manufacturing instructions.

The route of a made part is what a guide would print as manufacturing instructions: for FDM the approved orientation,
supports and stock, for CNC the setup (stock, datums, tool access, workholding). The release holds `route.consistency@<PN>`
and `route.operation_plan@<PN>/<op>` from cad-design's packet, and both need no geometry. A missing stock or
route leaves `route.consistency` unknown. A missing orientation, support plan, setup or workholding fails
`route.operation_plan` and names the field. A field recorded as open stays unknown.
"""

from collections.abc import Callable
from typing import Any

from corpus import Family, Outcome, Pair
from doc_support import cnc_part, fdm_part, route_verdict


def without(build: Callable[..., dict[str, Any]], what: str, *prefixes: str) -> Callable[[bool], Outcome]:
    """The mutant builds the part with `what` left out of its route. The twin states it."""

    def run(mutant: bool) -> Outcome:
        return route_verdict(build(**{what: not mutant}), *prefixes)

    return run


ROUTE = ("route.consistency@", "route.operation_plan@")

FAMILY = Family(
    id="doc_manufacturing", check="cad-design process_checks packet: route.consistency and route.operation_plan", owner="cad-model",
    pairs=(
        Pair("fdm_orientation", "the printed part has no approved build orientation", without(fdm_part, "orientation", *ROUTE)),
        Pair("fdm_supports", "the printed part has no support plan", without(fdm_part, "supports", *ROUTE)),
        Pair("fdm_stock", "the printed part names no material profile", without(fdm_part, "material", *ROUTE)),
        Pair("fdm_route", "the printed part has no route at all", without(fdm_part, "route", *ROUTE)),
        Pair("cnc_setup", "the milled part has no setup", without(cnc_part, "setup", *ROUTE)),
        Pair("cnc_workholding", "the milled part's setup has no workholding", without(cnc_part, "workholding", *ROUTE)),
    ))
