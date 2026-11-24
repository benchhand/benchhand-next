#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""Parallel part builds in the kernel runner: CAD_MODEL_BUILD_JOBS, request order, per-part isolation.

Run: python3 -B -m unittest discover -s skills/cad-model/tests -p test_runner_parallel.py
`build_jobs` needs nothing; the build tests start the real CadQuery runner through `run_kernels` (uv).
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
from cadmodel import build, runner  # noqa: E402 - stdlib-only imports; OCP loads in the runner

BOX = """import time
import cadquery as cq
KERNEL = "cadquery"
PARAMS = {{"size": {size}}}
def build(params):
    time.sleep({delay})
    s = params["size"]
    return cq.Solid.makeBox(s, s + 1, s + 2)
"""
SYNC = """import os, time
from pathlib import Path
import cadquery as cq
KERNEL = "cadquery"
PARAMS = {{}}
def build(params):
    signals = Path({signals!r})
    (signals / str(os.getpid())).touch()
    deadline = time.monotonic() + 30
    while len(list(signals.iterdir())) < 2:
        if time.monotonic() > deadline:
            raise TimeoutError("the other part never started")
        time.sleep(0.05)
    return cq.Solid.makeBox(3, 4, 5)
"""
CRASH = """import os
KERNEL = "cadquery"
PARAMS = {}
def build(params):
    os._exit(3)
"""
TWIN = """import cadquery as cq
KERNEL = "cadquery"
PARAMS = {}
def build(params):
    return cq.Solid.makeBox(3, 4, 5).moved(cq.Location(cq.Vector(5, 0, 0)))
"""
BROKEN = """KERNEL = "cadquery"
PARAMS = {}
def build(params):
    raise ValueError("no good")
"""
NOISY = """import logging
import cadquery as cq
KERNEL = "cadquery"
PARAMS = {}
def build(params):
    logging.getLogger("cadmodel.fillets").warning("skipped edge E1")
    return cq.Solid.makeBox(3, 4, 5)
"""
WHERE = """import json, multiprocessing, os
import cadquery as cq
KERNEL = "cadquery"
PARAMS = {}
def build(params):
    server, runner = os.getppid(), multiprocessing.parent_process().pid
    with open(os.environ["WHERE_LOG"] + "/" + str(os.getpid()), "w") as out:
        json.dump({"pid": os.getpid(), "server": server, "runner": runner, "pgrp": os.getpgrp(),
                   "server_pgrp": os.getpgid(server), "runner_pgrp": os.getpgid(runner)}, out)
    return cq.Solid.makeBox(3, 4, 5)
"""
HOLD = """import multiprocessing, os, time
from pathlib import Path
import cadquery as cq
from cadmodel.build import write_json
KERNEL = "cadquery"
PARAMS = {}
def build(params):
    server, runner = os.getppid(), multiprocessing.parent_process().pid
    write_json(Path(os.environ["WHERE_LOG"]) / str(os.getpid()),
               {"pid": os.getpid(), "server": server, "runner": runner})
    time.sleep(120)
    return cq.Solid.makeBox(3, 4, 5)
"""
# (pn, source): the slow part is first so a completion-order result would differ from request order
PROJECT = [
    ("TST-0001", BOX.format(size=10, delay=2.0)),
    ("TST-0002", BROKEN),
    ("TST-0003", NOISY),
    ("TST-0004", BOX.format(size=20, delay=0)),
    ("TST-0005", BOX.format(size=30, delay=0)),
]


class BuildJobs(unittest.TestCase):
    def test_default_is_half_the_cpus_capped_by_parts_and_four(self) -> None:
        for cpus, parts, want in [(16, 20, 4), (16, 3, 3), (8, 20, 4), (4, 20, 2), (2, 20, 1), (1, 20, 1), (16, 1, 1)]:
            with self.subTest(cpus=cpus, parts=parts):
                self.assertEqual(runner.build_jobs(parts, {}, cpus), want)

    def test_env_overrides_but_never_exceeds_the_parts(self) -> None:
        for raw, parts, want in [("1", 5, 1), ("3", 5, 3), ("12", 5, 5), (" 2 ", 5, 2)]:
            with self.subTest(raw=raw):
                self.assertEqual(
                    runner.build_jobs(parts, {runner.BUILD_JOBS_ENV: raw}, 16), want
                )

    def test_env_must_be_a_positive_integer(self) -> None:
        for raw in ("0", "-1", "two", "1.5"):
            with (
                self.subTest(raw=raw),
                self.assertRaisesRegex(ValueError, runner.BUILD_JOBS_ENV),
            ):
                runner.build_jobs(5, {runner.BUILD_JOBS_ENV: raw}, 16)


REUSING_RUNNER = HERE / "fixtures" / "run_cadquery_reusing_workers.py"
BREAKING_SUBMIT_RUNNER = HERE / "fixtures" / "run_cadquery_breaking_submit.py"


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def step_bytes(path: Path) -> bytes:
    """The STEP bytes with only the FILE_NAME header's wall-clock timestamp masked."""
    return re.sub(rb"(FILE_NAME\('[^']*',')[^']*'", rb"\1<time>'", path.read_bytes())


def step_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _WriteSpy:
    """A file object that records which sidecar names are visible each time bytes reach it."""

    def __init__(self, file: Any, seen: Any) -> None:
        self._file = file
        self._seen = seen

    def write(self, data: Any) -> Any:
        self._seen()
        return self._file.write(data)

    def __enter__(self) -> "_WriteSpy":
        self._file.__enter__()
        return self

    def __exit__(self, *exc: Any) -> Any:
        return self._file.__exit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._file, name)


def names_visible_at_each_write(folder: Path, action: Any) -> list[list[str]]:
    """Run `action`. At every file write, record the sidecar names a reader could see."""
    visible: list[list[str]] = []
    real_open = io.open

    def spying_open(*args: Any, **kwargs: Any) -> Any:
        file = real_open(*args, **kwargs)
        if "w" not in (args[1] if len(args) > 1 else kwargs.get("mode", "r")):
            return file
        return _WriteSpy(file, lambda: visible.append([p.name for p in folder.glob("[0-9]*")]))

    with mock.patch("io.open", spying_open), mock.patch("builtins.open", spying_open):
        action()
    return visible


def write_in_place(folder: Path) -> None:
    """The original fixture's way: it creates the final name before it writes the content."""
    with open(folder / "1", "w") as out:
        json.dump({"pid": 1}, out)


def serialise_then_write_in_place(folder: Path) -> None:
    """It serializes first, but still creates the final name and writes into it."""
    (folder / "1").write_text(json.dumps({"pid": 1}), encoding="utf-8")


class HoldSidecar(unittest.TestCase):
    def setUp(self) -> None:
        self.sidecars = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_a_reader_could_see_the_name_during_a_non_atomic_write(self) -> None:
        # negative controls: the spy must flag writers that expose the final name before the content is whole
        for writer in (write_in_place, serialise_then_write_in_place):
            with self.subTest(writer=writer.__name__):
                folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
                visible = names_visible_at_each_write(folder, lambda: writer(folder))
                self.assertTrue(visible, "no write was observed")
                self.assertIn(["1"], visible)

    def test_hold_sidecar_is_never_visible_half_written(self) -> None:
        # the readiness check counts sidecars by name, so a name must only appear once its JSON is complete
        class Held(Exception):
            pass

        def stop_at_sleep(_seconds: float) -> None:
            raise Held

        def run_fixture() -> None:
            with (
                mock.patch.dict(sys.modules, {"cadquery": mock.Mock()}),
                mock.patch.dict(os.environ, {"WHERE_LOG": str(self.sidecars)}),
                mock.patch("multiprocessing.parent_process", return_value=mock.Mock(pid=1)),
                mock.patch("time.sleep", stop_at_sleep),
            ):
                namespace: dict[str, Any] = {}
                exec(HOLD, namespace)
                with self.assertRaises(Held):
                    namespace["build"]({})

        visible = names_visible_at_each_write(self.sidecars, run_fixture)
        self.assertTrue(visible, "no write was observed")
        self.assertTrue(all(names == [] for names in visible), visible)
        written = json.loads((self.sidecars / str(os.getpid())).read_text())
        self.assertEqual(written["pid"], os.getpid())
        self.assertEqual(list(self.sidecars.iterdir()), [self.sidecars / str(os.getpid())])


@unittest.skipUnless(shutil.which("uv"), "uv is required to start the runners")
class ParallelBuilds(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.where = cls.root / "pids"
        cls.where.mkdir()
        cls.requests = cls.request("main", PROJECT)
        cls.serial = cls.run_with("1", "serial")
        cls.pool = cls.run_with("3", "pool")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    @classmethod
    def request(
        cls, tag: str, project: list[tuple[str, str]], out: str = ""
    ) -> list[dict[str, str]]:
        parts = []
        for pn, source in project:
            folder = cls.root / tag / "hw" / "parts" / pn
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "model.py").write_text(source, encoding="utf-8")
            parts.append({"pn": pn, "name": pn, "model": str(folder / "model.py")})
        return parts

    @classmethod
    def run_with(
        cls,
        jobs: str,
        label: str,
        parts: list[dict[str, str]] | None = None,
        script: Path | None = None,
    ) -> dict:
        parts = [
            dict(p, step=str(cls.root / label / f"{p['pn']}.step"))
            for p in parts or cls.requests
        ]
        scripts = {"cadquery": script} if script else {}
        with (
            mock.patch.dict(
                os.environ, {runner.BUILD_JOBS_ENV: jobs, "WHERE_LOG": str(cls.where)}
            ),
            mock.patch.dict(build.RUNNERS, scripts),
        ):
            return build.run_kernels({"cadquery": parts})["cadquery"]

    def test_results_follow_request_order_not_completion_order(self) -> None:
        self.assertEqual(list(self.pool["parts"]), [pn for pn, _ in PROJECT])
        reversed_parts = self.run_with("3", "reversed", list(reversed(self.requests)))
        self.assertEqual(
            list(reversed_parts["parts"]), [pn for pn, _ in reversed(PROJECT)]
        )

    def test_a_failing_part_fails_alone_with_the_serial_error(self) -> None:
        for result in (self.serial, self.pool):
            parts = result["parts"]
            self.assertEqual(
                [pn for pn, part in parts.items() if not part["ok"]], ["TST-0002"]
            )
        self.assertEqual(
            self.pool["parts"]["TST-0002"], self.serial["parts"]["TST-0002"]
        )
        self.assertEqual(
            self.pool["parts"]["TST-0002"]["error"],
            {
                "type": "ValueError",
                "message": "no good",
                "where": "model.py:4 in build",
            },
        )

    def test_fillet_warnings_stay_with_their_part(self) -> None:
        warned = {pn: part.get("warnings") for pn, part in self.pool["parts"].items()}
        self.assertEqual(
            warned,
            {
                "TST-0001": None,
                "TST-0002": None,
                "TST-0003": ["skipped edge E1"],
                "TST-0004": None,
                "TST-0005": None,
            },
        )

    def test_one_job_and_several_give_the_same_results_and_step_bytes(self) -> None:
        def stable(result: dict) -> dict:
            parts = {
                pn: {k: v for k, v in part.items() if k != "build_s"}
                for pn, part in result["parts"].items()
            }
            return {
                "parts": parts,
                "sources": result["sources"],
                "tools": result["tools"],
            }

        def step(label: str, pn: str) -> bytes:
            return step_bytes(self.root / label / f"{pn}.step")

        self.assertEqual(stable(self.pool), stable(self.serial))
        for pn, part in self.serial["parts"].items():
            if part["ok"]:
                self.assertEqual(step("pool", pn), step("serial", pn), pn)

    def test_workers_share_the_runners_process_group_and_leave_no_bytecode(
        self,
    ) -> None:
        parts = self.request("located", [(f"TST-{i:04d}", WHERE) for i in range(1, 5)])
        for old in self.where.iterdir():
            old.unlink()
        result = self.run_with("2", "where", parts)
        self.assertTrue(
            all(part["ok"] for part in result["parts"].values()), result["parts"]
        )
        seen = [json.loads(path.read_text()) for path in self.where.iterdir()]
        self.assertTrue(seen)
        for entry in seen:  # the group build._stop kills is the runner's
            self.assertEqual(entry["pgrp"], entry["runner_pgrp"], entry)
            self.assertEqual(entry["server_pgrp"], entry["runner_pgrp"], entry)
            self.assertNotEqual(entry["pgrp"], os.getpgrp(), "run_kernels starts a session of its own")
            self.assertNotEqual(entry["pid"], entry["server"])
            self.assertNotEqual(entry["server"], entry["runner"])
        self.assertFalse(
            list(self.root.rglob("__pycache__")),
            "workers must not write bytecode beside model.py",
        )

    def occurrence_ids(self, label: str, pns: list[str]) -> list[str]:
        ids = []
        for pn in pns:
            found = re.search(r"NEXT_ASSEMBLY_USAGE_OCCURRENCE\('(\d+)'", step_text(self.root / label / f"{pn}.step"))
            self.assertIsNotNone(found, pn)
            ids.append(found.group(1))
        return ids

    def test_located_parts_give_the_same_step_bytes_with_one_job_and_several(self) -> None:
        # OCCT numbers NEXT_ASSEMBLY_USAGE_OCCURRENCE from a process-wide counter: a part's bytes must
        # not depend on how many parts the same process wrote before it
        pns = [f"TST-{i:04d}" for i in range(1, 5)]
        parts = self.request("twins", [(pn, TWIN) for pn in pns])
        self.run_with("1", "twins1", parts)
        self.run_with("3", "twins3", parts)
        for pn in pns:
            self.assertEqual(
                step_bytes(self.root / "twins1" / f"{pn}.step"),
                step_bytes(self.root / "twins3" / f"{pn}.step"),
                pn,
            )
        self.assertEqual(self.occurrence_ids("twins3", pns), ["1"] * 4)

    def test_the_occurrence_check_notices_a_reused_worker(self) -> None:
        pns = [f"TST-{i:04d}" for i in range(1, 4)]
        parts = self.request("reuse", [(pn, TWIN) for pn in pns])
        self.run_with("1", "reuse", parts, script=REUSING_RUNNER)
        self.assertEqual(self.occurrence_ids("reuse", pns), ["1", "2", "3"])

    def test_parts_build_at_the_same_time_in_different_workers(self) -> None:
        # Each part signals its start and waits for the other. Serial scheduling times the wait out.
        signals = self.root / "signals"
        signals.mkdir()
        parts = self.request("sync", [(f"TST-{i:04d}", SYNC.format(signals=str(signals))) for i in (1, 2)])
        result = self.run_with("2", "sync", parts)
        self.assertTrue(all(part["ok"] for part in result["parts"].values()), result["parts"])
        pids = {path.name for path in signals.iterdir()}
        self.assertEqual(len(pids), 2, pids)
        self.assertNotIn(str(os.getpid()), pids)

    def test_a_worker_that_dies_fails_only_the_parts_it_did_not_finish(self) -> None:
        # one worker at a time: TST-0001 is done before TST-0002 kills its worker, TST-0003 never starts
        parts = self.request(
            "crash", [("TST-0001", BOX.format(size=10, delay=0)), ("TST-0002", CRASH), ("TST-0003", NOISY)]
        )
        result = self.run_with("1", "crash", parts)
        self.assertEqual(list(result["parts"]), ["TST-0001", "TST-0002", "TST-0003"])
        self.assertTrue(result["parts"]["TST-0001"]["ok"])
        for pn in ("TST-0002", "TST-0003"):
            part = result["parts"][pn]
            self.assertFalse(part["ok"], pn)
            self.assertEqual(set(part), {"ok", "error"})
            self.assertEqual(part["error"]["type"], "WorkerCrashed")
            self.assertEqual(set(part["error"]), {"type", "message", "where"})

    def test_a_pool_that_breaks_while_submitting_fails_only_the_unsubmitted_parts(self) -> None:
        pns = [f"TST-{i:04d}" for i in range(1, 5)]
        parts = self.request("submit", [(pn, BOX.format(size=10, delay=0)) for pn in pns])
        result = self.run_with("1", "submit", parts, script=BREAKING_SUBMIT_RUNNER)
        self.assertEqual(list(result["parts"]), pns)
        self.assertTrue(result["parts"]["TST-0001"]["ok"])
        self.assertTrue(result["parts"]["TST-0002"]["ok"])
        for pn in ("TST-0003", "TST-0004"):
            part = result["parts"][pn]
            self.assertEqual(set(part), {"ok", "error"}, pn)
            self.assertFalse(part["ok"], pn)
            self.assertEqual(part["error"]["type"], "WorkerCrashed", pn)
            self.assertEqual(set(part["error"]), {"type", "message", "where"}, pn)

    def test_import_s_is_measured_when_every_part_crashes(self) -> None:
        parts = self.request("allcrash", [(f"TST-{i:04d}", CRASH) for i in range(1, 4)])
        result = self.run_with("2", "allcrash", parts)
        self.assertTrue(all(not part["ok"] for part in result["parts"].values()), result["parts"])
        self.assertGreater(result["import_s"], 0.0)

    def test_killing_the_runners_group_takes_the_server_and_every_worker(self) -> None:
        # the runner starts as build.py starts it: a session of its own, killed through build._stop
        pids = self.root / "cancel"
        pids.mkdir()
        parts = self.request("cancel", [(f"TST-{i:04d}", HOLD) for i in range(1, 3)])
        request = {"result": str(self.root / "cancel.json"),
                   "parts": [dict(p, step=str(self.root / "cancel" / f"{p['pn']}.step")) for p in parts]}
        env = dict(os.environ, **{runner.BUILD_JOBS_ENV: "2", "WHERE_LOG": str(pids)})
        proc = subprocess.Popen(build.scriptenv.script_command(build.RUNNERS["cadquery"]), stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True, env=env,
                                start_new_session=True)
        seen: list[int] = []
        try:
            proc.stdin.write(json.dumps(request))
            proc.stdin.close()
            deadline = time.monotonic() + 180
            while len(list(pids.glob("[0-9]*"))) < 2:
                self.assertLess(time.monotonic(), deadline, "the workers never started")
                self.assertIsNone(proc.poll(), "the runner exited early")
                time.sleep(0.2)
            entries = [json.loads(path.read_text()) for path in pids.glob("[0-9]*")]
            seen = sorted({proc.pid, *(e["pid"] for e in entries), *(e["server"] for e in entries),
                           *(e["runner"] for e in entries)})
            self.assertGreaterEqual(len(seen), 5, seen)  # uv, the runner, the server, two workers
            build._stop([proc])
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and any(alive(pid) for pid in seen):
                time.sleep(0.1)
            self.assertEqual([pid for pid in seen if alive(pid)], [])
        finally:
            for pid in seen:  # only the recorded pids
                if alive(pid):
                    os.kill(pid, signal.SIGKILL)
            proc.wait()

    def test_a_bad_jobs_value_is_a_bad_request(self) -> None:
        with self.assertRaisesRegex(build.UsageError, "CAD_MODEL_BUILD_JOBS"):
            self.run_with("zero", "bad")


if __name__ == "__main__":
    unittest.main()
