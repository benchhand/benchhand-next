# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""The AgentCAD-derived Booleans live in occ_derived (Apache-2.0) and stay reachable through occ.

Fault injection patches `occ.boolean`, so callers must keep resolving it on occ at call time.
Needs no OCP: the patched occ stands in for the kernel.

Run: python3 -m unittest discover -s skills/cad-model/tests -p test_occ_derived.py -v
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
from cadmodel import occ, occ_derived, safe  # noqa: E402

DERIVED = ("boolean", "occupied", "volume_slack")


class OccDerivedTests(unittest.TestCase):
    def test_occ_re_exports_the_derived_functions_unchanged(self) -> None:
        for name in DERIVED:
            with self.subTest(name=name):
                self.assertIs(getattr(occ, name), getattr(occ_derived, name))

    def test_occ_derived_imports_first_in_a_fresh_interpreter(self) -> None:
        proc = subprocess.run([sys.executable, "-c", "import cadmodel.occ_derived, cadmodel.occ"],
                              cwd=SCRIPTS, capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])

    def test_volume_slack_is_relative_with_an_absolute_floor(self) -> None:
        self.assertEqual(occ.volume_slack(), 1e-6)
        self.assertEqual(occ.volume_slack(1e3, -2e9), 2e9 * 1e-7)

    def test_patching_occ_boolean_reaches_safe_edits(self) -> None:
        shape = mock.Mock(**{"IsNull.return_value": False})
        with mock.patch.multiple(occ, to_topods=lambda value: shape, is_valid=lambda s: True,
                                 count=lambda s, kind: 1, occupied=lambda s, fuzzy=0.0: (s, 10.0),
                                 boolean=mock.Mock(side_effect=occ.GeometryError("injected fault"))):
            with self.assertRaisesRegex(safe.SafeEditError, "injected fault"):
                safe.safe_cut(object(), object())


if __name__ == "__main__":
    unittest.main()
