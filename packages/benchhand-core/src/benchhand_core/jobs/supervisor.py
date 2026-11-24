"""The job supervisor: runs one command in a process group of its own and ends that group with it.

Stdlib only, and run by path (`python -I -S -B supervisor.py <owner> <grace> <status fd> <command...>`),
so a job starts without importing benchhand.

The supervisor leads its own session. It forks an anchor that leads a second process group and does
nothing but stay in it, then starts the command in that group, so everything the command starts
stays there. The supervisor reaps the anchor only after it has killed the group. Until then the
anchor, alive or a zombie, holds the group id, so no signal to the group can reach another process.

The supervisor reports on the status fd whether the command started: `started`, or
`error <errno> <message>` when it could not be executed. It then waits for the command and kills
the whole group when the command ends, when its owner ends, however abruptly, and `grace` seconds
after it was asked to stop; at the first request it sends TERM to the group. It exits with the
command's status, or dies of the same signal. Should the supervisor itself be killed outright, the
anchor sees it go and kills the group.
"""

from __future__ import annotations

import os
import resource
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

SUPERVISOR_SCRIPT = Path(__file__).resolve()
POLL_SECONDS = 0.1  # how often the supervisor checks its owner and the stop request
ANCHOR_POLL_SECONDS = 0.25  # how often the anchor checks its supervisor
START_FAILED = 127
STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


def _install_stop_handler() -> list[float]:
    """Record when the first stop request came in; the wait loop acts on it."""
    stopping: list[float] = []

    def stop(_signum: int, _frame: object) -> None:
        if not stopping:
            stopping.append(time.monotonic())

    for sig in STOP_SIGNALS:
        signal.signal(sig, stop)
    return stopping


def _end_like(code: int) -> None:
    """End the same way the command did, so the owner reads the command's own status."""
    if code < 0:
        with suppress(OSError, ValueError):  # the command's crash left its own core; add none
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        with suppress(OSError, ValueError):
            signal.signal(-code, signal.SIG_DFL)
        os.kill(os.getpid(), -code)
        os._exit(128 - code)
    os._exit(code)


def _hold_group(supervisor: int, status_fd: int) -> None:
    """The anchor: lead a process group, and kill it when the supervisor is gone."""
    os.close(status_fd)
    for sig in STOP_SIGNALS:
        signal.signal(sig, signal.SIG_DFL)
    os.setpgid(0, 0)
    while os.getppid() == supervisor:
        time.sleep(ANCHOR_POLL_SECONDS)
    os.killpg(0, signal.SIGKILL)


def _fork_anchor(status_fd: int) -> int:
    supervisor = os.getpid()
    anchor = os.fork()
    if anchor == 0:
        try:
            _hold_group(supervisor, status_fd)
        finally:
            os._exit(0)
    with suppress(OSError):  # the anchor does this too; whoever is first wins the race
        os.setpgid(anchor, anchor)
    return anchor


def _report(status_fd: int, line: str) -> None:
    with suppress(OSError):  # the owner stopped listening
        os.write(status_fd, f"{line}\n".encode())


def _end_group(anchor: int) -> None:
    """Kill everything in the anchor's group, the anchor included, and reap the anchor. The
    anchor is unreaped until now, so its id is still the group's."""
    with suppress(OSError):
        os.killpg(anchor, signal.SIGKILL)
    with suppress(OSError):
        os.kill(anchor, signal.SIGKILL)
    with suppress(ChildProcessError):
        os.waitpid(anchor, 0)


def _wait_for(
    child: subprocess.Popen[bytes], owner: int, grace_seconds: float, group: int, stopping: list[float]
) -> int:
    asked_to_stop = False
    while True:
        try:
            return child.wait(POLL_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        if stopping and not asked_to_stop:
            asked_to_stop = True
            with suppress(OSError):
                os.killpg(group, signal.SIGTERM)
        grace_over = bool(stopping) and time.monotonic() - stopping[0] > grace_seconds
        if os.getppid() != owner or grace_over:
            with suppress(OSError):
                os.killpg(group, signal.SIGKILL)


def supervise(owner: int, grace_seconds: float, status_fd: int, command: list[str]) -> None:
    stopping = _install_stop_handler()
    if os.getppid() != owner:
        os._exit(START_FAILED)
    anchor = _fork_anchor(status_fd)
    try:
        child = subprocess.Popen(command, process_group=anchor)
    except OSError as error:
        _report(status_fd, f"error {error.errno or 0} {str(error.strerror or error).splitlines()[0]}")
        _end_group(anchor)
        os._exit(START_FAILED)
    _report(status_fd, "started")
    os.close(status_fd)
    code = _wait_for(child, owner, grace_seconds, anchor, stopping)
    _end_group(anchor)
    _end_like(code)


if __name__ == "__main__":
    supervise(int(sys.argv[1]), float(sys.argv[2]), int(sys.argv[3]), sys.argv[4:])
