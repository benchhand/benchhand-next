# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["numpy==2.5.5"]
# ///

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Runs `agreement_timing.measure(3)` with a fake clock and a counting stand-in for `compare`, and prints one JSON line.

The clock ticks at 0, 1, 1, 3, 3 and 6 s, so the three runs last 1, 2 and 3 s. test_agreement_reference.py judges
the line. Usage: uv run --script agreement_timing_probe.py
"""

from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "scripts"))
import agreement_timing  # noqa: E402  (the import needs the sys.path entry above)

TICKS = itertools.chain([0.0, 1.0, 1.0, 3.0, 3.0, 6.0], itertools.repeat(float("nan")))  # a fourth run would read NaN
calls: list[int] = []


def counting_compare(glb: object, step: object, linear_mm: float) -> dict[str, str]:
    calls.append(1)
    return {"status": "pass"}


agreement_timing.GLB_GRID = agreement_timing.STEP_GRID = (8, 4)  # a small pair: only the loop is under test
with mock.patch.object(agreement_timing.agreement, "compare", counting_compare):
    result = agreement_timing.measure(3, clock=lambda: next(TICKS))
print(json.dumps({"result": result, "compare_calls": len(calls)}))
