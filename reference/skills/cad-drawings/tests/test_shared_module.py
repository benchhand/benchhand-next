#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""A drawing worker thread that needs cad-fits finds it fully loaded once, never loaded twice or half built.

Run: uv run --no-project --with-requirements harness/test-requirements.txt python -B -m unittest discover -s skills/cad-drawings/tests -p test_shared_module.py
"""

from __future__ import annotations

import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import drawing_intent  # noqa: E402
import shared_module  # noqa: E402

# A module body that counts its runs, stalls until the second thread is about to load it, then until
# that thread's call returns. A correct loader keeps the second thread waiting (the last wait times out
# on purpose) and runs the body once; a broken one runs the body a second time in the second thread.
SLOW_FITS = """
import sys
probe = sys._fits_probe
probe["runs"].append(1)
probe["started"].set()
assert probe["second_ready"].wait(10), "the second thread never reached the loader"
probe["second_returned"].wait(1)  # bounds the red case only: a thread blocked on the lock cannot signal, so the green case never depends on it
READY = True
"""


class FitsLoadThreadTests(unittest.TestCase):
    def test_two_threads_share_one_fully_executed_fits_module(self) -> None:
        probe = {"runs": [], **{name: threading.Event() for name in ("started", "second_ready", "second_returned")}}
        sys._fits_probe = probe  # type: ignore[attr-defined]
        self.addCleanup(lambda: delattr(sys, "_fits_probe"))
        self.addCleanup(sys.modules.pop, "cad_fits_fits", None)
        sys.modules.pop("cad_fits_fits", None)
        drawing_intent._fits.cache_clear()
        self.addCleanup(drawing_intent._fits.cache_clear)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fits.py"
            path.write_text(SLOW_FITS, encoding="utf-8")

            def second() -> object:
                assert probe["started"].wait(10), "the first thread never started loading"
                probe["second_ready"].set()
                module = drawing_intent._fits()
                probe["second_returned"].set()
                return module

            with mock.patch.object(drawing_intent, "FITS", path), ThreadPoolExecutor(2) as pool:
                first = pool.submit(drawing_intent._fits)
                later = pool.submit(second)
                modules = (first.result(30), later.result(30))
        self.assertEqual(len(probe["runs"]), 1, "the module body ran once")
        self.assertIs(modules[0], modules[1])
        self.assertTrue(getattr(modules[1], "READY", False), "the second thread got the finished module")


FAILS_ONCE = """
import sys
probe = sys._fits_probe
probe["runs"].append(1)
if len(probe["runs"]) == 1:
    PARTIAL = True
    raise RuntimeError("first load fails")
READY = True
"""


class FailedLoadTests(unittest.TestCase):
    def test_retry_after_a_failed_load_runs_the_body_again(self) -> None:
        name = "cad_shared_module_fails_once"
        probe: dict[str, list[int]] = {"runs": []}
        sys._fits_probe = probe  # type: ignore[attr-defined]
        self.addCleanup(lambda: delattr(sys, "_fits_probe"))
        self.addCleanup(sys.modules.pop, name, None)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fails_once.py"
            path.write_text(FAILS_ONCE, encoding="utf-8")
            with self.assertRaises(RuntimeError):
                shared_module.load_shared(name, path)
            self.assertFalse(name in sys.modules, "a failed load left the half-built module behind")
            module = shared_module.load_shared(name, path)
        self.assertEqual(len(probe["runs"]), 2, "the second load ran the body again")
        self.assertTrue(getattr(module, "READY", False))
        self.assertFalse(hasattr(module, "PARTIAL"), "the retry got a fresh module, not the half-built one")


if __name__ == "__main__":
    unittest.main()
