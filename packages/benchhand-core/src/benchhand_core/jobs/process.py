"""A command in a private process group, and the termination of such groups.

`SupervisedProcess` starts the command under the supervisor (see supervisor.py), which leads the
group. Its pid is the group id. The supervisor stays unreaped until the group is terminated:
an unreaped leader keeps its id, and so the group id, from reuse, so signals to the group can
never reach another process.
"""

from __future__ import annotations

import errno
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import IO

from benchhand_core.jobs.identity import (
    Unsupported,
    group_survives,
    pid_exists,
    process_identity,
    require_posix,
)
from benchhand_core.jobs.supervisor import SUPERVISOR_SCRIPT

DEFAULT_GRACE_SECONDS = 2.0  # TERM to KILL
_WAIT_STEP_SECONDS = 0.02
_KILL_WAIT_SECONDS = 1.0  # for the kernel to tear a killed group down


def check_program(program: str, cwd: Path, env: Mapping[str, str]) -> None:
    """Raise what subprocess would raise for a missing or non-executable program, before a
    supervisor starts."""
    if os.path.dirname(program):
        path = Path(program) if os.path.isabs(program) else cwd / program
        if not path.is_file():
            raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), program)
        if not os.access(path, os.X_OK):
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), program)
    elif shutil.which(program, path=os.pathsep.join(os.get_exec_path(dict(env)))) is None:
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), program)


class SupervisedProcess:
    """`pid` is the supervisor's, which is also the group id, and `identity` its start identity."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        output: IO[bytes],
        grace_seconds: float = DEFAULT_GRACE_SECONDS,
    ) -> None:
        require_posix()
        if not command:
            raise ValueError("a supervised process needs a command")
        check_program(command[0], cwd, env)
        self.command = tuple(command)
        self._popen = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-S",
                "-B",
                str(SUPERVISOR_SCRIPT),
                str(os.getpid()),
                str(grace_seconds),
                *command,
            ],
            cwd=cwd,
            env=dict(env),
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._group_ended = False
        try:
            identity = process_identity(self.pid)  # the unreaped supervisor still has it
            if identity is None:
                raise Unsupported(f"the supervisor {self.pid} ended before it could be identified")
            self.identity = identity
        except BaseException:
            self.terminate(grace_seconds=0)
            raise

    @property
    def pid(self) -> int:
        return self._popen.pid

    def exited(self) -> bool:
        """Whether the supervised command is over, without reaping its supervisor. Poll with
        this, then call `terminate`, which kills what the command left in its group while the
        unreaped supervisor still holds the group id.

        Without os.waitid (macOS before Python 3.13) Popen.poll reaps the supervisor and records
        its status, so `_signal_group` takes its reaped branch and `terminate` returns the
        recorded status."""
        if self._popen.returncode is not None:
            return True
        if not hasattr(os, "waitid"):
            return self._popen.poll() is not None
        try:
            return os.waitid(os.P_PID, self.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
        except ChildProcessError:
            return True

    def _signal_group(self, sig: int) -> None:
        # Once the supervisor is reaped its id is free. While another process holds it, our group
        # is gone, since no new process gets an id that is still a group id.
        if self._popen.returncode is not None and pid_exists(self.pid):
            return
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(self.pid, sig)

    def terminate(self, grace_seconds: float = DEFAULT_GRACE_SECONDS) -> int:
        """TERM the process group, wait up to `grace_seconds` for the supervisor to exit, KILL the
        group, and then reap the supervisor. Returns its exit status, which is the command's
        status when the command ended first (a negative status is the signal that ended it).
        Idempotent."""
        if not self._group_ended:
            self._signal_group(signal.SIGTERM)
            deadline = time.monotonic() + grace_seconds
            while not self.exited() and time.monotonic() < deadline:
                time.sleep(_WAIT_STEP_SECONDS)
            self._signal_group(signal.SIGKILL)
            self._group_ended = True
        return self._popen.wait()


def terminate_recorded_group(
    pgid: int, leader_identity: str, grace_seconds: float = DEFAULT_GRACE_SECONDS
) -> None:
    """TERM, wait, then KILL a process group nobody here supervises, after checking that the
    recorded leader identity still owns the group id. Signals nothing when it does not."""
    for sig, wait_seconds in ((signal.SIGTERM, grace_seconds), (signal.SIGKILL, _KILL_WAIT_SECONDS)):
        if not group_survives(pgid, leader_identity):
            return
        with suppress(ProcessLookupError, PermissionError):
            os.killpg(pgid, sig)
        deadline = time.monotonic() + wait_seconds
        while group_survives(pgid, leader_identity) and time.monotonic() < deadline:
            time.sleep(_WAIT_STEP_SECONDS)
