# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A feature in the wrong place on a part: the same hole, the same volume, 6 to 8 mm away."""

from corpus import Family, Pair
from support import AGREEMENT, oracle_case

FAMILY = Family(
    id="semantic_misplaced_feature", check="cad_model.py check: cad.glb_step_agreement", owner="package D",
    pairs=(
        Pair("base_bore_moved_in_mesh", "the GLB has the base bore 8 mm along X from where the STEP has it",
             oracle_case(fault={"kind": "stale", "variant": {"base": {"bore_x": 8.0}, "insert": {"x": 8.0}}},
                         prefixes=AGREEMENT)),
        Pair("plate_hole_moved_in_mesh", "the GLB has the plate's 3 mm hole 6 mm from where the STEP has it",
             oracle_case(fault={"kind": "stale", "variant": {"plate": {"hole_x": 31.0}}}, prefixes=AGREEMENT)),
    ),
    notes="Each mesh is that of the project built with the old model: an exporter run on stale input.",
)
