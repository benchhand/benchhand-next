# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The GLB and the STEP of one version describe different things."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _oracles import case  # noqa: E402
from corpus import Family, Pair  # noqa: E402

FAMILY = Family(
    id="semantic_step_glb_disagreement", check="cad_model.py check: GLB<->STEP geometry", owner="package D",
    pairs=(
        Pair("units_slip", "every GLB coordinate is 1000 times the STEP's, a millimetre read as a metre",
             case(fault={"kind": "scale", "factor": 1000.0})),
        Pair("hole_left_out_of_mesh", "the GLB shows the plate undrilled where the STEP has its 3 mm hole",
             case(fault={"kind": "stale", "variant": {"plate": {"drilled": False}}})),
        Pair("thinner_plate_in_mesh", "the GLB plate is 4 mm thick where the STEP's is 5 mm",
             case(fault={"kind": "stale", "variant": {"plate": {"thickness": 4.0}}})),
    ),
)
