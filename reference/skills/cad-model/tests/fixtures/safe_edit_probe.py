# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

# /// script
# requires-python = ">=3.12,<3.15"
# dependencies = ["cadquery-ocp-novtk==8.0.1.1.0"]
# ///
"""Run the safe edits and the occ Booleans on raw OCP boxes (OCP 8.0, no CadQuery or build123d loaded).

Usage: uv run --script safe_edit_probe.py
stdout: {"edits": {case: result}, "occ": {case: result}, "diff": {case: row}}; the cases are in safe_cases_lib.py.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import safe_cases_lib  # noqa: E402

print(json.dumps({"edits": safe_cases_lib.edit_report(), "occ": safe_cases_lib.occ_report(), "diff": safe_cases_lib.diff_report()}))
