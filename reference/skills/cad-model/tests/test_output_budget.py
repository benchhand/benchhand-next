#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Sjors Robroek
#
# SPDX-License-Identifier: MPL-2.0

"""stdout size of the switched producers in compact mode, on the lamp-arm example.

Run: python3 -m unittest discover -s skills/cad-model/tests -p test_output_budget.py -v
The tests build the example once with cad_model.py (CadQuery, `uv`), then run each switched producer in json and compact modes.

Byte budgets (stdout of one command in compact mode, lamp-arm example, v1 built from examples/lamp-arm/hw):

    command               before    json (enveloped)   compact   budget
    cad_model run           5534           6067            172      400
    cad_model check        97003         104331            176      400
    cad_model latest         174            268            178      250
    form_check --version   12563          13787            430      800
    validate                 700           1472            385      700

"before" is the bare JSON of main. The envelope repeats `findings` beside the payload, which shows most in
validate. The compact column includes a scratch path of about 100 bytes; a shorter path shortens it.

Raise a budget only with a reason in the commit message: each byte is read by an agent on every call.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import result_payload  # noqa: E402

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
SCRIPTS = HERE.parent / "scripts"

LAMP_HW = SKILLS.parent / "examples" / "lamp-arm" / "hw"
CAD_MODEL = SCRIPTS / "cad_model.py"
FORM_CHECK = SKILLS / "cad-design" / "scripts" / "form_check.py"
VALIDATE = SKILLS / "cad-record" / "scripts" / "validate.py"

PLAIN_ENV = {**os.environ, "CAD_OUTPUT": "json"}
AGENT_ENV = {**os.environ, "CAD_OUTPUT": "compact"}

# Compact-mode stdout bytes per command on the lamp-arm example; see the table in the module docstring.
BUDGETS = {"run": 400, "check": 400, "latest": 250, "form_check": 800, "validate": 700}


def without_timings(value: object) -> object:
    """`value` without the wall-clock fields, which differ between two runs of one command."""
    if isinstance(value, dict):
        return {k: without_timings(v) for k, v in value.items() if k not in ("timings_s", "seconds", "wall_s")}
    if isinstance(value, list):
        return [without_timings(v) for v in value]
    return value


@unittest.skipUnless(shutil.which("uv"), "uv is required to run the producers")
class LampArmTests(unittest.TestCase):
    """Each switched producer on the lamp-arm example: summary, full file and unchanged plain output."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hw = Path(cls.tmp.name) / "hw"
        shutil.copytree(LAMP_HW, cls.hw)
        cls.run_result = cls.tool(CAD_MODEL, "run", str(cls.hw), "--label", "v1", env=PLAIN_ENV)
        assert cls.run_result.returncode == 0, cls.run_result.stderr[-3000:]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tmp.cleanup()

    @staticmethod
    def tool(script: Path, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        # no timeout: a cold uv cache builds CadQuery's environment first
        return subprocess.run(["uv", "run", "--quiet", "--script", str(script), *args], capture_output=True,
                              text=True, env=env, check=False)

    def commands(self) -> dict[str, tuple[Path, tuple[str, ...]]]:
        hw = str(self.hw)
        return {"check": (CAD_MODEL, ("check", "v1", "--hw", hw, "--no-cache")),
                "latest": (CAD_MODEL, ("latest", hw, "--label", "v1")),
                "form_check": (FORM_CHECK, ("--hw", hw, "--version", "v1", "--out", str(self.hw.parent / ".cad-work" / "p.json"))),
                "validate": (VALIDATE, (hw,))}

    def both(self, name: str) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
        script, args = self.commands()[name]
        return self.tool(script, *args, env=PLAIN_ENV), self.tool(script, *args, env=AGENT_ENV)

    def test_every_producer_names_a_full_json_file_equal_to_its_plain_stdout_with_the_same_exit_code(self) -> None:
        for name in self.commands():
            with self.subTest(command=name):
                plain, agent = self.both(name)
                self.assertEqual(agent.returncode, plain.returncode, agent.stderr[-2000:])
                last = agent.stdout.rstrip("\n").splitlines()[-1]
                # a result shorter than its summary (latest) is printed in full
                full = (Path(last.removeprefix("full JSON: ")).read_text(encoding="utf-8")
                        if last.startswith("full JSON: ") else agent.stdout)
                self.assertEqual(without_timings(json.loads(full)), without_timings(json.loads(plain.stdout)))
                self.assertLessEqual(len(agent.stdout.encode()), BUDGETS[name], agent.stdout)
                self.assertLessEqual(len(agent.stdout), len(plain.stdout) + 1)

    def test_the_json_flag_prints_full_json_though_the_environment_says_compact(self) -> None:
        # check's result is large, so compact mode summarizes it whatever lamp-arm's verdict; a full envelope
        # under CAD_OUTPUT=compact can then only come from --json
        args = ("check", "v1", "--hw", str(self.hw), "--no-cache")
        # the control runs first: the first check publishes the readback packet, so both compared runs reuse it
        control = self.tool(CAD_MODEL, *args, env=AGENT_ENV)
        self.assertIn("full JSON: ", control.stdout)
        plain = self.tool(CAD_MODEL, *args, env=PLAIN_ENV)
        agent = self.tool(CAD_MODEL, *args, "--json", env=AGENT_ENV)
        self.assertEqual(agent.returncode, plain.returncode, agent.stderr[-2000:])
        self.assertNotIn("full JSON: ", agent.stdout)
        self.assertEqual(without_timings(result_payload(agent.stdout)), without_timings(result_payload(plain.stdout)))

    def sealed(self, hw: Path) -> dict[str, str]:
        """sha256 of every file the build sealed under hw/versions, by path below hw/."""
        versions = hw / "versions"
        return {p.relative_to(hw).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(versions.rglob("*")) if p.is_file()}

    def test_cad_model_run_summary_stays_inside_its_budget_and_seals_the_same_bytes_as_a_json_run(self) -> None:
        other = Path(self.tmp.name) / "again"
        shutil.copytree(LAMP_HW, other / "hw")
        agent = self.tool(CAD_MODEL, "run", str(other / "hw"), "--label", "v1", env=AGENT_ENV)
        self.assertEqual(agent.returncode, 0, agent.stderr[-2000:])
        self.assertLessEqual(len(agent.stdout.encode()), BUDGETS["run"], agent.stdout)
        path = Path(agent.stdout.rstrip("\n").splitlines()[-1].removeprefix("full JSON: "))
        self.assertEqual(result_payload(path.read_text(encoding="utf-8"))["label"], "v1")
        sealed = self.sealed(self.hw)
        self.assertIn("versions/v1/manifest.json", sealed)
        self.assertEqual(self.sealed(other / "hw"), sealed)

    def test_cad_model_check_out_file_is_the_named_full_json(self) -> None:
        out = Path(self.tmp.name) / ".cad-work" / "check.json"
        out.parent.mkdir(exist_ok=True)
        agent = self.tool(CAD_MODEL, "check", "v1", "--hw", str(self.hw), "--out", str(out), env=AGENT_ENV)
        self.assertIn(f"full JSON: {out.resolve()}", agent.stdout)
        self.assertEqual(result_payload(out.read_text(encoding="utf-8"))["label"], "v1")


if __name__ == "__main__":
    unittest.main()
