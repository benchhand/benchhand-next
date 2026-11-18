"""The STEP FILE_NAME time is a constant: STEP bytes depend on the shape alone, never on the clock or the environment."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROBE = HERE / "fixtures" / "step_header_probe.py"

FILE_NAME = re.compile(rb"FILE_NAME\('[^']*','([^']*)'")
# STEP wraps long lines, so the name may follow a line break
VALIDATION_PROPERTY = re.compile(rb"PROPERTY_DEFINITION\('geometric validation property',\s*'([^']*)'")


@unittest.skipUnless(shutil.which("uv"), "uv is required to write STEP through OCP")
class StepHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    def write(self, name: str, epoch: str | None = None, mode: str = "box") -> bytes:
        env = {key: value for key, value in os.environ.items() if key != "SOURCE_DATE_EPOCH"}
        if epoch is not None:
            env["SOURCE_DATE_EPOCH"] = epoch
        out = self.root / name
        proc = subprocess.run(["uv", "run", "--quiet", "--script", str(PROBE), str(out), mode], env=env,
                              capture_output=True, text=True, check=False, timeout=900)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return out.read_bytes()

    def test_two_writes_are_byte_identical_across_clock_seconds(self) -> None:
        first = self.write("a.step")
        time.sleep(1.1)   # the wall clock OCCT would stamp has moved on
        second = self.write("b.step")
        self.assertEqual(first, second)

    def test_curved_and_assembly_writes_are_byte_identical_with_validation_properties(self) -> None:
        # volume, area and centroid are floats from adaptive integration: curved faces and the assembly path must repeat them exactly
        for mode in ("halftorus", "tilted", "assembly", "placed"):
            with self.subTest(mode=mode):
                first = self.write(f"{mode}-a.step", mode=mode)
                second = self.write(f"{mode}-b.step", mode=mode)
                self.assertEqual(sorted(VALIDATION_PROPERTY.findall(first)), [b"centroid", b"surface area", b"volume"])
                self.assertEqual(first, second)

    def test_header_time_is_the_fixed_date(self) -> None:
        self.assertEqual(FILE_NAME.search(self.write("fixed.step")).group(1), b"1980-01-01T00:00:00")

    def test_source_date_epoch_does_not_change_the_bytes(self) -> None:
        # a cache key that omits the environment must never see two byte-different STEPs
        plain = self.write("plain.step")
        for epoch in ("1700000000", "not-a-number"):
            with self.subTest(epoch=epoch):
                self.assertEqual(self.write(f"epoch-{epoch}.step", epoch), plain)


if __name__ == "__main__":
    unittest.main()
