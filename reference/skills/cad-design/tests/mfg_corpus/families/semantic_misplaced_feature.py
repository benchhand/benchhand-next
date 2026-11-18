# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A feature in the wrong place on a part: the same hole, the same volume, 6 to 8 mm away."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _oracles import case  # noqa: E402
from corpus import Family, Pair  # noqa: E402

FAMILY = Family(
    id="semantic_misplaced_feature", check="cad_model.py check: GLB<->STEP agreement", owner="package D",
    pairs=(
        Pair("base_bore_moved_in_mesh", "the GLB has the base bore 8 mm along X from where the STEP has it",
             case(fault={"kind": "stale", "variant": {"base": {"bore_x": 8.0}, "insert": {"x": 8.0}}})),
        Pair("plate_hole_moved_in_mesh", "the GLB has the plate's 3 mm hole 6 mm from where the STEP has it",
             case(fault={"kind": "stale", "variant": {"plate": {"hole_x": 31.0}}})),
    ),
    notes="Each mesh is that of the project built with the old model: an exporter run on stale input.",
)
