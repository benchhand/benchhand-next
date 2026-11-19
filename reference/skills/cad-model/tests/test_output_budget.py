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

import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
from modload import load_module, result_payload  # noqa: E402

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parents[1]
SCRIPTS = HERE.parent / "scripts"

LAMP_HW = SKILLS.parent / "examples" / "lamp-arm" / "hw"
CAD_MODEL = SCRIPTS / "cad_model.py"
FORM_CHECK = SKILLS / "cad-design" / "scripts" / "form_check.py"
VALIDATE = SKILLS / "cad-record" / "scripts" / "validate.py"
emit = load_module("cad_record_emit", SKILLS / "cad-record" / "scripts" / "emit.py")

PLAIN_ENV = {**os.environ, "CAD_OUTPUT": "json"}
AGENT_ENV = {**os.environ, "CAD_OUTPUT": "compact"}

# Compact-mode stdout bytes per command on the lamp-arm example; see the table in the module docstring.
BUDGETS = {"run": 400, "check": 400, "latest": 250, "form_check": 800, "validate": 700}


ROOT_MARK = "<tmp>"
SHORT_ROOT = "/tmp"  # the clip-position roots are built under a short base, whatever TMPDIR is


def _forms(path: Path | str) -> set[str]:
    return {str(path), str(Path(path).resolve())}


def measured(stdout: str, *roots: Path | str, paths: tuple[Path | str, ...] = ()) -> int:
    """Bytes of `stdout` with each temp root (as given and resolved) replaced by a fixed mark.

    The tools print absolute paths under the test's temp dir, whose length depends on the machine's TMPDIR
    and on symlinks such as macOS /var -> /private/var. The budget counts the tool's own output, not that prefix.

    The emitter clips a fact line to `emit.MAX_LINE` characters, ending it with "…", so a long root also cuts the
    path's tail or the root itself. `paths` names the files a tool may print under the roots: a clipped line
    whose path fragment is a prefix of one of them is first restored to that full path, so the count does not
    depend on where the clip fell. Text after the path on a clipped line is not recoverable and is not counted.
    """
    known = sorted({form for path in paths for form in _forms(path)}, key=len, reverse=True)
    lines = []
    for line in stdout.split("\n"):
        start = line.find("/")
        if len(line) == emit.MAX_LINE and line.endswith("…") and start >= 0:
            fragment = line[start:-1]
            full = next((path for path in known if path.startswith(fragment)), None)
            if full is not None:
                line = line[:start] + full
        lines.append(line)
    stdout = "\n".join(lines)
    for form in sorted({form for root in roots for form in _forms(root)}, key=len, reverse=True):
        stdout = stdout.replace(form, ROOT_MARK)
    return len(stdout.encode())


def assert_within_budget(case: unittest.TestCase, stdout: str, budget: int, *roots: Path | str,
                         paths: tuple[Path | str, ...] = ()) -> None:
    """Fail `case` when `stdout`, counted by `measured`, is over `budget` bytes."""
    case.assertLessEqual(measured(stdout, *roots, paths=paths), budget, stdout)


class MeasuredTests(unittest.TestCase):
    """`measured` counts the tool's own bytes whatever the temp root's length."""

    SAMPLE = "packet: {root}/.cad-work/p.json\nfull JSON: {root}/.cad-work/agent-output/x-1234.json\n3 findings\n"

    def test_the_same_output_counts_equal_under_temp_roots_of_different_length(self) -> None:
        with tempfile.TemporaryDirectory() as base:
            short, long = Path(base) / "a", Path(base) / ("d" * 60)
            short.mkdir()
            long.mkdir()
            counts = {measured(self.SAMPLE.format(root=r), r) for r in (short, long)}
        self.assertEqual(len(counts), 1)

    def test_a_symlinked_root_counts_like_its_resolved_form(self) -> None:
        with tempfile.TemporaryDirectory() as base:
            real = Path(base).resolve() / "real"
            real.mkdir()
            link = Path(base).resolve() / "link"
            link.symlink_to(real)
            self.assertEqual(measured(self.SAMPLE.format(root=real), link), measured(self.SAMPLE.format(root=link), link))

    @staticmethod
    def emitted(packet: Path, out: Path) -> str:
        """Compact stdout of the real emitter, as form_check calls it: the packet path is a fact, which it clips."""
        out.parent.mkdir(parents=True, exist_ok=True)
        stream = io.StringIO()
        with mock.patch.dict(os.environ, {"CAD_OUTPUT": "compact"}):
            emit.emit({"blob": "x" * 5000}, tool="form_check", name="form_check", code=0, out=out,
                      facts={"version": "v1", "packet": str(packet)}, stream=stream)
        return stream.getvalue()

    def short_base(self) -> Path:
        """A fresh directory on a short fixed root, so the clip-position roots fit whatever TMPDIR is."""
        if not Path(SHORT_ROOT).is_dir():
            self.skipTest(f"{SHORT_ROOT} does not exist: no short base for the clip-position roots")
        base = Path(tempfile.mkdtemp(dir=SHORT_ROOT)).resolve()
        self.addCleanup(shutil.rmtree, base, True)
        self.assertLess(len(str(base)), emit.MAX_LINE - len("packet: ") - len("/.cad-work/p.json") - 40, base)
        return base

    def test_the_emitters_clipped_packet_path_counts_equal_whatever_the_root_length(self) -> None:
        # the packet line is "packet: " + root + "/.cad-work/p.json", clipped to emit.MAX_LINE characters
        suffix = len("/.cad-work/p.json")
        base = self.short_base()
        roots = {"short": len(str(base)) + 3,
                 "just under the clip": emit.MAX_LINE - len("packet: ") - suffix - 5,
                 "clip inside the suffix": emit.MAX_LINE - len("packet: ") - 4,
                 "clip inside the root": emit.MAX_LINE + 40}
        counts = {}
        for label, length in roots.items():
            root = base / ("d" * (length - len(str(base)) - 1))
            self.assertEqual(len(str(root)), length)
            packet = root / ".cad-work" / "p.json"
            counts[label] = measured(self.emitted(packet, root / ".cad-work" / "o.json"), root, paths=(packet,))
        deep = base / ("e" * (emit.MAX_LINE + 40 - len(str(base)) - 1))
        deep.mkdir()
        link = base / "l"
        link.symlink_to(deep)
        for label, shown in (("symlink, packet as given", link), ("symlink, packet resolved", deep)):
            packet = shown / ".cad-work" / "p.json"
            counts[label] = measured(self.emitted(packet, link / ".cad-work" / "o.json"), link,
                                     paths=(link / ".cad-work" / "p.json",))
        self.assertEqual(len(set(counts.values())), 1, counts)

    def test_the_budget_accepts_its_limit_and_rejects_one_byte_more(self) -> None:
        with tempfile.TemporaryDirectory() as base:
            head = f"packet: {base}/p.json\n"
            at_limit = head + "x" * (800 - measured(head, base) - 1) + "\n"
            assert_within_budget(self, at_limit, 800, base)
            with self.assertRaises(AssertionError):
                assert_within_budget(self, at_limit + "x", 800, base)

    def test_growth_in_the_tools_own_lines_still_counts(self) -> None:
        with tempfile.TemporaryDirectory() as base:
            text = self.SAMPLE.format(root=base)
            extra = "finding: x\n"
            self.assertEqual(measured(text + extra, base) - measured(text, base), len(extra))


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

    def printed_paths(self) -> tuple[Path, ...]:
        """The files a producer prints as facts, which the emitter may clip."""
        return (self.hw.parent / ".cad-work" / "p.json",)

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
                assert_within_budget(self, agent.stdout, BUDGETS[name], self.tmp.name, paths=self.printed_paths())
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
        assert_within_budget(self, agent.stdout, BUDGETS["run"], self.tmp.name)
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
