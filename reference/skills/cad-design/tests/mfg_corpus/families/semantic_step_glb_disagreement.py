# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The GLB and the STEP of one version describe different things."""

from corpus import Family, Pair
from support import AGREEMENT, oracle_case

FAMILY = Family(
    id="semantic_step_glb_disagreement", check="cad_model.py check: cad.glb_step_agreement (geometry)", owner="package D",
    pairs=(
        Pair("units_slip", "every GLB coordinate is 1000 times the STEP's, a millimetre read as a metre",
             oracle_case(fault={"kind": "scale", "factor": 1000.0}, prefixes=AGREEMENT)),
        Pair("hole_left_out_of_mesh", "the GLB shows the plate undrilled where the STEP has its 3 mm hole",
             oracle_case(fault={"kind": "stale", "variant": {"plate": {"drilled": False}}}, prefixes=AGREEMENT)),
        Pair("thinner_plate_in_mesh", "the GLB plate is 4 mm thick where the STEP's is 5 mm",
             oracle_case(fault={"kind": "stale", "variant": {"plate": {"thickness": 4.0}}}, prefixes=AGREEMENT)),
    ),
)
