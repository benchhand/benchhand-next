# /// script
# requires-python = ">=3.12,<3.13"
# dependencies = ["cadquery==2.8.0", "cadquery-ocp==7.9.3.1.1", "vtk==9.6.2"]
# ///
"""Test double for run_cadquery.py: the real runner, but its worker pool keeps a worker for many parts.

test_runner_parallel.py uses it to show that its STEP occurrence-id check notices a reused worker.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from cadmodel import runner  # noqa: E402

POOL = runner.ProcessPoolExecutor


def reusing_pool(**kwargs):
    kwargs.pop("max_tasks_per_child", None)
    return POOL(**kwargs)


if __name__ == "__main__":
    runner.ProcessPoolExecutor = reusing_pool
    sys.exit(runner.main("cadquery", ("cadquery", "cadquery-ocp", "vtk")))
