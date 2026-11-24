# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["build123d==0.13.0", "cadquery-ocp-novtk==8.0.1.1.0", "bd_warehouse==0.4.0"]
# ///
"""Run the safe edits and the occ Booleans in the build123d environment (OCP 8.0) and report the wrapper kind
each template gets back.

Usage: uv run --script safe_edit_build123d_probe.py
stdout: {"edits", "occ"} as safe_edit_probe.py, and "wrap": {case: {"type", "volume"}}.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from build123d import Align, Box, BuildPart, Compound, Pos, Solid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import safe_cases_lib as lib  # noqa: E402
from cadmodel import occ  # noqa: E402
from cadmodel.safe import safe_cut, safe_fuse, safe_intersect  # noqa: E402

LOW = (Align.MIN, Align.MIN, Align.MIN)


def case(call):
    try:
        value = call()
        return {"type": type(value).__name__, "volume": occ.volume(occ.to_topods(value))}
    except Exception as error:  # noqa: BLE001
        return {"error": str(error), "type": type(error).__name__}


part_a, part_b = Box(10, 10, 10, align=LOW), Pos(5, 0, 0) * Box(10, 10, 10, align=LOW)
solid_a, solid_b = Solid(part_a.wrapped), Solid(part_b.wrapped)
with BuildPart() as builder:
    Box(10, 10, 10, align=LOW)
wrap = {
    "part_cut": case(lambda: safe_cut(part_a, part_b)),
    "part_fuse": case(lambda: safe_fuse(part_a, part_b)),
    "part_intersect": case(lambda: safe_intersect(part_a, part_b)),
    "solid_cut": case(lambda: safe_cut(solid_a, solid_b)),
    "solid_fuse": case(lambda: safe_fuse(solid_a, solid_b)),
    "solid_intersect": case(lambda: safe_intersect(solid_a, solid_b)),
    "builder_cut": case(lambda: safe_cut(builder, part_b)),
    "part_with_solid_tool": case(lambda: safe_cut(part_a, solid_b)),
    "solid_with_part_tool": case(lambda: safe_cut(solid_a, part_b)),
    "raw_first_with_part_tool": case(lambda: safe_cut(lib.A, part_b)),
    "compound_cut": case(lambda: safe_cut(Compound([solid_a]), solid_b)),
    "unknown_wrapper": case(lambda: safe_cut(SimpleNamespace(wrapped=lib.A), lib.B)),
}
print(json.dumps({"edits": lib.edit_report(), "occ": lib.occ_report(), "diff": lib.diff_report(), "wrap": wrap}))
