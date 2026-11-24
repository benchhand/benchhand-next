# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A mesh fault on a part that the version changed, caught by a `--changed-only` check against the version before."""

from corpus import Family, Pair
from support import oracle_case

# v2 moves the plate's hole from X 25 to X 31 (the change under test). v1 is the clean default project.
MOVED_HOLE = {"plate": {"hole_x": 31.0}}
# The plate is the part the version changed, so the changed-only check judges its agreement. It leaves the unchanged
# base and insert out, and their agreement reads unknown until a full check runs.
CHANGED_PLATE = ("cad.glb_step_agreement@TST-0002",)

FAMILY = Family(
    id="semantic_changed_only_scope", check="cad_model.py check --changed-only: cad.glb_step_agreement of the changed part",
    owner="package D",
    pairs=(
        Pair("changed_plate_mesh_is_the_old_one", "the exporter drew v2's plate with v1's hole position",
             oracle_case(MOVED_HOLE, {"kind": "stale", "variant": {"plate": {"hole_x": 25.0}}}, prefixes=CHANGED_PLATE,
                         changed_only=True)),
        Pair("changed_plate_node_moved_5_mm", "v2's plate node sits 5 mm from its STEP placement",
             oracle_case(MOVED_HOLE, {"kind": "offset", "occurrence": "TST-0002", "metres": [0.005, 0.0, 0.0]},
                         prefixes=CHANGED_PLATE, changed_only=True)),
    ),
    notes="A fault on a part the version left unchanged is outside a changed-only check by design; the full check covers it.",
)
