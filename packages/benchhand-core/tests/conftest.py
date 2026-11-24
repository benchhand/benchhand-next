from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Iterator
from contextlib import suppress
from pathlib import Path

import pytest
from benchhand_core.jobs import JobService
from job_support import running, wait_until


class Pids:
    """Process ids a test learned of, killed at the end whatever the test did."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.known: list[int] = []

    def family(self, path: Path, timeout: float = 10.0) -> tuple[int, int]:
        assert wait_until(path.exists, timeout), "the job did not start"
        child, grandchild = (int(pid) for pid in path.read_text().split())
        self.known += [child, grandchild]
        return child, grandchild

    def sleeper(self) -> subprocess.Popen[bytes]:
        """A live session leader that is no job."""
        sleep = [sys.executable, "-c", "import time; time.sleep(600)"]
        process = subprocess.Popen(sleep, start_new_session=True)
        self.known.append(process.pid)
        return process

    def ended_pid(self) -> int:
        process = subprocess.Popen([sys.executable, "-c", "pass"])
        process.wait()
        return process.pid

    def assert_gone(self, *pids: int) -> None:
        for pid in pids:
            assert wait_until(lambda pid=pid: not running(pid)), f"process {pid} survived"


@pytest.fixture(autouse=True)
def posix_only() -> None:
    if os.name != "posix":
        pytest.skip("process groups are POSIX only")


@pytest.fixture
def pids(tmp_path: Path) -> Iterator[Pids]:
    holder = Pids(tmp_path)
    yield holder
    for pid in holder.known:
        with suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.fixture
def service(project: Path) -> Iterator[JobService]:
    with JobService(project, grace_seconds=0.5) as jobs:
        yield jobs


@pytest.fixture(params=["with-waitid", "without-waitid"])
def waitid_variant(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    """The same groups where os has no waitid: macOS before Python 3.13."""
    if request.param == "without-waitid":
        monkeypatch.delattr(os, "waitid", raising=False)
    return request.param
