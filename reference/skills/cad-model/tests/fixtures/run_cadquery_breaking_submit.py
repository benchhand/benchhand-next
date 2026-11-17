# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["cadquery==2.8.0", "cadquery-ocp==7.9.3.1.1", "vtk==9.6.2"]
# ///
"""Test double for run_cadquery.py: the real runner, but its worker pool reports itself broken on the third submit.

test_runner_parallel.py uses it to force a pool failure while the runner is still submitting parts.
"""

import sys
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from cadmodel import runner  # noqa: E402

POOL = runner.ProcessPoolExecutor


class BreaksOnThirdSubmit(POOL):
    submits = 0

    def submit(self, *args, **kwargs):
        type(self).submits += 1
        if type(self).submits == 3:
            raise BrokenProcessPool("a worker died while the runner was submitting")
        return super().submit(*args, **kwargs)


if __name__ == "__main__":
    runner.ProcessPoolExecutor = BreaksOnThirdSubmit
    sys.exit(runner.main("cadquery", ("cadquery", "cadquery-ocp", "vtk")))
