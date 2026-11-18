# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A shape swapped for another of the same volume, so no volume read-back can tell them apart."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _oracles import case  # noqa: E402
from corpus import Family, Pair  # noqa: E402

# The base block is 40 x 40 x 20 with a 7.77 mm bore. Its twin in the mesh is a cylinder of the same plan
# area, height and bore: the same volume to the last digit.
ROUND = {"base": {"shape": "round"}}
# A bore of 8.6 mm for a heat-set insert declared in a 7.77 mm hole. The block is 20.1384 mm tall. That height
# restores the volume, 31051.6 mm^3, that the wider bore removed. The insert grows with the bore (8.82 mm), so
# contact, interference and connection stay as the clean twin has them. The plate rides up with the top face.
WIDE_BORE = {"base": {"bore": 8.6, "height": 20.1384}, "insert": {"diameter": 8.82}, "plate": {"z0": 20.1384}}

FAMILY = Family(
    id="semantic_equal_volume_substitution", check="cad_model.py check: GLB<->STEP agreement, declared dimensions",
    owner="package D",
    pairs=(
        Pair("mesh_is_an_equal_volume_cylinder", "the GLB shows the base as a round block of the STEP block's volume",
             case(fault={"kind": "stale", "variant": ROUND})),
        Pair("bore_diameter_traded_for_height", "the base bore is 8.6 mm where the heat-set declaration says 7.77, "
             "and the height absorbs the volume", case(model=WIDE_BORE)),
    ),
    notes="The second pair is a model error that the record's own dimension exposes; the first is an output error.",
)
