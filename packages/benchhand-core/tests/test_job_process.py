"""Supervised process groups with real processes, ported from the prototype's process_lifecycle tests.

A supervised family of a child and a grandchild that both ignore SIGTERM (a native solver stuck in
a call), parents killed outright, and programs that cannot start.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from benchhand_core.jobs.process import SupervisedProcess
from conftest import Pids
from job_support import FAMILY, LEAVER, LINGERER, python, running, wait_until


def spawn(argv: list[str], tmp_path: Path, grace_seconds: float = 0.5) -> SupervisedProcess:
    log = open(tmp_path / "out.log", "ab")  # noqa: SIM115 - the child holds its own copy
    try:
        return SupervisedProcess(argv, cwd=tmp_path, env=os.environ, output=log, grace_seconds=grace_seconds)
    finally:
        log.close()


def test_terminating_the_group_kills_a_family_that_ignores_sigterm(tmp_path: Path, pids: Pids) -> None:
    marker = tmp_path / "pids"
    process = spawn(python(FAMILY, str(marker)), tmp_path)
    child, grandchild = pids.family(marker)
    started = time.monotonic()
    code = process.terminate()
    assert time.monotonic() - started < 5
    assert code == -signal.SIGKILL
    pids.assert_gone(child, grandchild)
    assert process.terminate() == code  # idempotent


def test_a_group_that_outlives_its_supervisor_is_killed(tmp_path: Path, pids: Pids) -> None:
    marker = tmp_path / "pids"
    process = spawn(python(LINGERER, str(marker)), tmp_path)
    child, grandchild = pids.family(marker)
    code = process.terminate()
    assert code == -signal.SIGTERM  # the command's own status: its child died of SIGTERM
    pids.assert_gone(child, grandchild)


def test_a_process_left_by_a_command_that_ended_dies_without_the_owner_doing_anything(
    tmp_path: Path, pids: Pids
) -> None:
    marker = tmp_path / "grandchild"
    spawn(python(LEAVER, str(marker)), tmp_path)  # nobody polls, reaps or terminates it
    assert wait_until(marker.exists, 30)
    grandchild = int(marker.read_text())
    pids.known.append(grandchild)
    pids.assert_gone(grandchild)


def test_the_group_dies_when_its_parent_is_killed_outright(tmp_path: Path, pids: Pids) -> None:
    marker = tmp_path / "pids"
    parent_code = textwrap.dedent(f"""
        import os, sys, time
        from pathlib import Path
        from benchhand_core.jobs.process import SupervisedProcess
        log = open({str(tmp_path / "parent.log")!r}, "ab")
        process = SupervisedProcess([sys.executable, "-c", {FAMILY!r}, {str(marker)!r}],
                                    cwd=Path({str(tmp_path)!r}), env=os.environ, output=log)
        print(process.pid, flush=True)
        time.sleep(600)
    """)
    parent = subprocess.Popen(
        [sys.executable, "-c", parent_code], stdout=subprocess.PIPE, text=True, start_new_session=True
    )
    assert parent.stdout is not None
    try:
        supervisor = int(parent.stdout.readline())
        pids.known.append(supervisor)
        child, grandchild = pids.family(marker)
        os.killpg(parent.pid, signal.SIGKILL)  # the parent and its own group: nothing can clean up
    finally:
        parent.wait()
        parent.stdout.close()
    pids.assert_gone(supervisor, child, grandchild)


def test_the_group_still_dies_when_the_supervisor_is_killed_after_it_sent_terminate(
    tmp_path: Path, pids: Pids
) -> None:
    marker = tmp_path / "pids"
    process = spawn(python(FAMILY, str(marker)), tmp_path, grace_seconds=60)
    child, grandchild = pids.family(marker)
    pids.known.append(process.pid)
    process._popen.send_signal(signal.SIGTERM)  # the supervisor sends TERM to the group, which ignores it
    time.sleep(1)  # well past the supervisor's poll, well before its KILL
    assert running(child) and running(grandchild)
    process._popen.kill()  # the supervisor stalls and its owner's timeout kills it
    pids.assert_gone(child, grandchild)
    process.terminate()


def test_a_command_that_ends_by_itself_reports_its_status(tmp_path: Path) -> None:
    process = spawn(python("import sys; sys.exit(3)"), tmp_path)
    assert wait_until(process.exited, 30)
    assert process.terminate() == 3
    killed = spawn(python("import os, signal; os.kill(os.getpid(), signal.SIGUSR1)"), tmp_path)
    assert wait_until(killed.exited, 30)
    assert killed.terminate() == -signal.SIGUSR1


def test_a_missing_program_raises_like_subprocess(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        spawn([str(tmp_path / "missing")], tmp_path)
    with pytest.raises(FileNotFoundError):
        spawn(["benchhand-no-such-program"], tmp_path)
    script = tmp_path / "plain.txt"
    script.write_text("not a program")
    with pytest.raises(PermissionError):
        spawn([str(script)], tmp_path)


def test_a_program_is_found_through_a_relative_path_entry_of_the_jobs_cwd(tmp_path: Path) -> None:
    cwd = tmp_path / "work"
    (cwd / "bin").mkdir(parents=True)
    tool = cwd / "bin" / "tool"
    tool.write_text(f"#!{sys.executable}\nimport sys; sys.exit(7)\n")
    tool.chmod(0o755)
    log = open(tmp_path / "out.log", "ab")  # noqa: SIM115 - the child holds its own copy
    try:
        process = SupervisedProcess(
            ["tool"], cwd=cwd, env={**os.environ, "PATH": "bin"}, output=log, grace_seconds=0.5
        )
    finally:
        log.close()
    assert wait_until(process.exited, 30)
    assert process.terminate() == 7
