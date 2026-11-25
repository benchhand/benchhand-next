"""Helpers for the job service tests: real processes that ignore SIGTERM, and contract examples."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from importlib.resources import files
from typing import Any

CONTRACT = files("benchhand_contracts") / "schemas" / "jobs" / "job.schema.json"

# A job gets this long to start on a loaded host. A test that waits longer gives up.
STARTUP_SECONDS = 120.0

# A child and its grandchild that ignore SIGTERM and run for ten minutes; the child writes both pids.
FAMILY = textwrap.dedent("""
    import os, signal, subprocess, sys, time
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    with open(sys.argv[1] + ".tmp", "w") as out:
        out.write(f"{os.getpid()} {grandchild.pid}")
    os.replace(sys.argv[1] + ".tmp", sys.argv[1])
    time.sleep(600)
""")

# A child that dies on SIGTERM and a grandchild that ignores it. The child writes both pids once the
# grandchild reports that it ignores SIGTERM.
LINGERER = textwrap.dedent("""
    import os, signal, subprocess, sys, time
    ready = sys.argv[1] + ".ready"
    grandchild = subprocess.Popen([sys.executable, "-c", "import signal, sys, time; "
                                   "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
                                   "open(sys.argv[1], 'w').close(); time.sleep(600)", ready])
    deadline = time.monotonic() + 60
    while not os.path.exists(ready):
        if time.monotonic() > deadline:
            sys.exit("the grandchild never reported that it ignores SIGTERM")
        time.sleep(0.01)
    with open(sys.argv[1] + ".tmp", "w") as out:
        out.write(f"{os.getpid()} {grandchild.pid}")
    os.replace(sys.argv[1] + ".tmp", sys.argv[1])
    time.sleep(600)
""")

# A command that leaves a grandchild behind and ends at once.
LEAVER = textwrap.dedent("""
    import subprocess, sys
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    open(sys.argv[1], "w").write(str(grandchild.pid))
""")


def running(pid: int) -> bool:
    """Whether `pid` runs: a zombie waiting to be reaped has ended."""
    ps = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False)
    state = ps.stdout.strip()
    return bool(state) and not state.startswith("Z")


def wait_until(predicate: Callable[[], Any], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def example_record(**overrides: Any) -> dict[str, Any]:
    """The contract's first example (a running JobRecord) with `overrides`."""
    record = copy.deepcopy(json.loads(CONTRACT.read_text())["examples"][0])
    record.update(overrides)
    return record


def python(code: str, *args: str) -> list[str]:
    return [sys.executable, "-c", code, *args]
