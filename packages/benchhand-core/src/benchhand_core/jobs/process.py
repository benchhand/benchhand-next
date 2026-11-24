"""A command in a process group of its own, under a supervisor that ends the group with it.

`SupervisedProcess` starts the supervisor (see supervisor.py), which starts the command and kills
the whole group when the command ends or this process does. The supervisor stays unreaped until
it exits, so its pid cannot be reused and signals to it never reach another process. This module
never signals a process group: the supervisor, which holds the group's id, does.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import IO

from benchhand_core.jobs.identity import Unsupported, process_identity, require_posix
from benchhand_core.jobs.supervisor import SUPERVISOR_SCRIPT

DEFAULT_GRACE_SECONDS = 2.0  # TERM to KILL
_STOP_MARGIN_SECONDS = 5.0  # beyond the grace, for a stuck supervisor to end before it is killed


class SupervisedProcess:
    """`pid` is the supervisor's and `identity` its start identity."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        output: IO[bytes],
        grace_seconds: float = DEFAULT_GRACE_SECONDS,
    ) -> None:
        """Raises what `subprocess.Popen` raises when the command cannot be executed from `cwd`,
        for example FileNotFoundError or PermissionError."""
        require_posix()
        if not command:
            raise ValueError("a supervised process needs a command")
        self.command = tuple(command)
        self.grace_seconds = grace_seconds
        read_fd, write_fd = os.pipe()
        try:
            self._popen = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    str(SUPERVISOR_SCRIPT),
                    str(os.getpid()),
                    str(grace_seconds),
                    str(write_fd),
                    *command,
                ],
                cwd=cwd,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                pass_fds=(write_fd,),
                start_new_session=True,
            )
        except BaseException:
            os.close(read_fd)
            raise
        finally:
            os.close(write_fd)
        try:
            self._await_start(read_fd)
            identity = process_identity(self.pid)  # the unreaped supervisor still has it
            if identity is None:
                raise Unsupported(f"the supervisor {self.pid} ended before it could be identified")
            self.identity = identity
        except BaseException:
            self.terminate()
            raise

    def _await_start(self, read_fd: int) -> None:
        with os.fdopen(read_fd, encoding="utf-8", errors="replace") as status:
            line = status.readline().strip()
        if line == "started":
            return
        code = self._popen.wait()
        kind, _, rest = line.partition(" ")
        number, _, message = rest.partition(" ")
        if kind == "error" and number.isdecimal() and int(number) > 0:
            raise OSError(int(number), message, self.command[0])
        raise OSError(f"the supervisor ended with status {code} before it started {self.command[0]}")

    @property
    def pid(self) -> int:
        return self._popen.pid

    def exited(self) -> bool:
        """Whether the command is over and its group gone: the supervisor ended. Reaps it."""
        return self._popen.poll() is not None

    def terminate(self) -> int:
        """Ask the supervisor to stop the command: TERM to its group, KILL after the grace period.
        Returns the command's exit status (a negative status is the signal that ended it).
        Idempotent."""
        if self._popen.returncode is None:
            try:
                self._popen.send_signal(signal.SIGTERM)  # a no-op once the supervisor is reaped
                return self._popen.wait(timeout=self.grace_seconds + _STOP_MARGIN_SECONDS)
            except subprocess.TimeoutExpired:
                self._popen.kill()  # the supervisor's anchor then kills the group
        return self._popen.wait()
