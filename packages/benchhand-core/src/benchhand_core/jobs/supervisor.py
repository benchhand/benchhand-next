"""The job supervisor: runs one command as the leader of its own session and process group.

Stdlib only, and run by path (`python -I -S -B supervisor.py <parent> <grace> <command...>`), so a
job starts without importing benchhand. The supervisor runs the command as its child and exits with
the command's status, or dies of the same signal. Everything the command starts stays in the
group. The supervisor polls its parent, and when the parent ends, however abruptly, it kills the
whole group, grandchildren included. On SIGTERM it forwards TERM to the group and kills the group
`grace` seconds later.
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
from typing import Any

SUPERVISOR_SCRIPT = Path(__file__).resolve()
POLL_SECONDS = 0.1  # how often the supervisor checks its parent
START_FAILED = 127


def _install_stop_handler() -> list[float]:
    stopping: list[float] = []

    def stop(_signum: int, _frame: Any) -> None:
        if not stopping:
            stopping.append(time.monotonic())
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            os.killpg(0, signal.SIGTERM)

    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, stop)
    return stopping


def _end_like(code: int) -> None:
    """End the same way the command did, so the parent reads the command's own status."""
    if code < 0:
        with suppress(OSError, ValueError):  # the command's crash left its own core; add none
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        with suppress(OSError, ValueError):
            signal.signal(-code, signal.SIG_DFL)
        os.kill(os.getpid(), -code)
        os._exit(128 - code)
    os._exit(code)


def supervise(parent: int, grace_seconds: float, command: list[str]) -> None:
    stopping = _install_stop_handler()
    if os.getppid() != parent:
        os.killpg(0, signal.SIGKILL)
    try:
        child = subprocess.Popen(command)
    except OSError as error:
        print(f"supervisor: cannot start {command[0]}: {error}", file=sys.stderr, flush=True)
        os._exit(START_FAILED)
    while True:
        try:
            code = child.wait(POLL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            pass
        grace_over = bool(stopping) and time.monotonic() - stopping[0] > grace_seconds
        if os.getppid() != parent or grace_over:
            os.killpg(0, signal.SIGKILL)
    _end_like(code)


if __name__ == "__main__":
    supervise(int(sys.argv[1]), float(sys.argv[2]), sys.argv[3:])
