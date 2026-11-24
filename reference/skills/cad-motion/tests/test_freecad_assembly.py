# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
spec = importlib.util.spec_from_file_location("cad_motion_freecad_lifecycle", SCRIPTS / "freecad_assembly.py")
assert spec and spec.loader
freecad = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = freecad
spec.loader.exec_module(freecad)


class FreecadResultLifecycleTests(unittest.TestCase):
    def test_smoke_frames_selects_start_middle_and_end(self) -> None:
        frames = [{"frame": index} for index in range(11)]
        self.assertEqual([frame["frame"] for frame in freecad.smoke_frames(frames)], [0, 5, 10])

    def test_result_must_be_valid_and_for_this_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "result.json"
            for result in ({"run_id": "old", "status_sim": 0, "frames": [{}]},
                           {"run_id": "run", "status_sim": 1, "frames": [{}]},
                           {"run_id": "run", "status_sim": 0, "frames": []}):
                path.write_text(json.dumps(result), encoding="utf-8")
                self.assertIsNone(freecad._validated_result(path, "run"))
            valid = {"run_id": "run", "status_sim": 0, "frames": [{}]}
            path.write_text(json.dumps(valid), encoding="utf-8")
            self.assertEqual(freecad._validated_result(path, "run"), valid)

    @unittest.skipUnless(os.name == "posix", "the process-group contract is POSIX")
    def test_run_job_returns_on_valid_result_and_reaps_lingering_child(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "result.json"
            executable = root / "fake-freecad"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import json, pathlib, sys, time\n"
                "spec=json.loads(pathlib.Path(sys.argv[1] + '.spec').read_text())\n"
                "pathlib.Path(spec['result']).write_text(json.dumps({'run_id':spec['run_id'],'status_sim':0,'frames':[{}]}))\n"
                "time.sleep(30)\n", encoding="utf-8")
            executable.chmod(0o755)
            spec_path = root / "job.py.spec"
            job_path = root / "job.py"
            job_path.write_text("# no-op", encoding="utf-8")
            spec_path.write_text(json.dumps({"result": str(result_path), "run_id": "smoke-run"}), encoding="utf-8")
            started = __import__("time").monotonic()
            result, warnings, code = freecad.run_job(
                executable, root,
                {"result": str(result_path), "run_id": "smoke-run"},
                timeout=5)
            elapsed = __import__("time").monotonic() - started
            self.assertEqual(result["run_id"], "smoke-run")
            self.assertEqual(code, -15)
            self.assertLess(elapsed, 2.0)
            self.assertTrue(result_path.is_file())

    VALID = {"run_id": "race-run", "status_sim": 0, "frames": [{}]}

    def run_with_exit_after_first_read(self, root: Path, before: str | None) -> dict:
        """run_job against a stand-in process that writes the complete result and exits between the parent's
        first result read and its first poll(): the ordering a fast FreeCAD job hits under load. `before` is
        what the result file holds at that first read (None: no file)."""
        result_path = root / "result.json"
        if before is not None:
            result_path.write_text(before, encoding="utf-8")

        class ExitsAfterFirstRead:
            pid, returncode = -1, None

            def poll(self) -> int | None:
                if self.returncode is None:
                    result_path.write_text(json.dumps(FreecadResultLifecycleTests.VALID), encoding="utf-8")
                    self.returncode = 0
                return self.returncode

            def wait(self, timeout: float | None = None) -> int:
                return self.poll()

        spec = {"result": str(result_path), "run_id": "race-run"}
        with patch.object(freecad.subprocess, "Popen", return_value=ExitsAfterFirstRead()):
            result, _, code = freecad.run_job(root / "fake-freecad", root, spec, timeout=5)
        self.assertEqual(code, 0)
        return result

    def test_a_job_that_writes_its_result_and_exits_after_the_first_read_is_read_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_with_exit_after_first_read(Path(tmp), None), self.VALID)

    def test_a_partial_result_read_before_the_job_exits_is_read_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_with_exit_after_first_read(Path(tmp), '{"run_id": "race-'), self.VALID)

    @unittest.skipUnless(os.name == "posix", "runs the job script in a child Python")
    def test_the_job_never_leaves_a_partial_result_at_the_result_path(self) -> None:
        # The job stops while it writes its result; a parent polling the result path must never see the part.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result_path = root / "result.json"
            spec_path = root / "spec.json"
            spec_path.write_text(json.dumps({"result": str(result_path), "run_id": "race-run", "marker": "M"}),
                                 encoding="utf-8")
            job = root / "job.py"
            job.write_text(freecad.JOB.replace("__SPEC_PATH__", json.dumps(str(spec_path))), encoding="utf-8")
            interrupted = ("import json\n"
                           "def dump(obj, handle, **kwargs):\n"
                           "    handle.write('{\"run_id\": ')\n"
                           "    handle.flush()\n"
                           "    raise OSError('the job stopped mid-write')\n"
                           "json.dump = dump\n"
                           f"exec(compile(open({str(job)!r}).read(), {str(job)!r}, 'exec'))\n")
            subprocess.run([sys.executable, "-c", interrupted], cwd=root, capture_output=True, timeout=60)
            self.assertFalse(result_path.exists(), result_path.read_text(encoding="utf-8")
                             if result_path.exists() else "")


if __name__ == "__main__":
    unittest.main()
