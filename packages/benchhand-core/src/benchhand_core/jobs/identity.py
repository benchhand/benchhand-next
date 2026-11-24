"""Process identity and pid-reuse safety.

The kernel reuses process ids, so a pid alone proves nothing once its process is gone. A recorded
process runs only while some process has that pid and that identity.

Nothing here lets a caller signal a recorded process or group: checking an identity and then
signalling leaves a window in which the pid can be reused. Only a process's own parent, which
has not reaped it, may signal it, and only a supervisor signals the group it holds.

POSIX only (Linux, macOS). A guarantee this platform cannot give raises `Unsupported`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from functools import cache
from pathlib import Path


class Unsupported(RuntimeError):
    """This platform cannot tell what a process identity needs."""


def require_posix() -> None:
    if os.name != "posix" or not hasattr(os, "killpg"):
        raise Unsupported(f"process groups are POSIX only; {sys.platform} has none")


@cache
def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return ""


def _linux_identity(pid: int) -> str | None:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="ascii", errors="replace")
    except (FileNotFoundError, ProcessLookupError):
        return None
    except OSError as error:
        raise Unsupported(f"cannot read /proc/{pid}/stat: {error}") from error
    # The command name may hold spaces and parentheses; the fields after the last ")" start at
    # field 3 (state), so field 22 (start time, in clock ticks after boot) is index 19.
    return f"{_boot_id()}:{stat.rpartition(')')[2].split()[19]}"


def _ps_identity(pid: int) -> str | None:
    ps = shutil.which("ps") or "/bin/ps"
    try:
        result = subprocess.run(
            [ps, "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            env={**os.environ, "LC_ALL": "C"},
            check=False,
        )
    except OSError as error:
        raise Unsupported(f"no /proc and no usable ps ({error}): process identities unavailable") from error
    started = " ".join(result.stdout.split())
    if started:
        return started
    if result.returncode == 1:
        return None
    raise Unsupported(f"`ps -o lstart= -p {pid}` failed: {result.stderr.strip() or result.returncode}")


def process_identity(pid: int) -> str | None:
    """The start identity of process `pid`, or None when no process has that id. A zombie keeps
    its identity until it is reaped."""
    if pid <= 0:
        raise ValueError(f"not a process id: {pid}")
    if sys.platform.startswith("linux"):
        return _linux_identity(pid)
    return _ps_identity(pid)


def process_runs(pid: int, recorded_identity: str) -> bool:
    """Whether the recorded process still runs: some process has its pid and its identity."""
    return process_identity(pid) == recorded_identity
