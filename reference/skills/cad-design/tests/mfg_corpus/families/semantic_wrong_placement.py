# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A part of the right shape at the wrong place or turn in the assembly mesh."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _oracles import case  # noqa: E402
from corpus import Family, Pair  # noqa: E402

FAMILY = Family(
    id="semantic_wrong_placement", check="cad_model.py check: GLB<->STEP placement", owner="package D",
    pairs=(
        Pair("plate_node_moved_5_mm", "the plate's GLB node is 5 mm from its STEP placement",
             case(fault={"kind": "offset", "occurrence": "TST-0002", "metres": [0.005, 0.0, 0.0]})),
        Pair("plate_node_turned_90_degrees", "the plate's GLB node is turned a quarter turn about the vertical axis",
             case(fault={"kind": "rotate", "occurrence": "TST-0002", "degrees": 90.0})),
        Pair("insert_node_moved_2_mm", "the insert's GLB node is 2 mm from its STEP placement",
             case(fault={"kind": "offset", "occurrence": "TST-0003", "metres": [0.0, 0.0, 0.002]})),
    ),
)
