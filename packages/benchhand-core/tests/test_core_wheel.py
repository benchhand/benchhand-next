"""The built benchhand-core wheel runs a job when installed outside this checkout."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGES = Path(__file__).resolve().parents[2]
UV = shutil.which("uv")

# Runs in the fresh venv, from a directory outside the checkout.
SMOKE_SCRIPT = """
import sys
import time
from pathlib import Path

import benchhand_core
from benchhand_core.jobs import JobService, JobSpec

assert not benchhand_core.__file__.startswith(sys.argv[1]), benchhand_core.__file__
with JobService(Path(sys.argv[2])) as service:
    job_id = service.start(JobSpec("smoke/run", [sys.executable, "-c", "pass"])).job_id
    deadline = time.monotonic() + 60
    while service.status(job_id).status.value in ("queued", "running"):
        assert time.monotonic() < deadline, "the job never ended"
        time.sleep(0.05)
    assert service.status(job_id).status.value == "succeeded", service.status(job_id)
"""


@pytest.mark.wheel
@pytest.mark.skipif(UV is None, reason="needs uv")
def test_the_installed_wheel_runs_a_job_without_a_checkout(tmp_path: Path) -> None:
    assert UV is not None
    dist, venv, project = tmp_path / "dist", tmp_path / "venv", tmp_path / "project"
    project.mkdir()
    env = {key: value for key, value in os.environ.items() if key not in ("PYTHONPATH", "VIRTUAL_ENV")}

    def run(*command: str | Path) -> None:
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=False)
        assert result.returncode == 0, f"{command}:\n{result.stdout}{result.stderr}"

    for package in ("benchhand-contracts", "benchhand-core"):
        run(UV, "build", "--wheel", "--quiet", "--out-dir", dist, PACKAGES / package)
    run(UV, "venv", "--quiet", "--python", sys.executable, venv)
    python = venv / "bin" / "python"
    [contracts] = dist.glob("benchhand_contracts-*.whl")
    [core] = dist.glob("benchhand_core-*.whl")
    run(UV, "pip", "install", "--quiet", "--python", python, contracts)
    # core's other workspace dependency, benchhand-provider, is not used by jobs.
    run(UV, "pip", "install", "--quiet", "--python", python, "--no-deps", core)
    run(python, "-c", SMOKE_SCRIPT, PACKAGES.parent, project)
